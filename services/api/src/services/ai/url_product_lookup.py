from __future__ import annotations

import json
import re
from html import unescape
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from ...pipelines.extract.official_site import (
    clean_text,
    infer_handle_from_url,
    normalize_product_url,
    parse_product_json,
    producer_from_payload,
)

URL_RE = re.compile(r"(https?://[^\s<>()\"']+)", flags=re.IGNORECASE)
TITLE_RE = re.compile(r"<title>(.*?)</title>", flags=re.IGNORECASE | re.DOTALL)
META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?P<key>[^"\']+)["\'][^>]+content=["\'](?P<value>.*?)["\']',
    flags=re.IGNORECASE | re.DOTALL,
)
LINK_REL_RE = re.compile(
    r'<link[^>]+rel=["\'](?P<rel>[^"\']+)["\'][^>]+href=["\'](?P<href>.*?)["\']',
    flags=re.IGNORECASE | re.DOTALL,
)
JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<body>.*?)</script>',
    flags=re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")

SELL_INTENT_PATTERNS = (
    r"\u6709\u8ce3",
    r"\u6709\u6c92\u6709\u8ce3",
    r"\u6709\u6c92\u6709\u9019\u6b3e",
    r"\u6709\u9019\u652f",
    r"\u53ef\u4ee5\u5831\u50f9",
    r"\u80fd\u4e0d\u80fd\u5831\u50f9",
    r"\u8a62\u50f9",
    r"\u5831\u50f9",
    r"\u5eab\u5b58",
    r"\u73fe\u8ca8",
    r"\u6709\u8ca8",
    r"\u53ef\u552e",
    r"\u8cfc\u8cb7",
    r"\u8cb7\u5230",
    r"\bdo you sell\b",
    r"\bdo you have\b",
    r"\bare you selling\b",
    r"\bcan i quote\b",
    r"\bquote\b",
    r"\bstock\b",
    r"\binventory\b",
    r"\bavailability\b",
    r"\bavailable\b",
)

REGION_KEYWORDS = {
    "champagne": "champagne",
    "burgundy": "burgundy",
    "bourgogne": "burgundy",
    "bordeaux": "bordeaux",
    "alsace": "alsace",
    "loire": "loire",
    "rhone": "rhone",
    "rhone valley": "rhone",
}


