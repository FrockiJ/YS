from typing import Dict, Any, List, Tuple
import re

from src.utils.cerp_export_lookup import (
    find_best_matching_product,
    find_best_matching_producer,
)

FILTER_FIELD_MAP = {
    "region": "region",
    "village": "village",
    "vineyard": "vineyard",
    "producer": "producer",
    "classification": "classification",
    "style": "style",
    "grape": "grape_varieties",
}


def _tokens(q: str) -> List[str]:
    if not q:
        return []
    # Split by whitespace and common Chinese/English punctuation so tokens like
    # "Lafarge Vial、甜味" can still be detected individually.
    return [t for t in re.split(r"[\s,;\\/、，。；；：!！?？]+", q.strip()) if t]


def _push_filter(filters: Dict[str, Any], key: str, value: str) -> None:
    if not value:
        return
    if key not in filters:
        filters[key] = value
        return
    existing = filters[key]
    if isinstance(existing, list):
        if value not in existing:
            existing.append(value)
    else:
        if existing != value:
            filters[key] = [existing, value]


async def expand_aliases(conn, query: str) -> Tuple[List[str], Dict[str, str]]:
    toks = _tokens(query)
    rewrites = set([query])
    filters: Dict[str, str] = {}
    if not toks:
        return list(rewrites), filters
    for t in toks:
        rows = []
        if conn:
            rows = await conn.fetch(
                "SELECT canonical, variant, type FROM alias WHERE variant ILIKE $1 LIMIT 10",
                f"%{t}%",
            )
        for r in rows or []:
            rewrites.add(query.replace(t, r["canonical"]))
            tp = (r.get("type") or "").lower()
            field = FILTER_FIELD_MAP.get(tp)
            if field:
                _push_filter(filters, field, r["canonical"])

        # Fallback to CERP export lookup when alias table misses the token
        producer = find_best_matching_producer(t)
        if producer:
            rewrites.add(query.replace(t, producer))
            _push_filter(filters, "invn006", producer)
        product_row = find_best_matching_product(t)
        if product_row:
            name = product_row.get("invn005")
            code = product_row.get("invn002")
            barcode = product_row.get("invn008")
            producer_name = product_row.get("invn006")
            if name:
                rewrites.add(query.replace(t, name))
                _push_filter(filters, "invn005", name)
            if producer_name:
                _push_filter(filters, "invn006", producer_name)
            if code:
                _push_filter(filters, "invn002", code)
            if barcode:
                _push_filter(filters, "invn008", barcode)
    return list(rewrites)[:5], filters
