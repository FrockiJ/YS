import logging
import re
from typing import Optional
from urllib.parse import quote, urljoin

import httpx
import json

logger = logging.getLogger("ys_ai.services.api.utils.webphoto")

BASE_URL = "https://ys.local"
SEARCH_URL = f"{BASE_URL}/search?q="

_photo_cache: dict[str, Optional[str]] = {}


def _normalize_photo_src(src: str) -> Optional[str]:
    if not src:
        return None
    src = src.strip()
    if src.startswith("//"):
        return f"https:{src}"
    if src.startswith("/"):
        return urljoin(BASE_URL, src)
    return src


async def _extract_product_photo(client: httpx.AsyncClient, product_url: str) -> Optional[str]:
    try:
        response = await client.get(product_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.debug("Webphoto unable to load %s: %s", product_url, exc)
        return None
    html = response.text

    # Prefer Shopify JSON payload that lists images; fallback to legacy ProductPhotoImg tag
    json_match = re.search(
        r'<script[^>]+id="ProductJson-product-template"[^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    if json_match:
        try:
            payload = json.loads(json_match.group(1).strip())
            images = payload.get("images") or []
            featured_image = payload.get("featured_image")
            if not images and featured_image:
                images = [featured_image]
            if isinstance(images, list) and images:
                image_src = images[0]
                if isinstance(image_src, dict):
                    image_src = image_src.get("src")
                photo = _normalize_photo_src(image_src or "")
                if photo:
                    return photo
        except json.JSONDecodeError as exc:
            logger.debug("Webphoto failed to parse ProductJson for %s: %s", product_url, exc)

    match = re.search(r'id="ProductPhotoImg"[^>]+src="([^"]+)"', html)
    if match:
        return _normalize_photo_src(match.group(1))

    logger.debug("Webphoto did not find ProductPhotoImg or ProductJson in %s", product_url)
    return None


async def lookup_product_photo(code: str, barcode: Optional[str] = None) -> Optional[str]:
    key = (code or "").strip() or (barcode or "").strip()
    if not key:
        return None
    if key in _photo_cache:
        return _photo_cache[key]
    photo_url: Optional[str] = None
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        search_terms = [code or key]
        if barcode:
            search_terms.append(barcode)
        for term in search_terms:
            if not term:
                continue
            try:
                search_resp = await client.get(f"{SEARCH_URL}{quote(term)}")
                search_resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.debug("Webphoto search (%s) failed: %s", term, exc)
                continue
            match = re.search(r'href="(/products/[^"]+)"', search_resp.text)
            if not match:
                continue
            product_url = urljoin(BASE_URL, match.group(1))
            photo_url = await _extract_product_photo(client, product_url)
            if photo_url:
                logger.debug("Webphoto resolved %s -> %s", term, photo_url)
                break
    _photo_cache[key] = photo_url
    if not photo_url:
        logger.debug("Webphoto could not resolve image for %s", key)
    return photo_url
