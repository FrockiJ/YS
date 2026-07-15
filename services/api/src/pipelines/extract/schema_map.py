from __future__ import annotations

import re
from typing import Any, Dict, List


_PRICE_RE = re.compile(r"(?:NT\$|TWD|USD|\$)\s?\d+(?:[.,]\d{1,2})?", re.IGNORECASE)
_SKU_RE = re.compile(r"\b[A-Z]{2,8}-?[A-Z0-9]{3,16}\b", re.IGNORECASE)
_FEATURE_TERMS = (
    "waterproof",
    "breathable",
    "lightweight",
    "insulated",
    "rechargeable",
    "防水",
    "透氣",
    "輕量",
    "保暖",
    "充電",
)


def _dedupe(values: List[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


def map_to_knowledge_fields(text: str) -> Dict[str, Any]:
    """Extract only domain-neutral fields that are safe to persist in RAG metadata."""
    value = str(text or "").strip()
    lowered = value.casefold()
    fields: Dict[str, Any] = {}

    price = _PRICE_RE.search(value)
    if price:
        fields["price"] = price.group(0)

    skus = _dedupe(match.group(0).upper() for match in _SKU_RE.finditer(value))
    if skus:
        fields["skus"] = skus

    features = [term for term in _FEATURE_TERMS if term.casefold() in lowered]
    if features:
        fields["features"] = _dedupe(features)

    return fields
