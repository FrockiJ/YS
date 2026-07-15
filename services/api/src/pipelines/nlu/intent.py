from __future__ import annotations

import re
from typing import Any, Dict


_QUOTE_TERMS = ("報價", "報價單", "價格清單", "quote", "quotation", "price list")
_PRODUCT_TERMS = (
    "建議商品",
    "找商品",
    "購買",
    "庫存",
    "價格",
    "現貨",
    "recommend product",
    "suggest product",
    "find product",
    "buy",
    "stock",
    "inventory",
    "price",
)


def detect_intent(text: str, domain: str = "outdoor") -> Dict[str, Any]:
    del domain
    value = str(text or "").lower()
    slots: Dict[str, Any] = {}
    if any(term in value for term in _QUOTE_TERMS):
        intent = "QUOTE_LIST"
    elif any(term in value for term in _PRODUCT_TERMS):
        intent = "PRODUCT_RECOMMENDATION"
    else:
        intent = "FREE_CHAT"
    count_match = re.search(r"(\d+)\s*(?:個|件|組|箱|pcs?|items?|packs?)", value)
    if count_match:
        slots["quantity"] = int(count_match.group(1))
    return {"name": intent, "slots": slots}
