import os
import re
import time
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode, urlparse

import httpx

from ...schemas.ai import Hit

LOW_VALUE_DOMAINS = {
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "vivino.com",
    "www.vivino.com",
}

LOW_VALUE_PATH_TOKENS = {
    "/product",
    "/products",
    "/shop",
    "/store",
    "/cart",
    "/checkout",
    "/collections",
    "/search",
}

LOW_SIGNAL_TITLE_TOKENS = {
    "brands",
    "archive",
    "news",
    "blog",
    "catalog",
    "portfolio",
    "our producers",
    "producers",
}

LOW_SIGNAL_TEXT_TOKENS = {
    "cookie",
    "privacy policy",
    "terms of service",
    "newsletter",
    "subscribe",
    "wishlist",
    "add to cart",
    "javascript",
}

SECTION_KEYWORDS = {
    "background_story": {
        "zh": ("酒莊", "背景", "背景故事", "歷史", "家族", "創立", "故事"),
        "en": ("history", "background", "story", "family", "estate", "founded", "farming"),
    },
    "vineyard_region": {
        "zh": ("葡萄園", "產區", "產區資訊", "風土", "土壤", "地塊", "村莊"),
        "en": ("vineyard", "vineyards", "region", "terroir", "soil", "parcel", "appellation"),
    },
    "winemaking": {
        "zh": ("釀造", "釀造技巧", "發酵", "酒窖", "橡木桶", "培養", "工藝"),
        "en": ("winemaking", "vinification", "fermentation", "cellar", "oak", "barrel", "aging"),
    },
}

AUTHORITATIVE_EXTERNAL_CATEGORIES = {
    "brand_profile",
    "source_validation",
    "latest_info",
    "terroir_comparison",
    "url_product_lookup",
    "critic_score_lookup",
}

PLACEHOLDER_TEXT = "未找到足夠公開資訊"


SECTION_KEYWORDS["background_story"]["zh"] = ("背景", "故事", "歷史", "家族", "酒莊", "成立", "耕作")
SECTION_KEYWORDS["vineyard_region"]["zh"] = ("葡萄園", "產區", "風土", "土壤", "地塊", "村莊", "田塊")
SECTION_KEYWORDS["winemaking"]["zh"] = ("釀造", "發酵", "酒窖", "橡木桶", "熟成", "除渣", "浸皮")
PLACEHOLDER_TEXT = "沒有足夠可驗證內容"