class UrlProductLookupService:
    def __init__(self) -> None:
        self._timeout_seconds = 8.0

    @staticmethod
    def extract_first_url(text: str) -> Optional[str]:
        match = URL_RE.search(text or "")
        if not match:
            return None
        return match.group(1).rstrip(".,);:!?")

    @staticmethod
    def infer_lookup_goal(text: str) -> Optional[str]:
        haystack = str(text or "")
        for pattern in SELL_INTENT_PATTERNS:
            if re.search(pattern, haystack, flags=re.IGNORECASE):
                return "product_availability_from_url"
        return None

    async def analyze_query(self, text: str, *, primary_url: Optional[str] = None) -> Dict[str, Any]:
        original_url = str(primary_url or "").strip() or self.extract_first_url(text)
        if not original_url:
            return {}

        parsed_url = urlparse(original_url)
        variant_id = self._first_query_value(parsed_url.query, "variant")
        canonical_url = self._normalize_canonical_url(original_url)
        product_handle = infer_handle_from_url(canonical_url)
        result: Dict[str, Any] = {
            "original_url": original_url,
            "canonical_url": canonical_url,
            "domain": parsed_url.netloc.lower().lstrip("www."),
            "product_handle": product_handle or None,
            "variant_id": variant_id,
            "parse_status": "pending",
            "product_identity_confirmed": False,
            "lookup_goal": self.infer_lookup_goal(text),
            "official_page_confirmed": False,
            "page_title": "",
            "meta_description": "",
            "entity_hints": {},
            "search_query": "",
        }

        try:
            fetched = await self._fetch_product_page(original_url)
        except Exception as exc:
            result["parse_status"] = "failed"
            result["fetch_error"] = f"{type(exc).__name__}: {exc}"
            fallback_hints = self._fallback_hints_from_handle(product_handle)
            result["entity_hints"] = fallback_hints
            result["search_query"] = self._build_search_query(fallback_hints)
            return result

        canonical_url = fetched.get("canonical_url") or canonical_url
        product_handle = infer_handle_from_url(canonical_url) or product_handle
        page_title = str(fetched.get("title") or "").strip()
        meta_description = str(fetched.get("meta_description") or "").strip()
        product_payload = fetched.get("product_payload") if isinstance(fetched.get("product_payload"), dict) else {}
        json_ld_product = fetched.get("json_ld_product") if isinstance(fetched.get("json_ld_product"), dict) else {}

        entity_hints = self._build_entity_hints(
            product_handle=product_handle,
            page_title=page_title,
            meta_description=meta_description,
            product_payload=product_payload,
            json_ld_product=json_ld_product,
        )
        search_query = self._build_search_query(entity_hints)
        result.update(
            {
                "canonical_url": canonical_url,
                "product_handle": product_handle or None,
                "page_title": page_title,
                "meta_description": meta_description,
                "product_identity_confirmed": bool(
                    entity_hints.get("wine_name")
                    or entity_hints.get("full_wine_name")
                    or entity_hints.get("producer")
                ),
                "official_page_confirmed": bool(page_title or product_payload or json_ld_product),
                "parse_status": "resolved"
                if (page_title or product_payload or json_ld_product or product_handle)
                else "failed",
                "entity_hints": entity_hints,
                "search_query": search_query,
            }
        )
        if result["parse_status"] == "failed":
            fallback_hints = self._fallback_hints_from_handle(product_handle)
            for key, value in fallback_hints.items():
                entity_hints.setdefault(key, value)
            result["entity_hints"] = entity_hints
            result["search_query"] = search_query or self._build_search_query(entity_hints)
        return result

    async def _fetch_product_page(self, url: str) -> Dict[str, Any]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
        html = response.text
        final_url = str(response.url)
        canonical_href = self._extract_canonical_href(html)
        canonical_url = self._normalize_canonical_url(
            normalize_product_url(final_url, canonical_href) if canonical_href else final_url
        )
        page_title = self._extract_title(html)
        meta_description = self._extract_meta_description(html)
        product_payload = parse_product_json(html) or {}
        json_ld_product = self._extract_json_ld_product(html)
        return {
            "canonical_url": canonical_url,
            "title": page_title,
            "meta_description": meta_description,
            "product_payload": product_payload,
            "json_ld_product": json_ld_product,
        }

    @staticmethod
    def _first_query_value(query_string: str, key: str) -> Optional[str]:
        values = parse_qs(query_string or "").get(key) or []
        for value in values:
            normalized = str(value or "").strip()
            if normalized:
                return normalized
        return None

    @staticmethod
    def _normalize_canonical_url(url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return str(url or "").strip()
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if "/collections/" in parsed.path and "/products/" in parsed.path:
            normalized = normalize_product_url(normalized, normalized)
        return normalized

    @staticmethod
    def _extract_title(html: str) -> str:
        match = TITLE_RE.search(html or "")
        if not match:
            return ""
        return clean_text(match.group(1))

    @staticmethod
    def _extract_meta_description(html: str) -> str:
        for match in META_RE.finditer(html or ""):
            key = str(match.group("key") or "").strip().lower()
            if key in {"description", "og:description", "twitter:description"}:
                return clean_text(match.group("value"))
        return ""

    @staticmethod
    def _extract_canonical_href(html: str) -> Optional[str]:
        for match in LINK_REL_RE.finditer(html or ""):
            rel = str(match.group("rel") or "").strip().lower()
            if rel == "canonical":
                href = str(match.group("href") or "").strip()
                if href:
                    return href
        return None

    @staticmethod
    def _extract_json_ld_product(html: str) -> Dict[str, Any]:
        for match in JSON_LD_RE.finditer(html or ""):
            body = str(match.group("body") or "").strip()
            if not body:
                continue
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                continue
            candidate = UrlProductLookupService._select_product_json_ld(payload)
            if candidate:
                return candidate
        return {}

    @staticmethod
    def _select_product_json_ld(payload: Any) -> Dict[str, Any]:
        if isinstance(payload, list):
            for item in payload:
                candidate = UrlProductLookupService._select_product_json_ld(item)
                if candidate:
                    return candidate
            return {}
        if not isinstance(payload, dict):
            return {}
        graph = payload.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                candidate = UrlProductLookupService._select_product_json_ld(item)
                if candidate:
                    return candidate
        type_value = payload.get("@type")
        if isinstance(type_value, list):
            type_names = [str(item or "").lower() for item in type_value]
        else:
            type_names = [str(type_value or "").lower()]
        if "product" in type_names:
            return payload
        return {}

    @classmethod
    def _build_entity_hints(
        cls,
        *,
        product_handle: str,
        page_title: str,
        meta_description: str,
        product_payload: Dict[str, Any],
        json_ld_product: Dict[str, Any],
    ) -> Dict[str, Any]:
        producer = cls._normalize_space(
            producer_from_payload(product_payload)
            or cls._extract_brand_name(json_ld_product)
            or cls._extract_vendor_from_text(page_title)
        )
        product_title = cls._normalize_space(
            str(product_payload.get("title") or json_ld_product.get("name") or "").strip()
            or cls._clean_page_title(page_title)
        )
        if not product_title and product_handle:
            product_title = cls._title_from_handle(product_handle)
        wine_name = product_title
        if producer and wine_name.lower().startswith(producer.lower()):
            wine_name = wine_name[len(producer) :].strip(" ,/-")
        wine_name = cls._normalize_space(wine_name)
        vintage = cls._extract_vintage(" ".join(part for part in [product_title, page_title, meta_description] if part))
        region = cls._extract_region(" ".join(part for part in [product_title, meta_description] if part))
        hints: Dict[str, Any] = {}
        if producer:
            hints["producer"] = producer
        if wine_name:
            hints["wine_name"] = wine_name
        if product_title:
            hints["full_wine_name"] = product_title
        if vintage:
            hints["vintage"] = vintage
        if region:
            hints["region"] = region
        if product_handle:
            hints["product_handle"] = product_handle
        return hints

    @staticmethod
    def _extract_brand_name(json_ld_product: Dict[str, Any]) -> str:
        brand = json_ld_product.get("brand")
        if isinstance(brand, dict):
            return str(brand.get("name") or "").strip()
        return str(brand or "").strip()

    @staticmethod
    def _extract_vendor_from_text(title: str) -> str:
        segments = [segment.strip() for segment in re.split(r"[|｜\-–—]+", title or "") if segment.strip()]
        if len(segments) >= 2:
            return segments[0]
        return ""

    @staticmethod
    def _clean_page_title(title: str) -> str:
        segments = [segment.strip() for segment in re.split(r"[|｜]+", title or "") if segment.strip()]
        if not segments:
            return ""
        return segments[0]

    @staticmethod
    def _title_from_handle(handle: str) -> str:
        raw = str(handle or "").strip("-_/ ")
        if not raw:
            return ""
        return " ".join(part.capitalize() for part in raw.split("-") if part)

    @staticmethod
    def _extract_vintage(text: str) -> Optional[str]:
        match = re.search(r"\b((?:19|20)\d{2})\b", str(text or ""))
        return match.group(1) if match else None

    @staticmethod
    def _extract_region(text: str) -> Optional[str]:
        lowered = str(text or "").lower()
        for keyword, normalized in REGION_KEYWORDS.items():
            if keyword in lowered:
                return normalized
        return None

    @classmethod
    def _fallback_hints_from_handle(cls, handle: str) -> Dict[str, Any]:
        title = cls._title_from_handle(handle)
        if not title:
            return {}
        vintage = cls._extract_vintage(title)
        hints: Dict[str, Any] = {
            "full_wine_name": title,
            "wine_name": re.sub(r"\b(?:19|20)\d{2}\b", "", title).strip(" -"),
        }
        if vintage:
            hints["vintage"] = vintage
        producer_guess = cls._extract_producer_from_handle(title)
        if producer_guess:
            hints["producer"] = producer_guess
        region = cls._extract_region(title)
        if region:
            hints["region"] = region
        if handle:
            hints["product_handle"] = handle
        return hints

    @staticmethod
    def _extract_producer_from_handle(title: str) -> Optional[str]:
        tokens = [token for token in re.split(r"\s+", str(title or "").strip()) if token]
        if len(tokens) < 2:
            return None
        stop_tokens = {
            "grand",
            "cru",
            "premier",
            "1er",
            "rouge",
            "blanc",
            "rose",
            "champenois",
            "champagne",
            "bourgogne",
            "coteaux",
        }
        producer_tokens = []
        for token in tokens:
            if token.lower() in stop_tokens:
                break
            producer_tokens.append(token)
            if len(producer_tokens) >= 3:
                break
        if len(producer_tokens) >= 2:
            return " ".join(producer_tokens)
        return None

    @staticmethod
    def _build_search_query(entity_hints: Dict[str, Any]) -> str:
        parts = [
            str(entity_hints.get("producer") or "").strip(),
            str(entity_hints.get("wine_name") or entity_hints.get("full_wine_name") or "").strip(),
            str(entity_hints.get("vintage") or "").strip(),
            str(entity_hints.get("region") or "").strip(),
        ]
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _normalize_space(text: str) -> str:
        return " ".join(str(text or "").split()).strip()
