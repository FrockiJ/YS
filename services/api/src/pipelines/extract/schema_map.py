from __future__ import annotations

import re
from typing import Dict, Any, List, Set

STYLE_KEYWORDS = {
    "full-bodied": ["full-bodied", "rich", "opulent"],
    "medium-bodied": ["medium-bodied", "balanced"],
    "light-bodied": ["light-bodied", "fresh", "delicate"],
    "sparkling": ["sparkling", "mousseux", "effervescent"],
    "rosé": ["rosé", "rose"],
}

NAME_STOP_WORDS = {
    "wine",
    "wines",
    "the",
    "les",
    "de",
    "du",
    "la",
    "le",
    "of",
    "and",
    "vin",
    "with",
    "champagne",
    "appellation",
}

NAME_PATTERN = re.compile(
    r"\b([A-ZÁÀÂÄÁÇÈÉÊËÌÍÎÏÑÓÒÔÖŒÙÚÛÜŸŽ][A-Za-zÀ-ÿ'-]+(?:[\s-][A-ZÁÀÂÄÁÇÈÉÊËÌÍÎÏÑÓÒÔÖŒÙÚÛÜŸŽ][A-Za-zÀ-ÿ'-]+){1,3})\b"
)


def _match_style(lower: str) -> str | None:
    for style, keywords in STYLE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return style
    return None


def _extract_price(text: str) -> str | None:
    price_match = re.search(r"(?:EUR|USD|\$|NT\$|£)\s?\d+(?:[.,]\d{2})?", text)
    return price_match.group(0) if price_match else None


def _extract_vintage(text: str) -> str | None:
    vintage = re.search(r"(19|20)\d{2}", text)
    return vintage.group(0) if vintage else None


def _extract_producers(text: str) -> List[str]:
    producers: Set[str] = set()
    pattern = re.compile(
        r"(?:YS|Ch(?:ateau|\u00e2teau)|Maison|Clos)\s+[A-Z][A-Za-z\u00c0-\u017f'\- ]{2,60}"
    )
    for match in pattern.findall(text):
        producers.add(match.strip())

    for match in NAME_PATTERN.findall(text):
        candidate = match.strip()
        words = re.split(r"[\s-]+", candidate)
        if len(words) > 4:
            continue
        if any(word.lower() in NAME_STOP_WORDS for word in words):
            continue
        producers.add(candidate)

    return sorted(producers)


def _extract_grapes(text: str) -> List[str]:
    grapes = set()
    grape_keywords = [
        "pinot noir",
        "chardonnay",
        "gamay",
        "syrah",
        "grenache",
        "merlot",
        "cabernet sauvignon",
    ]
    lower = text.lower()
    for grape in grape_keywords:
        if grape in lower:
            grapes.add(grape.title())
    return sorted(grapes)


def map_to_knowledge_fields(text: str) -> Dict[str, Any]:
    lower = (text or "").lower()
    out: Dict[str, Any] = {}
    if "vosne" in lower:
        out["village"] = "Vosne-Romanée"
        out["region"] = "Côte de Nuits"
    if "suchots" in lower:
        out["vineyard"] = "Les Suchots"
    if "grand cru" in lower:
        out["classification"] = "Grand Cru"
    if "premier cru" in lower:
        out["classification"] = "Premier Cru"

    style = _match_style(lower)
    if style:
        out["style"] = style

    price = _extract_price(text)
    if price:
        out["price"] = price

    vintage = _extract_vintage(text)
    if vintage:
        out["vintage"] = vintage

    producers = _extract_producers(text)
    if producers:
        out["producers"] = producers
        out["producer"] = producers[0]

    grapes = _extract_grapes(text)
    if grapes:
        out["grape_varieties"] = grapes

    tasting_notes = []
    note_keywords = ["spice", "minerality", "berry", "citrus", "floral", "oak"]
    for kw in note_keywords:
        if kw in lower:
            tasting_notes.append(kw)
    if tasting_notes:
        out["tasting_notes"] = tasting_notes
    return out
