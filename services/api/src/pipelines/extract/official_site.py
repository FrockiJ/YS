from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import httpx


PRODUCT_JSON_RE = re.compile(
    r'<script[^>]+id="ProductJson-product-template"[^>]*>(.*?)</script>',
    flags=re.DOTALL | re.IGNORECASE,
)
PRODUCT_LINK_RE = re.compile(
    r'href="(?P<href>(?:/collections/[^"]+/products/[^"?#]+)|(?:/products/[^"?#]+))"',
    flags=re.IGNORECASE,
)
STRIP_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
DESCRIPTION_BLOCK_RE = re.compile(
    r'<div[^>]+class="[^"]*(?:product-single__description|product-description|rte)[^"]*"[^>]*>(.*?)</div>',
    flags=re.DOTALL | re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title>(.*?)</title>", flags=re.DOTALL | re.IGNORECASE)
PRICE_RE = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")


def clean_text(value: str) -> str:
    text = unescape(STRIP_TAG_RE.sub(" ", value or ""))
    return WHITESPACE_RE.sub(" ", text).strip()


def infer_handle_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return ""
    if "products" in parts:
        idx = parts.index("products")
        if idx + 1 < len(parts):
            return parts[idx + 1].strip()
    return parts[-1].strip()


def normalize_product_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url.rstrip("/") + "/", href)
    parsed = urlparse(absolute)
    normalized_path = parsed.path
    if "/collections/" in normalized_path and "/products/" in normalized_path:
        normalized_path = "/products/" + infer_handle_from_url(absolute)
    return f"{parsed.scheme}://{parsed.netloc}{normalized_path}"


def parse_discovery_html(base_url: str, html: str) -> List[Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}
    for match in PRODUCT_LINK_RE.finditer(html or ""):
        href = match.group("href")
        url = normalize_product_url(base_url, href)
        handle = infer_handle_from_url(url)
        if not handle or handle in candidates:
            continue
        candidates[handle] = {
            "product_handle": handle,
            "official_url": url,
        }
    return list(candidates.values())


def parse_product_json(html: str) -> Optional[Dict[str, Any]]:
    match = PRODUCT_JSON_RE.search(html or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None


def extract_description_html(html: str) -> str:
    match = DESCRIPTION_BLOCK_RE.search(html or "")
    if match:
        return match.group(1).strip()
    return ""


def extract_description_text(html: str, product_json: Dict[str, Any]) -> str:
    description_html = extract_description_html(html)
    if description_html:
        return clean_text(description_html)
    for key in ("description", "body_html"):
        value = product_json.get(key)
        if isinstance(value, str) and value.strip():
            return clean_text(value)
    title_match = TITLE_RE.search(html or "")
    if title_match:
        return clean_text(title_match.group(1))
    return ""


def coerce_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = PRICE_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def normalize_images(images: Any) -> List[str]:
    results: List[str] = []
    for item in images or []:
        if isinstance(item, dict):
            value = item.get("src") or item.get("url")
        else:
            value = item
        if not value:
            continue
        text = str(value).strip()
        if text.startswith("//"):
            text = f"https:{text}"
        if text not in results:
            results.append(text)
    return results


def normalize_tags(tags: Any) -> List[str]:
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",")]
    results: List[str] = []
    for item in tags or []:
        text = str(item or "").strip()
        if text and text not in results:
            results.append(text)
    return results


