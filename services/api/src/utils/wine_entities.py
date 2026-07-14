from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List


_PUNCT_RE = re.compile(r"[^a-z0-9]+")
_SPACE_RE = re.compile(r"\s+")

_TOKEN_ALIASES = {
    "pack": "backpack",
    "rucksack": "backpack",
    "trekking": "hiking",
    "trek": "hiking",
    "raincoat": "rain jacket",
    "shell": "rain jacket",
    "pole": "rod",
    "reels": "reel",
    "lure": "tackle",
    "lures": "tackle",
    "stove": "camping stove",
    "lamp": "headlamp",
    "lantern": "camp lantern",
}

_PHRASE_ALIASES = {
    "rain coat": "rain jacket",
    "waterproof shell": "rain jacket",
    "hardshell jacket": "rain jacket",
    "fishing pole": "fishing rod",
    "spinning pole": "fishing rod",
    "spinning reel": "fishing reel",
    "bait casting reel": "baitcasting reel",
    "trekking pole": "hiking pole",
    "walking pole": "hiking pole",
    "camp stove": "camping stove",
    "portable stove": "camping stove",
    "sleep bag": "sleeping bag",
    "day pack": "daypack",
    "hydration pack": "hydration backpack",
}

_KNOWN_ENTITY_HIERARCHY = {
    "rain jacket": {
        "entity_type": "category",
        "canonical": "Rain Jacket",
        "category": "Apparel",
        "department": "Hiking",
    },
    "fishing rod": {
        "entity_type": "category",
        "canonical": "Fishing Rod",
        "category": "Fishing Tackle",
        "department": "Fishing",
    },
    "fishing reel": {
        "entity_type": "category",
        "canonical": "Fishing Reel",
        "category": "Fishing Tackle",
        "department": "Fishing",
    },
    "hiking pole": {
        "entity_type": "category",
        "canonical": "Hiking Pole",
        "category": "Trail Gear",
        "department": "Hiking",
    },
    "camping stove": {
        "entity_type": "category",
        "canonical": "Camping Stove",
        "category": "Camp Kitchen",
        "department": "Camping",
    },
    "sleeping bag": {
        "entity_type": "category",
        "canonical": "Sleeping Bag",
        "category": "Sleep System",
        "department": "Camping",
    },
    "backpack": {
        "entity_type": "category",
        "canonical": "Backpack",
        "category": "Packs",
        "department": "Hiking",
    },
}


def normalize_entity_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = _PUNCT_RE.sub(" ", text)
    tokens = [_TOKEN_ALIASES.get(token, token) for token in text.split()]
    normalized = _SPACE_RE.sub(" ", " ".join(tokens)).strip()
    return _PHRASE_ALIASES.get(normalized, normalized)


def canonicalize_wine_entity(value: Any) -> Dict[str, Any]:
    """Compatibility name for the legacy inventory entity normalizer."""
    normalized = normalize_entity_text(value)
    if not normalized:
        return {"raw": value, "normalized": "", "canonical": ""}
    canonical_key = _PHRASE_ALIASES.get(normalized, normalized)
    known = dict(_KNOWN_ENTITY_HIERARCHY.get(canonical_key, {}))
    if known:
        known.setdefault("normalized", canonical_key)
        known.setdefault("raw", value)
        return known
    return {
        "raw": value,
        "normalized": canonical_key,
        "canonical": canonical_key.title(),
        "entity_type": "unknown",
    }


def expand_wine_aliases(value: Any) -> List[str]:
    """Compatibility name for inventory product alias expansion."""
    normalized = normalize_entity_text(value)
    if not normalized:
        return []
    aliases = {normalized}
    canonical = _PHRASE_ALIASES.get(normalized, normalized)
    aliases.add(canonical)
    for phrase, target in _PHRASE_ALIASES.items():
        if target == canonical:
            aliases.add(phrase)
    return sorted(aliases)


def enrich_entity_hints(hints: Dict[str, Any] | None) -> Dict[str, Any]:
    enriched = dict(hints or {})
    aliases: Dict[str, List[str]] = {}
    canonical: Dict[str, Dict[str, Any]] = {}
    for key in (
        "brand",
        "supplier",
        "category",
        "series",
        "model",
        "product_name",
        "item_name",
        "producer",
        "region",
        "appellation",
        "vineyard",
        "wine_name",
    ):
        value = enriched.get(key)
        values: Iterable[Any] = value if isinstance(value, list) else [value]
        collected: List[str] = []
        for item in values:
            if item in (None, ""):
                continue
            entity = canonicalize_wine_entity(item)
            if entity.get("normalized"):
                canonical.setdefault(key, entity)
                collected.extend(expand_wine_aliases(item))
        if collected:
            aliases[key] = sorted(set(collected))
    if aliases:
        enriched.setdefault("normalized_aliases", aliases)
    if canonical:
        enriched.setdefault("canonical_entities", canonical)
    return enriched
