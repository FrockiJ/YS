from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from ...utils.cerp_export_lookup import find_best_matching_product


FILTER_FIELD_MAP = {
    "brand": "brand",
    "product": "product_name",
    "category": "category",
    "specification": "specification",
    "location": "location",
    "activity": "activity",
}


def _tokens(query: str) -> List[str]:
    return [token for token in re.split(r"[\s,;\\/、，；。！？?!]+", str(query or "").strip()) if token]


def _push_filter(filters: Dict[str, Any], key: str, value: str) -> None:
    normalized = str(value or "").strip()
    if not normalized:
        return
    current = filters.get(key)
    if current is None:
        filters[key] = normalized
    elif isinstance(current, list):
        if normalized not in current:
            current.append(normalized)
    elif current != normalized:
        filters[key] = [current, normalized]


async def expand_aliases(conn, query: str) -> Tuple[List[str], Dict[str, Any]]:
    rewrites = {str(query or "").strip()}
    filters: Dict[str, Any] = {}
    for token in _tokens(query):
        rows = []
        if conn:
            rows = await conn.fetch(
                "SELECT canonical, variant, type FROM alias WHERE variant ILIKE $1 LIMIT 10",
                f"%{token}%",
            )
        for row in rows or []:
            canonical = str(row.get("canonical") or "").strip()
            if not canonical:
                continue
            rewrites.add(str(query).replace(token, canonical))
            field = FILTER_FIELD_MAP.get(str(row.get("type") or "").strip().lower())
            if field:
                _push_filter(filters, field, canonical)
        product = find_best_matching_product(token)
        if not product:
            continue
        for field, raw_key in (
            ("product_name", "invn005"),
            ("brand", "invn006"),
            ("sku", "invn002"),
            ("barcode", "invn008"),
            ("category", "invn030"),
            ("specification", "invn051"),
        ):
            value = str(product.get(raw_key) or "").strip()
            if value:
                _push_filter(filters, field, value)
        name = str(product.get("invn005") or "").strip()
        if name:
            rewrites.add(str(query).replace(token, name))
    return [item for item in rewrites if item][:5], filters