class GoogleCseEvidenceService:
    def __init__(self) -> None:
        self._api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        self._cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        self._query_limit = max(1, min(int(os.getenv("EXTERNAL_SEARCH_QUERY_LIMIT", "6") or "6"), 6))
        self._fetch_limit = max(0, min(int(os.getenv("EXTERNAL_SEARCH_FETCH_LIMIT", "3") or "3"), 3))
        self._authoritative_fetch_limit = max(
            0,
            min(int(os.getenv("EXTERNAL_SEARCH_AUTHORITATIVE_FETCH_LIMIT", "3") or "3"), 3),
        )
        self._budget_seconds = max(5.0, float(os.getenv("EXTERNAL_SEARCH_BUDGET_SECONDS", "35") or "35"))
        self._google_timeout_seconds = max(
            3.0, float(os.getenv("EXTERNAL_SEARCH_GOOGLE_TIMEOUT_SECONDS", "10") or "10")
        )
        self._fetch_timeout_seconds = max(
            3.0, float(os.getenv("EXTERNAL_SEARCH_FETCH_TIMEOUT_SECONDS", "10") or "10")
        )

    def search(
        self,
        query: str,
        *,
        entity_hints: Optional[Dict[str, Any]] = None,
        prompt_category: Optional[str] = None,
        external_search_reason: Optional[str] = None,
        source_policy: str = "internal_preferred",
        needs_authoritative_sources: bool = False,
        internal_hit_count: int = 0,
        limit: int = 5,
        verified_domains: Optional[List[str]] = None,
        candidate_domains: Optional[List[str]] = None,
        request_deadline_at: Optional[float] = None,
    ) -> Tuple[List[Hit], Dict[str, str], Dict[str, Any]]:
        normalized_query = self._normalize_space(query)
        authoritative_query = bool(
            needs_authoritative_sources
            or (prompt_category or "").strip() in AUTHORITATIVE_EXTERNAL_CATEGORIES
            or external_search_reason
        )
        fetch_limit = self._authoritative_fetch_limit if authoritative_query else self._fetch_limit
        info: Dict[str, Any] = {
            "attempted": False,
            "reason": external_search_reason,
            "provider": "google_cse",
            "model": "google_cse",
            "query": normalized_query,
            "query_variants_used": [],
            "provider_attempts": 0,
            "hit_count_pre_filter": 0,
            "hit_count_post_filter": 0,
            "fetched_url_count": 0,
            "fetched_count": 0,
            "usable_fetched_count": 0,
            "authoritative_hit_count": 0,
            "search_results": [],
            "fetched_pages": [],
            "response_sections": {},
            "response_found": False,
            "sections_covered": [],
            "failure_reasons": [],
            "termination_reason": None,
            "provider_unavailable": False,
            "budget_exhausted": False,
            "quality_gate": None,
            "duration_ms": 0.0,
        }
        if not normalized_query or source_policy == "internal_only" or not authoritative_query:
            return [], {}, info

        info["attempted"] = True
        info["provider_attempts"] = 1
        if not self._api_key or not self._cse_id:
            info["termination_reason"] = "configuration_error"
            info["provider_unavailable"] = True
            info["failure_reasons"] = ["configuration_error"]
            return [], {"external_search": "Google Custom Search credentials are not configured."}, info

        producer_hint = self._producer_hint_from_entity_hints(entity_hints or {}) or self._infer_producer(query)
        query_variants = self._build_query_variants(normalized_query, producer_hint)[: self._query_limit]
        info["query_variants_used"] = query_variants
        verified_domains = verified_domains or []
        candidate_domains = candidate_domains or []
        started = time.perf_counter()
        errors: Dict[str, str] = {}
        raw_results: List[Dict[str, Any]] = []

        for variant in query_variants:
            if self._deadline_exceeded(started, request_deadline_at):
                info["termination_reason"] = "request_deadline_exceeded"
                break
            if self._budget_exceeded(started):
                info["termination_reason"] = "budget_exhausted"
                info["budget_exhausted"] = True
                break
            try:
                payload = self._google_search(variant, top_k=max(limit, 5), timeout=self._google_timeout_seconds)
            except Exception as exc:
                errors["external_search"] = f"{type(exc).__name__}: {exc}"
                info["termination_reason"] = "provider_timeout" if isinstance(exc, httpx.TimeoutException) else "provider_error"
                info["failure_reasons"] = [info["termination_reason"]]
                break
            normalized = self._normalize_search_results(payload, query=variant, producer=producer_hint)
            raw_results.extend(normalized)
            info["hit_count_pre_filter"] += len(payload.get("items", []) or [])
            if len(raw_results) >= max(limit, 5):
                break

        deduped_results = self._dedupe_search_results(raw_results)[: max(limit, 5)]
        info["search_results"] = deduped_results
        info["hit_count_post_filter"] = len(deduped_results)

        fetched_pages: List[Dict[str, Any]] = []
        usable_pages: List[Dict[str, Any]] = []
        for item in deduped_results[:fetch_limit]:
            if self._deadline_exceeded(started, request_deadline_at):
                info["termination_reason"] = "request_deadline_exceeded"
                break
            if self._budget_exceeded(started):
                info["termination_reason"] = "budget_exhausted"
                info["budget_exhausted"] = True
                break
            try:
                page = self._fetch_page(item["link"], timeout=self._fetch_timeout_seconds)
            except Exception as exc:
                fetched_pages.append(
                    {
                        "url": item["link"],
                        "title": item["title"],
                        "usable": False,
                        "fetch_error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            low_signal = self._is_low_signal_page(page, producer_hint)
            page_record = {
                "url": item["link"],
                "title": page.get("title") or item["title"],
                "meta_description": page.get("meta_description") or item.get("snippet", ""),
                "paragraphs": page.get("paragraphs") or [],
                "usable": not low_signal,
                "low_signal": low_signal,
            }
            fetched_pages.append(page_record)
            if not low_signal:
                usable_pages.append(page_record)

        info["fetched_pages"] = fetched_pages
        info["fetched_url_count"] = len(fetched_pages)
        info["fetched_count"] = sum(1 for page in fetched_pages if not page.get("fetch_error"))
        info["usable_fetched_count"] = len(usable_pages)

        combined_records: List[Dict[str, Any]] = []
        for item in deduped_results:
            record = {
                "title": item["title"],
                "url": item["link"],
                "snippet": item.get("snippet", ""),
                "meta_description": "",
                "paragraphs": [],
            }
            if self._is_low_signal_search_record(record, producer_hint):
                continue
            combined_records.append(record)
        combined_records.extend(usable_pages)

        response_sections = self._build_response_sections(combined_records, producer_hint)
        sections_covered = self._sections_covered(response_sections)
        producer_evidence_count = sum(
            1
            for item in deduped_results
            if self._mentions_producer(
                " ".join([item.get("title", ""), item.get("snippet", ""), item.get("link", "")]),
                producer_hint,
            )
        )
        failure_reasons: List[str] = []
        if len(deduped_results) < 2:
            failure_reasons.append("no_search_hits")
        if not usable_pages and not any(item.get("snippet") for item in deduped_results):
            failure_reasons.append("fetch_failed")
        if len(sections_covered) < 2:
            failure_reasons.append("insufficient_section_coverage")
        if producer_hint and producer_evidence_count < 1:
            failure_reasons.append("producer_not_confirmed")
        if not usable_pages:
            failure_reasons.append("no_usable_fetched_pages")

        response_found = (
            len(deduped_results) >= 2
            and len(usable_pages) >= 1
            and len(sections_covered) >= 2
            and (producer_evidence_count >= 1 or not producer_hint)
        )
        if not info["termination_reason"] and not response_found and failure_reasons:
            info["termination_reason"] = "insufficient_evidence"

        external_hits = self._build_hits(
            query=normalized_query,
            search_results=deduped_results,
            usable_pages=usable_pages,
            producer=producer_hint,
            response_sections=response_sections,
            verified_domains=verified_domains,
            candidate_domains=candidate_domains,
            authoritative=response_found,
        )
        info["response_sections"] = response_sections
        info["response_found"] = response_found
        info["sections_covered"] = sections_covered
        info["failure_reasons"] = failure_reasons
        info["authoritative_hit_count"] = len(external_hits) if response_found else 0
        info["quality_gate"] = "response_found" if response_found else (failure_reasons[0] if failure_reasons else "no_hits")
        info["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return external_hits, errors, info

    @staticmethod
    def _normalize_space(text: str) -> str:
        return " ".join((text or "").split()).strip()

    @classmethod
    def _producer_hint_from_entity_hints(cls, entity_hints: Dict[str, Any]) -> str:
        raw_value = (entity_hints or {}).get("producer")
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        for item in values:
            cleaned = cls._clean_producer_hint(item)
            if cleaned:
                return cleaned
        return ""

    @classmethod
    def _clean_producer_hint(cls, value: Any) -> str:
        text = cls._normalize_space(str(value or "").replace("\n", " ")).strip(" ,;:[]'")
        if not text:
            return ""
        lowered = text.lower()
        if lowered.startswith("[") and lowered.endswith("]"):
            return ""
        if any(
            token in lowered
            for token in (
                "wine advocate",
                "jasper morris",
                "burghound",
                "vinous",
                "decanter",
                "drinking window",
                "score",
                "page",
            )
        ):
            return ""
        return text

    @classmethod
    def _infer_producer(cls, text: str) -> Optional[str]:
        raw = cls._normalize_space(text)
        if not raw:
            return None
        patterns = [
            r"\b((?:YS|Champagne|Chateau|Château|Clos|Maison)\s+[A-Z][A-Za-z'&.\-]+(?:\s+[A-Z][A-Za-z'&.\-]+){0,5})\b",
            r"\b([A-Z][A-Za-z'&.\-]+(?:\s+[A-Z][A-Za-z'&.\-]+){1,5})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw)
            if not match:
                continue
            candidate = match.group(1).strip()
            if len(candidate.split()) >= 2 and cls._clean_producer_hint(candidate):
                return candidate
        return None

    @classmethod
    def _build_query_variants(cls, query: str, producer: Optional[str]) -> List[str]:
        variants: List[str] = []

        def push(value: str) -> None:
            normalized = cls._normalize_space(value)
            if normalized and normalized not in variants:
                variants.append(normalized)

        producer_name = producer or "YS Jean Marshall"
        push(query)
        lowered = query.lower()
        critic_tokens = ("wine advocate", "jasper", "burghound", "vinous", "decanter", "score", "rating")
        if any(token in lowered for token in critic_tokens):
            for source_name in ("Wine Advocate", "Jasper Morris", "Burghound", "Vinous", "Decanter"):
                push(f"\"{producer_name}\" \"{source_name}\" score rating")
            push(f"\"{producer_name}\" tasting note score")
            return variants
        if any(token in lowered for token in ("wine advocate", "jasper", "burghound", "vinous", "decanter", "score", "rating", "酒評", "分數")):
            push(f"\"{producer_name}\" Wine Advocate Jasper Morris Burghound Vinous Decanter score rating")
            push(f"\"{producer_name}\" critic score wine review")
            return variants
        if any(token in lowered for token in ("source", "reference", "official", "來源", "引用", "官網", "官方")):
            push(f"\"{producer_name}\" official source reference website")
            push(f"\"{producer_name}\" producer official website")
            return variants
        push(f"\"{producer_name}\" winery vineyard history winemaking")
        push(f"\"{producer_name}\" official winery vineyard history")
        return variants

    @staticmethod
    def _producer_tokens(producer: Optional[str]) -> List[str]:
        if not producer:
            return []
        ignore = {"ys", "chateau", "château", "champagne", "clos", "maison"}
        tokens = re.findall(r"[A-Za-z]+", producer.lower())
        normalized_tokens = [GoogleCseEvidenceService._normalize_match_token(token) for token in tokens]
        return [token for token in normalized_tokens if token not in ignore and len(token) > 1]

    @staticmethod
    def _normalize_match_token(token: str) -> str:
        return re.sub(r"(.)\1+", r"\1", str(token or "").lower())

    @classmethod
    def _mentions_producer(cls, text: str, producer: Optional[str]) -> bool:
        normalized = cls._normalize_space((text or "").lower())
        producer_norm = cls._normalize_space((producer or "").lower())
        if not normalized or not producer_norm:
            return False
        if producer_norm in normalized:
            return True
        tokens = cls._producer_tokens(producer)
        if not tokens:
            return False
        haystack_tokens = {
            cls._normalize_match_token(token)
            for token in re.findall(r"[A-Za-z]+", normalized)
            if len(token) > 1
        }
        hits = sum(1 for token in tokens if token in haystack_tokens)
        return hits >= min(2, len(tokens))

    def _google_search(self, query: str, *, top_k: int, timeout: float) -> Dict[str, Any]:
        params = {
            "q": query,
            "key": self._api_key,
            "cx": self._cse_id,
            "num": min(max(top_k, 1), 10),
        }
        url = f"https://www.googleapis.com/customsearch/v1?{urlencode(params)}"
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _is_low_value_result(link: str) -> bool:
        parsed = urlparse(link)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        if host in LOW_VALUE_DOMAINS:
            return True
        return any(token in path for token in LOW_VALUE_PATH_TOKENS)

    @classmethod
    def _normalize_search_results(
        cls,
        payload: Dict[str, Any],
        *,
        query: str,
        producer: Optional[str],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in payload.get("items", []) or []:
            title = cls._normalize_space(str(item.get("title") or ""))
            link = cls._normalize_space(str(item.get("link") or ""))
            snippet = cls._normalize_space(str(item.get("snippet") or ""))
            if not link or cls._is_low_value_result(link):
                continue
            evidence_text = " ".join(part for part in (title, snippet, link) if part)
            if producer and not cls._mentions_producer(evidence_text, producer):
                continue
            normalized.append(
                {
                    "query": query,
                    "title": title,
                    "link": link,
                    "snippet": snippet,
                    "display_link": cls._normalize_space(str(item.get("displayLink") or "")),
                }
            )
        return normalized

    @staticmethod
    def _dedupe_search_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen_links: set[str] = set()
        for item in results:
            link = str(item.get("link") or "").strip()
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            deduped.append(item)
        return deduped

    @classmethod
    def _strip_html(cls, html: str) -> str:
        without_scripts = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", html)
        without_tags = re.sub(r"(?is)<[^>]+>", " ", without_scripts)
        return cls._normalize_space(unescape(without_tags))

    @classmethod
    def _extract_title(cls, html: str) -> str:
        match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        return cls._normalize_space(unescape(match.group(1))) if match else ""

    @classmethod
    def _extract_meta_description(cls, html: str) -> str:
        patterns = [
            r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            r'(?is)<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return cls._normalize_space(unescape(match.group(1)))
        return ""

    @classmethod
    def _extract_paragraphs(cls, html: str) -> List[str]:
        paragraphs: List[str] = []
        for match in re.finditer(r"(?is)<p[^>]*>(.*?)</p>", html):
            text = cls._strip_html(match.group(1))
            if text and len(text) > 40 and text not in paragraphs:
                paragraphs.append(text)
        return paragraphs[:12]

    def _fetch_page(self, link: str, *, timeout: float) -> Dict[str, Any]:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ys-ai-google-cse/1.0; +https://localhost)",
            "Accept": "text/html,application/xhtml+xml",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(link, headers=headers)
            response.raise_for_status()
            html = response.text
        return {
            "url": link,
            "title": self._extract_title(html),
            "meta_description": self._extract_meta_description(html),
            "paragraphs": self._extract_paragraphs(html),
        }

    @classmethod
    def _split_sentences(cls, text: str) -> List[str]:
        raw = re.split(r"(?<=[。！？!?\.])\s+|\s*[\r\n]+\s*", text)
        sentences: List[str] = []
        for item in raw:
            normalized = cls._normalize_space(item)
            if len(normalized) >= 25 and normalized not in sentences:
                sentences.append(normalized)
        return sentences

    @staticmethod
    def _score_sentence(sentence: str, keywords: Sequence[str]) -> int:
        lowered = sentence.lower()
        return sum(1 for token in keywords if token.lower() in lowered)

    @staticmethod
    def _is_noisy_sentence(sentence: str) -> bool:
        if len(sentence) > 450:
            return True
        separators = sentence.count("|") + sentence.count(" / ") + sentence.count(" > ")
        if separators >= 2:
            return True
        lowered = sentence.lower()
        if sum(1 for token in LOW_SIGNAL_TEXT_TOKENS if token in lowered) >= 2:
            return True
        alpha_tokens = re.findall(r"[A-Za-z]{2,}", sentence)
        if len(alpha_tokens) >= 14 and len(set(token.lower() for token in alpha_tokens)) <= 6:
            return True
        return False

    @classmethod
    def _is_low_signal_page(cls, page: Dict[str, Any], producer: Optional[str]) -> bool:
        title = cls._normalize_space(str(page.get("title") or "")).lower()
        meta = cls._normalize_space(str(page.get("meta_description") or "")).lower()
        paragraphs = [p for p in page.get("paragraphs") or [] if p]
        combined = " ".join([title, meta] + paragraphs[:4]).lower()
        if any(token in title for token in LOW_SIGNAL_TITLE_TOKENS):
            return True
        if sum(1 for token in LOW_SIGNAL_TEXT_TOKENS if token in combined) >= 3:
            return True
        if paragraphs and sum(len(p) for p in paragraphs[:3]) > 3000:
            return True
        if producer and not cls._mentions_producer(combined, producer):
            return True
        if not paragraphs and len(meta) < 60:
            return True
        return False

    @classmethod
    def _is_low_signal_search_record(cls, record: Dict[str, Any], producer: Optional[str]) -> bool:
        title = cls._normalize_space(str(record.get("title") or "")).lower()
        snippet = cls._normalize_space(str(record.get("snippet") or "")).lower()
        combined = f"{title} {snippet}"
        if any(token in title for token in LOW_SIGNAL_TITLE_TOKENS):
            return True
        if sum(1 for token in LOW_SIGNAL_TEXT_TOKENS if token in combined) >= 2:
            return True
        if producer and not cls._mentions_producer(combined, producer):
            return True
        return False

    @classmethod
    def _collect_section_points(
        cls,
        records: Iterable[Dict[str, Any]],
        section: str,
        producer: Optional[str],
    ) -> List[str]:
        keywords = list(SECTION_KEYWORDS[section]["zh"]) + list(SECTION_KEYWORDS[section]["en"])
        scored: List[Tuple[int, str]] = []
        for record in records:
            producer_context = cls._mentions_producer(
                " ".join(
                    [
                        str(record.get("title") or ""),
                        str(record.get("snippet") or ""),
                        str(record.get("meta_description") or ""),
                        " ".join(record.get("paragraphs") or []),
                    ]
                ),
                producer,
            )
            candidates: List[str] = []
            for field in ("snippet", "meta_description"):
                value = cls._normalize_space(str(record.get(field) or ""))
                if value:
                    candidates.append(value)
            candidates.extend(record.get("paragraphs") or [])
            for sentence in candidates:
                for split_sentence in cls._split_sentences(sentence):
                    if producer and not producer_context and not cls._mentions_producer(split_sentence, producer):
                        continue
                    if cls._is_noisy_sentence(split_sentence):
                        continue
                    score = cls._score_sentence(split_sentence, keywords)
                    if score > 0:
                        scored.append((score, split_sentence))
        scored.sort(key=lambda item: (-item[0], len(item[1])))
        points: List[str] = []
        for _, sentence in scored:
            if sentence not in points:
                points.append(sentence)
            if len(points) >= 5:
                break
        return points

    @classmethod
    def _build_response_sections(
        cls,
        records: List[Dict[str, Any]],
        producer: Optional[str],
    ) -> Dict[str, List[str]]:
        sections: Dict[str, List[str]] = {}
        for section in ("background_story", "vineyard_region", "winemaking"):
            points = cls._collect_section_points(records, section, producer)
            sections[section] = points or [PLACEHOLDER_TEXT]
        return sections

    @staticmethod
    def _sections_covered(response_sections: Dict[str, List[str]]) -> List[str]:
        covered: List[str] = []
        for key, points in response_sections.items():
            if any(point != PLACEHOLDER_TEXT for point in points):
                covered.append(key)
        return covered

    @classmethod
    def _build_hits(
        cls,
        *,
        query: str,
        search_results: List[Dict[str, Any]],
        usable_pages: List[Dict[str, Any]],
        producer: Optional[str],
        response_sections: Dict[str, List[str]],
        verified_domains: List[str],
        candidate_domains: List[str],
        authoritative: bool,
    ) -> List[Hit]:
        hits: List[Hit] = []
        tier = "external_evidence" if authoritative else "external_unverified"
        page_lookup = {str(page.get("url") or ""): page for page in usable_pages}
        for item in search_results[:5]:
            page = page_lookup.get(item["link"], {})
            text_parts = []
            if item.get("snippet"):
                text_parts.append(item["snippet"])
            text_parts.extend(page.get("paragraphs") or [])
            text = cls._normalize_space(" ".join(text_parts[:4]))
            if producer and not cls._mentions_producer(" ".join([item.get("title", ""), text]), producer):
                continue
            if not text:
                text = item.get("snippet") or ""
            domain = (urlparse(item["link"]).netloc or "").lower().lstrip("www.")
            hits.append(
                Hit(
                    id=item["link"],
                    text=text,
                    summary=cls._normalize_space(
                        str(page.get("meta_description") or item.get("snippet") or item.get("title") or "")
                    )[:280],
                    meta={
                        "url": item["link"],
                        "title": item.get("title"),
                        "provider": "google_cse",
                        "query": query,
                        "query_variant": item.get("query"),
                        "display_link": item.get("display_link"),
                        "source_group": "external_search",
                        "source_kind": "external_search",
                        "source_tier": tier,
                        "producer": producer,
                        "verified_domain_match": domain in verified_domains,
                        "candidate_domain_match": domain in candidate_domains,
                        "response_sections": response_sections,
                    },
                    source_type="external",
                    source_tier=tier,
                )
            )
        return hits

    def _deadline_exceeded(self, started: float, request_deadline_at: Optional[float]) -> bool:
        return request_deadline_at is not None and time.monotonic() >= request_deadline_at

    def _budget_exceeded(self, started: float) -> bool:
        return (time.perf_counter() - started) >= self._budget_seconds
