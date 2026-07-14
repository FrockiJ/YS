from __future__ import annotations

import re
from typing import Optional


SKU_RE = re.compile(r"\b[A-Z]{1,8}[-_]?\d{3,}[A-Z0-9_-]*\b", re.IGNORECASE)

ZH_LISTING_TOKENS = (
    "\u5217\u51fa",  # list
    "\u986f\u793a",  # show
    "\u67e5\u770b",  # view
    "\u67e5\u8a62",  # query
    "\u641c\u5c0b",  # search
    "\u641c\u7d22",  # search
    "\u6709\u54ea\u4e9b",  # what are available
    "\u6709\u54ea",  # what available
    "\u6240\u6709",  # all
    "\u5168\u90e8",  # all
)
ZH_STOCK_TOKENS = (
    "\u5eab\u5b58",  # inventory
    "\u73fe\u8ca8",  # in stock
    "\u6709\u8ca8",  # available
    "\u5b58\u8ca8",  # inventory
    "\u5b58\u91cf",  # stock quantity
)
ZH_PRODUCT_TOKENS = (
    "\u5546\u54c1",  # goods
    "\u7522\u54c1",  # product
    "\u54c1\u9805",  # item
)

EN_LISTING_RE = re.compile(r"\b(?:show|list|browse|display|top|all)\b", re.IGNORECASE)
EN_STOCK_RE = re.compile(r"\b(?:inventory|stock|in[\s-]?stock|available|availability)\b", re.IGNORECASE)
EN_PRODUCT_RE = re.compile(r"\b(?:product|products|items|sku)\b", re.IGNORECASE)
EN_EXACT_OR_FILTERED_RE = re.compile(
    r"\b(?:do\s+we|are\s+we|currently\s+carry|carry|if\s+yes|if\s+no|"
    r"under|below|less\s+than|over|at\s+least|>=|<=|sorted\s+by|"
    r"bottles?|nt\$|\$|price|retail|vip|champagne|burgundy|bourgogne|wine|wines?)\b|"
    r"\b(?:19|20)\d{2}\b",
    re.IGNORECASE,
)


def is_generic_inventory_listing_query(text: Optional[str]) -> bool:
    """Return True for broad inventory-list prompts, not exact SKU/product lookups."""
    raw = str(text or "").strip()
    if not raw:
        return False
    if SKU_RE.search(raw):
        return False

    lowered = raw.casefold()
    if EN_EXACT_OR_FILTERED_RE.search(lowered):
        return False
    has_zh_listing = any(token in raw for token in ZH_LISTING_TOKENS)
    has_zh_stock = any(token in raw for token in ZH_STOCK_TOKENS)
    has_zh_product = any(token in raw for token in ZH_PRODUCT_TOKENS)
    has_en_listing = bool(EN_LISTING_RE.search(lowered))
    has_en_stock = bool(EN_STOCK_RE.search(lowered))
    has_en_product = bool(EN_PRODUCT_RE.search(lowered))

    if (has_zh_listing or has_en_listing) and (has_zh_stock or has_en_stock):
        return True
    if (has_zh_stock or has_en_stock) and (has_zh_product or has_en_product):
        return True
    return False