def brand_from_payload(payload: Dict[str, Any]) -> str:
    for key in ("vendor", "brand"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def infer_availability(payload: Dict[str, Any]) -> Optional[bool]:
    variants = payload.get("variants") or []
    seen = False
    available = False
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        seen = True
        if variant.get("available"):
            available = True
            break
    if seen:
        return available
    published = payload.get("published")
    if isinstance(published, bool):
        return published
    return None


def normalize_variants(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for variant in payload.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        normalized.append(
            {
                "id": variant.get("id"),
                "title": variant.get("title"),
                "sku": variant.get("sku"),
                "barcode": variant.get("barcode"),
                "available": variant.get("available"),
                "price": coerce_price(variant.get("price")),
                "compare_at_price": coerce_price(variant.get("compare_at_price")),
            }
        )
    return normalized


def price_range(payload: Dict[str, Any], variants: List[Dict[str, Any]]) -> tuple[Optional[float], Optional[float]]:
    prices = [item.get("price") for item in variants if item.get("price") is not None]
    if not prices:
        direct = coerce_price(payload.get("price"))
        if direct is not None:
            return direct, direct
        return None, None
    return min(prices), max(prices)


def build_profile_from_product_page(
    *,
    base_url: str,
    product_url: str,
    html: str,
    search_terms: List[str],
) -> Optional[Dict[str, Any]]:
    payload = parse_product_json(html)
    if not payload:
        return None
    handle = str(payload.get("handle") or infer_handle_from_url(product_url)).strip()
    if not handle:
        return None

    variants = normalize_variants(payload)
    price_min, price_max = price_range(payload, variants)
    description_html = extract_description_html(html)
    description_text = extract_description_text(html, payload)
    normalized_url = normalize_product_url(base_url, product_url)
    images = normalize_images(payload.get("images") or ([payload.get("featured_image")] if payload.get("featured_image") else []))
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    profile = {
        "product_handle": handle,
        "product_title": str(payload.get("title") or handle).strip(),
        "brand": brand_from_payload(payload),
        "product_type": str(payload.get("type") or "").strip() or None,
        "official_url": normalized_url,
        "product_json_hash": payload_hash,
        "availability": infer_availability(payload),
        "price_min": price_min,
        "price_max": price_max,
        "images_json": images,
        "variants_json": variants,
        "tags_json": normalize_tags(payload.get("tags")),
        "description_html": description_html or None,
        "description_text": description_text or None,
        "search_terms_json": [term for term in search_terms if str(term or "").strip()],
        "source_payload_json": payload,
        "source_tier": "internal_official",
        "is_active": True,
    }
    return profile


def build_profile_chunks(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    base_meta = {
        "source_group": "official_site",
        "source_tier": "internal_official",
        "source_kind": "product_json",
        "official_url": profile.get("official_url"),
        "product_handle": profile.get("product_handle"),
        "brand": profile.get("brand"),
        "availability": profile.get("availability"),
    }
    chunks: List[Dict[str, Any]] = []

    identity_lines = [
        f"Official product: {profile.get('product_title')}",
        f"Brand: {profile.get('brand')}" if profile.get("brand") else "",
        f"Handle: {profile.get('product_handle')}",
        f"Official URL: {profile.get('official_url')}",
        f"Product Type: {profile.get('product_type')}" if profile.get("product_type") else "",
    ]
    identity_text = "\n".join(line for line in identity_lines if line)
    chunks.append({"name": "identity", "text": identity_text, "meta": dict(base_meta, source_kind="product_json", structured_group="identity")})

    commercial_bits = []
    if profile.get("price_min") is not None:
        if profile.get("price_min") == profile.get("price_max"):
            commercial_bits.append(f"Price: {profile.get('price_min')}")
        else:
            commercial_bits.append(f"Price Range: {profile.get('price_min')} - {profile.get('price_max')}")
    if profile.get("availability") is not None:
        commercial_bits.append(f"Availability: {'available' if profile.get('availability') else 'unavailable'}")
    if profile.get("variants_json"):
        commercial_bits.append(f"Variant Count: {len(profile.get('variants_json') or [])}")
    if profile.get("tags_json"):
        commercial_bits.append("Tags: " + ", ".join(profile.get("tags_json") or []))
    if profile.get("images_json"):
        commercial_bits.append("Images: " + ", ".join((profile.get("images_json") or [])[:3]))
    if commercial_bits:
        chunks.append(
            {
                "name": "commercial",
                "text": "\n".join([identity_text] + commercial_bits),
                "meta": dict(base_meta, source_kind="product_json", structured_group="commercial"),
            }
        )

    description = str(profile.get("description_text") or "").strip()
    if description:
        chunks.append(
            {
                "name": "description",
                "text": "\n".join([identity_text, f"Official Description: {description}"]),
                "meta": dict(base_meta, source_kind="product_html", structured_group="description"),
            }
        )
    return chunks


@dataclass
class OfficialSiteSeed:
    seed_type: str
    value: str
    query: Optional[str] = None


def normalize_seed(base_url: str, raw: str) -> OfficialSiteSeed:
    text = str(raw or "").strip()
    if not text:
        return OfficialSiteSeed("collection", "/collections/custom-collection")
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        if "/products/" in parsed.path:
            return OfficialSiteSeed("product", normalize_product_url(base_url, text))
        if "/search" in parsed.path:
            return OfficialSiteSeed("search", text, query=parse_q_param(text))
        return OfficialSiteSeed("collection", text)
    if text.startswith("/products/") or "/products/" in text:
        return OfficialSiteSeed("product", normalize_product_url(base_url, text))
    if text.startswith("/search"):
        return OfficialSiteSeed("search", urljoin(base_url, text), query=parse_q_param(text))
    if text.startswith("/collections/"):
        return OfficialSiteSeed("collection", urljoin(base_url, text))
    return OfficialSiteSeed("search", f"{base_url.rstrip('/')}/search?q={quote_plus(text)}", query=text)


def parse_q_param(url_or_path: str) -> str:
    match = re.search(r"[?&]q=([^&]+)", url_or_path)
    if not match:
        return ""
    return unescape(match.group(1).replace("+", " ")).strip()
