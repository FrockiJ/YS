from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


BEHAVIOR_PROFILES: Dict[str, Dict[str, Any]] = {
    "general_chat": {
        "source_policy": "internal_preferred",
        "allow_external": False,
        "allow_fail_closed": False,
        "retrieval_priority": ["internal"],
        "required_doc_types": [],
        "blocked_doc_types": [],
        "citation_rule": "grounded_when_available",
    },
    "brand_profile": {
        "source_policy": "internal_preferred",
        "allow_external": True,
        "allow_fail_closed": False,
        "retrieval_priority": ["internal_approved", "internal_official", "internal", "external_authoritative"],
        "required_doc_types": ["brand", "supplier", "profile", "official", "website", "background"],
        "blocked_doc_types": ["inventory_only"],
        "citation_rule": "internal_approved_first",
    },
    "source_validation": {
        "source_policy": "authoritative_external_required",
        "allow_external": True,
        "allow_fail_closed": True,
        "retrieval_priority": ["external_authoritative", "internal_official", "internal_approved"],
        "required_doc_types": ["source", "official", "website", "citation", "reference"],
        "blocked_doc_types": ["inventory_only"],
        "citation_rule": "authoritative_or_fail_closed",
    },
    "internal_rag_only_validation": {
        "source_policy": "internal_only",
        "allow_external": False,
        "allow_fail_closed": True,
        "retrieval_priority": ["internal_approved", "manual", "reference", "internal"],
        "required_doc_types": ["source", "citation", "reference", "manual"],
        "blocked_doc_types": ["external_unverified", "inventory_only"],
        "citation_rule": "internal_trace_or_fail_closed",
    },
    "alias_inventory_equivalence": {
        "source_policy": "internal_preferred",
        "allow_external": False,
        "allow_fail_closed": False,
        "retrieval_priority": ["cerp", "internal_official", "internal_primary"],
        "required_doc_types": ["inventory", "stock", "product", "alias"],
        "blocked_doc_types": ["external_unverified"],
        "citation_rule": "inventory_snapshot_required",
    },
    "inventory_lookup": {
        "source_policy": "internal_preferred",
        "allow_external": False,
        "allow_fail_closed": False,
        "retrieval_priority": ["cerp", "internal_official", "internal_primary"],
        "required_doc_types": ["inventory", "stock", "product"],
        "blocked_doc_types": ["generic_profile"],
        "citation_rule": "inventory_binding_required",
    },
    "cerp_business_lookup": {
        "source_policy": "internal_only",
        "allow_external": False,
        "allow_fail_closed": True,
        "retrieval_priority": ["cerp", "internal_primary"],
        "required_doc_types": ["inventory", "stock", "product", "commercial_field"],
        "blocked_doc_types": ["external_unverified", "generic_profile"],
        "citation_rule": "business_snapshot_required",
    },
    "quote_recommendation": {
        "source_policy": "internal_only",
        "allow_external": False,
        "allow_fail_closed": False,
        "retrieval_priority": ["cerp", "internal_official", "internal_primary", "internal_approved"],
        "required_doc_types": ["inventory", "stock", "product", "portfolio"],
        "blocked_doc_types": ["external_unverified"],
        "citation_rule": "official_or_inventory_snapshot",
    },
    "url_product_lookup": {
        "source_policy": "authoritative_external_required",
        "allow_external": True,
        "allow_fail_closed": True,
        "retrieval_priority": ["internal_official", "cerp", "external_authoritative"],
        "required_doc_types": ["product", "official", "inventory"],
        "blocked_doc_types": [],
        "citation_rule": "url_or_inventory_binding",
    },
    "image_product_lookup": {
        "source_policy": "internal_preferred",
        "allow_external": False,
        "allow_fail_closed": False,
        "retrieval_priority": ["cerp", "internal_official", "internal_primary"],
        "required_doc_types": ["product", "inventory"],
        "blocked_doc_types": ["generic_profile"],
        "citation_rule": "inventory_binding_required",
    },
}


LEGACY_PROFILE_ALIASES: Dict[str, str] = {
    "critic_score_lookup": "source_validation",
    "exact_review_lookup": "internal_rag_only_validation",
    "book_corpus_lookup": "internal_rag_only_validation",
    "multi_review_compare": "source_validation",
    "source_hierarchy_conflict": "source_validation",
    "terroir_comparison": "source_validation",
    "vintage_region_overview": "general_chat",
    "tasting_note_generation": "general_chat",
    "vineyard_lookup": "source_validation",
    "producer_ranking": "brand_profile",
}


def get_behavior_profile(prompt_category: str | None) -> Dict[str, Any]:
    key = str(prompt_category or "").strip()
    key = LEGACY_PROFILE_ALIASES.get(key, key)
    profile = BEHAVIOR_PROFILES.get(key) or BEHAVIOR_PROFILES["general_chat"]
    return deepcopy(profile)
