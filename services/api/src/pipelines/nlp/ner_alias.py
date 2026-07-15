from __future__ import annotations

from typing import Any, Dict, List

from ..extract.schema_map import map_to_knowledge_fields


def _variants(value: str) -> List[str]:
    return list(dict.fromkeys((value, value.casefold(), value.replace("-", " ").casefold())))


def extract_entities_and_alias(text: str):
    fields = map_to_knowledge_fields(text)
    aliases: List[Dict[str, Any]] = []
    entities: List[Dict[str, Any]] = []
    alias_keys = {
        "brand": "brand",
        "product_name": "product_name",
        "category": "category",
        "location": "location",
        "activity": "activity",
        "specification": "specification",
        "skus": "sku",
    }
    for key, raw in fields.items():
        values = raw if isinstance(raw, list) else [raw]
        for item in values:
            value = str(item or "").strip()
            if not value:
                continue
            entities.append({"type": key, "value": value, "normalized": value.casefold(), "confidence": 0.8, "meta": {}})
            alias_type = alias_keys.get(key)
            if alias_type:
                aliases.extend(
                    {
                        "canonical": value,
                        "variant": variant,
                        "type": alias_type,
                        "lang": "auto",
                        "source": "heuristic",
                        "confidence": 0.8,
                    }
                    for variant in _variants(value)
                )
    return entities, aliases, fields
