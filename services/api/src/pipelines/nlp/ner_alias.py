from __future__ import annotations

from typing import Any, Dict, List

from ..extract.schema_map import map_to_knowledge_fields


def _normalize_value(value: Any) -> str:
    return str(value).strip()


def _alias_variants(value: str) -> List[str]:
    variants = {value}
    low = value.lower()
    variants.add(low)
    variants.add(value.replace("-", " ").lower())
    if " " in value:
        variants.add(value.replace(" ", ""))
    return [v for v in variants if v]


def extract_entities_and_alias(text: str):
    fields = map_to_knowledge_fields(text)
    aliases: List[Dict[str, Any]] = []
    entities: List[Dict[str, Any]] = []

    def _add_entity(entity_type: str, value: str, confidence: float = 0.8):
        entities.append({
            "type": entity_type,
            "value": value,
            "normalized": value.lower(),
            "confidence": confidence,
            "meta": {}
        })

    alias_keys = {
        "region": "region",
        "village": "village",
        "vineyard": "vineyard",
        "producers": "producer",
        "producer": "producer",
        "classification": "classification",
        "style": "style",
        "grape_varieties": "grape",
    }

    for key, raw in fields.items():
        if not raw:
            continue
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            base = _normalize_value(value)
            if not base:
                continue
            _add_entity(key, base)
            alias_type = alias_keys.get(key)
            if alias_type:
                for variant in _alias_variants(base):
                    aliases.append({
                        "canonical": base,
                        "variant": variant,
                        "type": alias_type,
                        "lang": "auto",
                        "source": "heuristic",
                        "confidence": 0.8,
                    })

    return entities, aliases, fields
