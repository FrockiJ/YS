# coding: utf-8
from typing import Dict, Any
import re

ALCOHOL_KEYWORDS = [
    "wine",
    "burgundy",
    "pinot",
    "chardonnay",
    "merlot",
    "cabernet",
    "riesling",
    "sauvignon",
    "beer",
    "ipa",
    "lager",
    "stout",
    "porter",
    "ale",
    "weissbier",
    "hefeweizen",
    "whisky",
    "whiskey",
    "bourbon",
    "scotch",
    "rye",
    "rum",
    "brandy",
    "cognac",
    "gin",
    "vodka",
    "tequila",
    "mezcal",
    "sake",
    "nihonshu",
    "soju",
    "cocktail",
    "liqueur",
    "vermouth",
    "amaro",
    # Chinese keywords
    "\u9152",
    "\u9152\u6b3e",
    "\u8461\u8404\u9152",
    "\u7d05\u9152",
    "\u767d\u9152",
    "\u9999\u6ab3",
    "\u5a01\u58eb\u5fcc",
    "\u5564\u9152",
    "\u6e05\u9152",
    "\u8abf\u9152",
]

PRODUCER_TERMS = [
    "\u9152\u838a",
    "\u9152\u5ee0",
    "\u7522\u5340",
    "\u9152\u57df",
    "winery",
    "producer",
    "ys",
    "estate",
]
STOCK_TERMS = [
    "\u5eab\u5b58",
    "\u5b58\u8ca8",
    "\u73fe\u8ca8",
    "\u6709\u8ca8",
    "\u7f3a\u8ca8",
    "stock",
    "inventory",
    "quantity",
]
QUOTE_TERMS = [
    "\u5831\u50f9",
    "\u5831\u50f9\u55ae",
    "\u5831\u50f9\u6e05\u55ae",
    "\u5831\u50f9\u8868",
    "quote",
    "quotation",
    "quote list",
    "price list",
    "list",
]
CRITIC_TERMS = [
    "wine advocate",
    "jasper morris",
    "burghound",
    "vinous",
    "decanter",
    "score",
    "scores",
    "rating",
    "ratings",
    "points",
    "\u9152\u8a55",
    "\u8a55\u5206",
    "\u5206\u6578",
    "\u4f86\u6e90",
    "\u5f15\u7528",
]
RECOMMEND_TERMS = [
    "\u63a8\u85a6",
    "\u5efa\u8b70",
    "\u642d\u914d",
    "pair",
    "\u9078\u64c7",
    "\u9069\u5408",
    "\u60f3\u8981",
    "\u627e",
]


def detect_intent(text: str, domain: str = "alcohol") -> Dict[str, Any]:
    t = (text or "").lower()
    slots: Dict[str, Any] = {}
    matched = any(k in t for k in ALCOHOL_KEYWORDS)
    intent = "FREE_CHAT"

    if any(k in t for k in CRITIC_TERMS):
        intent = "ASK_ALCOHOL_INFO" if domain == "alcohol" else "FREE_CHAT"
    elif any(k in t for k in QUOTE_TERMS):
        intent = "QUOTE_LIST"
    elif domain == "alcohol" and matched:
        intent = "ASK_ALCOHOL_INFO"
        if any(k in t for k in PRODUCER_TERMS):
            intent = "ASK_PRODUCER_INFO"
        elif any(k in t for k in RECOMMEND_TERMS):
            intent = "ASK_RECOMMENDATION"

    vintage_match = re.search(r"(19\d{2}|20\d{2})", t)
    if vintage_match:
        slots["vintage"] = vintage_match.group(1)
    count_match = re.search(r"(\d+)\s*(?:\u74f6|\u652f|\u7bb1|\u7d44|cases?|case|packs?|bottles?|bottle)", t)
    if count_match:
        slots["count"] = count_match.group(1)
    return {"name": intent, "slots": slots}
