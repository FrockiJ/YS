from __future__ import annotations

from typing import Any, Dict, Optional

from ...schemas.ai import Hit
from .citation_validator import normalize_source_metadata


SOURCE_PRIORITY_WEIGHT_START = 0.35
SOURCE_PRIORITY_WEIGHT_STEP = 0.04
DOCUMENT_TYPE_MATCH_WEIGHT = 0.30
ENTITY_EXACT_MATCH_WEIGHT = 0.25
CONTEXT_RELEVANCE_WEIGHT = 0.20
CUSTOMER_PROFILE_WEIGHT = 0.15
AUTHORITATIVE_SOURCE_TIERS = {"internal_official", "Tier 1", "Tier 2", "external_evidence"}


def source_priority_boost(
    hit: Hit,
    *,
    priority: list[str],
    required_doc_type_match: bool,
) -> tuple[float, Dict[str, Any]]:
    meta = normalize_source_metadata(hit.meta or {})
    source_tier = str(hit.source_tier or meta.get("source_tier") or "").strip()
    source_type = str(hit.source_type or meta.get("source_type") or "").strip()
    search_text = _hit_search_text(hit, meta)
    boost = 0.0
    matched: list[str] = []
    for idx, item in enumerate(priority or []):
        normalized = str(item or "").strip().lower()
        if not normalized:
            continue
        weight = max(0.05, SOURCE_PRIORITY_WEIGHT_START - idx * SOURCE_PRIORITY_WEIGHT_STEP)
        if normalized == "cerp" and (source_type.lower() == "cerp" or "cerp" in search_text):
            boost += weight
            matched.append(normalized)
        elif normalized == "external_authoritative" and source_tier in AUTHORITATIVE_SOURCE_TIERS:
            boost += weight
            matched.append(normalized)
        elif normalized in {source_tier.lower(), source_type.lower()}:
            boost += weight
            matched.append(normalized)
        elif normalized and normalized in search_text:
            boost += weight
            matched.append(normalized)
    if required_doc_type_match:
        boost += DOCUMENT_TYPE_MATCH_WEIGHT
        matched.append("required_doc_type")
    return boost, {"matched_priorities": matched, "source_tier": source_tier, "source_type": source_type}


def score_breakdown(
    hit: Hit,
    *,
    base_score: float,
    source_priority_boost_value: float,
    entity_exact_match: bool,
    document_type_match: bool,
    context_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context_state = context_state or {}
    context_relevance = CONTEXT_RELEVANCE_WEIGHT if _matches_context(hit, context_state) else 0.0
    customer_profile = CUSTOMER_PROFILE_WEIGHT if _customer_profile_relevant(hit, context_state) else 0.0
    entity_weight = ENTITY_EXACT_MATCH_WEIGHT if entity_exact_match else 0.0
    total = base_score + source_priority_boost_value + entity_weight + context_relevance + customer_profile
    return {
        "base_score": round(base_score, 4),
        "source_priority": round(source_priority_boost_value, 4),
        "entity_exact_match": round(entity_weight, 4),
        "document_type_match": bool(document_type_match),
        "context_relevance": round(context_relevance, 4),
        "customer_profile_relevance": round(customer_profile, 4),
        "total_score": round(total, 4),
    }


def _matches_context(hit: Hit, context_state: Dict[str, Any]) -> bool:
    protected = context_state.get("protected_entities") if isinstance(context_state.get("protected_entities"), dict) else {}
    active = context_state.get("active_topic") if isinstance(context_state.get("active_topic"), dict) else {}
    terms = [str(value).strip().lower() for source in (protected, active) for value in source.values() if str(value or "").strip()]
    if not terms:
        return False
    haystack = _hit_search_text(hit, normalize_source_metadata(hit.meta or {}))
    return any(term.lower() in haystack for term in terms)


def _customer_profile_relevant(hit: Hit, context_state: Dict[str, Any]) -> bool:
    if not context_state.get("project_profile_used"):
        return False
    meta = normalize_source_metadata(hit.meta or {})
    family = str(meta.get("source_family") or "").strip()
    tier = str(hit.source_tier or meta.get("source_tier") or "").strip()
    return family == "customer_facts_pack" or tier in {"internal_approved", "internal_official"}


def _hit_search_text(hit: Hit, meta: Dict[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in (
            hit.text,
            hit.summary,
            " ".join(hit.keywords or []),
            hit.source_type,
            hit.source_tier,
            " ".join(str(item or "") for item in meta.values()),
        )
    ).lower()
