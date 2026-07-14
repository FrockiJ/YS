from __future__ import annotations

from typing import Any, Dict, Optional

from .behavior_profiles import get_behavior_profile
from .evidence_contracts import evidence_type_for_prompt_category


CERP_INTENTS = {"QUOTE_LIST"}
PERMISSION_BOUNDARY_CATEGORIES = {"permission_boundary"}
CUSTOMER_FACT_CATEGORIES = {"brand_profile", "general_chat", "producer_ranking"}


def build_answer_route_policy(
    *,
    prompt_category: Optional[str],
    intent_name: Optional[str],
    entity_hints: Optional[Dict[str, Any]] = None,
    context_state: Optional[Dict[str, Any]] = None,
    behavior_profile: Optional[Dict[str, Any]] = None,
    source_policy: Optional[str] = None,
    needs_authoritative_sources: bool = False,
) -> Dict[str, Any]:
    """Return the central answer routing contract used by retrieval and generation.

    This does not replace NLU. It turns the current NLU/context decision into a
    stable route/evidence contract that can be traced and validated.
    """

    category = str(prompt_category or "").strip() or "general_chat"
    intent = str(intent_name or "").strip() or "FREE_CHAT"
    profile = dict(behavior_profile or get_behavior_profile(category))
    resolved_source_policy = (
        str(source_policy or "").strip()
        or str(profile.get("source_policy") or "").strip()
        or ("authoritative_external_required" if needs_authoritative_sources else "internal_preferred")
    )
    if intent in CERP_INTENTS and category == "general_chat":
        category = "quote_recommendation"
    evidence_type = evidence_type_for_prompt_category(category)
    if category in PERMISSION_BOUNDARY_CATEGORIES:
        evidence_type = "permission_boundary"

    allowed_sources = _allowed_sources_for(category, evidence_type)
    required_sources = _required_sources_for(category, evidence_type)
    context_state = context_state or {}
    customer_context_used = bool(
        context_state.get("project_profile_used")
        or context_state.get("related_conversation_count")
        or context_state.get("conversation_memory_used")
    )
    if customer_context_used and category in CUSTOMER_FACT_CATEGORIES:
        allowed_sources.append("customer_facts_pack")

    return {
        "route": category,
        "intent": intent,
        "evidence_type": evidence_type,
        "source_policy": resolved_source_policy,
        "citation_rule": profile.get("citation_rule"),
        "retrieval_priority": list(profile.get("retrieval_priority") or []),
        "required_doc_types": list(profile.get("required_doc_types") or []),
        "blocked_doc_types": list(profile.get("blocked_doc_types") or []),
        "required_sources": required_sources,
        "allowed_sources": _dedupe(allowed_sources),
        "permission_boundary": evidence_type == "permission_boundary",
        "context": {
            "followup_type": context_state.get("followup_type"),
            "context_used": bool(context_state.get("resolved")),
            "protected_entities": context_state.get("protected_entities") or {},
            "customer_context_used": customer_context_used,
        },
        "entity_hints_present": sorted(
            key for key, value in (entity_hints or {}).items() if value not in (None, "", [], {})
        ),
    }


def _allowed_sources_for(category: str, evidence_type: str) -> list[str]:
    if evidence_type == "licensed_review":
        return ["licensed_review_dataset"]
    if evidence_type == "book_ocr":
        return ["ocr_book_corpus", "book"]
    if evidence_type == "cerp_snapshot":
        return ["cerp_snapshot", "CERP"]
    if evidence_type == "cerp_business_snapshot":
        return ["cerp_snapshot", "CERP"]
    if evidence_type == "source_hierarchy":
        return ["cerp_snapshot", "internal_official", "licensed_review_dataset", "ocr_book_corpus"]
    if evidence_type == "permission_boundary":
        return []
    if category in CUSTOMER_FACT_CATEGORIES:
        return ["internal_approved", "internal_official", "customer_facts_pack"]
    return ["internal_approved", "internal_official", "internal", "external_authoritative"]


def _required_sources_for(category: str, evidence_type: str) -> list[str]:
    if evidence_type == "licensed_review":
        return ["licensed_review_dataset"]
    if evidence_type == "book_ocr":
        return ["ocr_book_corpus"]
    if evidence_type == "cerp_snapshot":
        return ["cerp_snapshot"]
    if evidence_type == "cerp_business_snapshot":
        return ["cerp_snapshot"]
    if evidence_type == "source_hierarchy":
        return ["controlling_source"]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
