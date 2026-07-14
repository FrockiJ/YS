import asyncio
import json
import logging
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ...core import db
from ...pipelines.rag.searcher import (
    structured_search as _structured_search,
    vector_search as _vector_search,
)
from ...schemas.ai import Hit, RetrievalResult
from ...services.cerp_query_planner import CerpQueryPlanner
from ...services.cerp_service import CerpService
from ...utils.inventory_intent import is_generic_inventory_listing_query
from ...utils.quote_search import (
    quote_product_exact_rejection_reasons,
    quote_product_matches_criteria,
)
from .google_cse_evidence import GoogleCseEvidenceService
from .source_registry import ProducerSourceDomainService
from .citation_validator import (
    controlling_source,
    normalize_source_metadata,
    should_fail_closed_for_citations,
    source_priority,
    validate_hits,
)
try:
    from .answer_route_policy import build_answer_route_policy
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    def build_answer_route_policy(
        *,
        prompt_category: Optional[str],
        intent_name: Optional[str] = None,
        entity_hints: Optional[Dict[str, Any]] = None,
        context_state: Optional[Dict[str, Any]] = None,
        behavior_profile: Optional[Dict[str, Any]] = None,
        source_policy: Optional[str] = None,
        needs_authoritative_sources: bool = False,
    ) -> Dict[str, Any]:
        profile = behavior_profile or {}
        return {
            "route": str(prompt_category or "grounded_answer"),
            "intent": intent_name,
            "evidence_type": "grounded_answer",
            "source_policy": source_policy or profile.get("source_policy") or "internal_preferred",
            "citation_rule": profile.get("citation_rule") or "grounded_when_available",
            "retrieval_priority": list(profile.get("retrieval_priority") or ["internal"]),
            "required_doc_types": list(profile.get("required_doc_types") or []),
            "blocked_doc_types": list(profile.get("blocked_doc_types") or []),
            "required_sources": [],
            "allowed_sources": [],
            "permission_boundary": {},
            "context": {},
            "entity_hints_present": bool(entity_hints),
        }

from .evidence_contracts import apply_evidence_contract, answer_plan_summary
try:
    from .burghound_issue_resolver import BurghoundIssueResolver
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    class BurghoundIssueResolver:  # type: ignore
        @staticmethod
        def should_handle(query: str) -> bool:
            return False

        async def resolve(self, query: str):
            return None

try:
    from .review_conflict_resolver import ReviewConflictResolver
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    class ReviewConflictResolver:  # type: ignore
        @staticmethod
        def should_handle(query: str) -> bool:
            return False

        async def resolve(self, query: str):
            return None
try:
    from .evidence_scoring_policy import score_breakdown, source_priority_boost
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    def source_priority_boost(
        hit: Any,
        *,
        priority: Iterable[str],
        required_doc_type_match: bool = False,
    ) -> Tuple[float, Dict[str, Any]]:
        meta = getattr(hit, "meta", None) or {}
        source_tier = str(getattr(hit, "source_tier", None) or meta.get("source_tier") or "").strip()
        source_type = str(getattr(hit, "source_type", None) or meta.get("source_type") or "").strip()
        search_text = " ".join(
            str(value or "")
            for value in (
                getattr(hit, "text", ""),
                getattr(hit, "summary", ""),
                source_type,
                source_tier,
                " ".join(str(item or "") for item in meta.values()),
            )
        ).lower()
        boost = 0.0
        matched: List[str] = []
        for idx, item in enumerate(priority or []):
            normalized = str(item or "").strip().lower()
            if not normalized:
                continue
            weight = max(0.05, 0.35 - idx * 0.04)
            if normalized == "cerp" and (source_type.lower() == "cerp" or "cerp" in search_text):
                boost += weight
                matched.append(normalized)
            elif normalized in {source_tier.lower(), source_type.lower()}:
                boost += weight
                matched.append(normalized)
            elif normalized and normalized in search_text:
                boost += weight
                matched.append(normalized)
        if required_doc_type_match:
            boost += 0.30
            matched.append("required_doc_type")
        return boost, {"matched_priorities": matched, "source_tier": source_tier, "source_type": source_type}

    def score_breakdown(
        hit: Any,
        *,
        base_score: float = 0.0,
        source_priority_boost_value: float = 0.0,
        entity_exact_match: bool = False,
        document_type_match: bool = False,
        context_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "base": base_score,
            "source_priority": source_priority_boost_value,
            "entity_exact": 0.0,
            "document_type": 0.0,
            "context_relevance": 0.0,
            "customer_profile": 0.0,
            "total": base_score + source_priority_boost_value,
            "matched": {
                "entity_exact": entity_exact_match,
                "document_type": document_type_match,
                "context_relevance": False,
                "customer_profile": False,
            },
        }

try:
    from .behavior_profiles import get_behavior_profile
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    def get_behavior_profile(prompt_category: Optional[str]) -> Dict[str, Any]:
        category = str(prompt_category or "").strip()
        if category in {"source_validation", "critic_score_lookup", "terroir_comparison", "url_product_lookup"}:
            return {
                "source_policy": "authoritative_external_required",
                "retrieval_priority": ["external_authoritative", "internal_official", "internal_approved", "internal"],
                "required_doc_types": [],
                "blocked_doc_types": [],
                "citation_rule": "authoritative_or_fail_closed",
            }
        if category == "quote_recommendation":
            return {
                "source_policy": "internal_only",
                "retrieval_priority": ["cerp", "internal_official", "internal_primary", "internal_approved"],
                "required_doc_types": ["inventory", "stock", "product", "portfolio"],
                "blocked_doc_types": ["external_unverified"],
                "citation_rule": "official_or_cerp_inventory",
            }
        return {
            "source_policy": "internal_preferred",
            "retrieval_priority": ["internal"],
            "required_doc_types": [],
            "blocked_doc_types": [],
            "citation_rule": "grounded_when_available",
        }

logger = logging.getLogger(__name__)

AUTHORITATIVE_PROMPT_CATEGORIES = {
    "terroir_comparison",
    "url_product_lookup",
    "source_validation",
    "critic_score_lookup",
    "exact_review_lookup",
    "book_corpus_lookup",
    "multi_review_compare",
    "source_hierarchy_conflict",
    "internal_rag_only_validation",
}
AUTHORITATIVE_SOURCE_TIERS = {"internal_official", "Tier 1", "Tier 2", "external_evidence"}
INTERNAL_OFFICIAL_DOMAINS = {"ys.local"}
INTERNAL_PRIMARY_DOMAINS = {"cerp.winton.com.tw"}
INTERNAL_PRIMARY_KEYWORDS = {"cerp", "inventory", "stock"}
INTERNAL_APPROVED_KEYWORDS = {"rap"}
PRODUCT_MATCH_PROMPT_CATEGORIES = {"image_product_lookup"}
CRITIC_LOOKUP_CATEGORIES = {
    "critic_score_lookup",
    "source_validation",
    "exact_review_lookup",
    "multi_review_compare",
}
LICENSED_REVIEW_CATEGORIES = {"exact_review_lookup", "multi_review_compare"}
BOOK_CONTRACT_CATEGORIES = {"book_corpus_lookup", "internal_rag_only_validation"}
CERP_SEARCH_PROMPT_CATEGORIES = {
    "quote_recommendation",
    "inventory_lookup",
    "url_product_lookup",
    "image_product_lookup",
    "alias_inventory_equivalence",
    "source_hierarchy_conflict",
}
CERP_EXPLICIT_LOOKUP_RE = re.compile(
    r"\b(?:cerp|stock|inventory|availability|quote|quotation)\b|庫存|現貨|有貨|缺貨|報價|詢價",
    re.IGNORECASE,
)
CRITIC_SOURCE_NAMES = ("Wine Advocate", "Jasper Morris", "Burghound", "Vinous", "Decanter", "Wine Spectator")
CRITIC_AUTHORITATIVE_DOMAINS = {
    "robertparker.com",
    "wineadvocate.com",
    "jaspermorrisinsideburgundy.com",
    "insideburgundy.com",
    "burghound.com",
    "vinous.com",
    "decanter.com",
    "winespectator.com",
}


class RetrievalService:
    def __init__(
        self,
        cerp_service: Optional[CerpService] = None,
        external_search_service: Optional[Any] = None,
        producer_source_domain_service: Optional[ProducerSourceDomainService] = None,
    ) -> None:
        self._cerp_service = cerp_service or CerpService()
        self._external_search_service = external_search_service or GoogleCseEvidenceService()
        self._producer_source_domain_service = producer_source_domain_service or ProducerSourceDomainService()

    async def search(
        self,
        query: str,
        *,
        conn=None,
        rag_k: int = 8,
        cerp_limit: int = 50,
        query_variants: Optional[List[str]] = None,
        alias_filters: Optional[Dict[str, Any]] = None,
        entity_hints: Optional[Dict[str, Any]] = None,
        entity_resolution: Optional[Dict[str, Any]] = None,
        followup_context: Optional[Dict[str, Any]] = None,
        attachment_context: Optional[Dict[str, Any]] = None,
        url_lookup: Optional[Dict[str, Any]] = None,
        lookup_goal: Optional[str] = None,
        prompt_category: Optional[str] = None,
        intent_name: Optional[str] = None,
        needs_authoritative_sources: bool = False,
        source_policy: str = "internal_preferred",
        external_search_reason: Optional[str] = None,
        context_state: Optional[Dict[str, Any]] = None,
        request_deadline_at: Optional[float] = None,
    ) -> RetrievalResult:
        errors: Dict[str, str] = {}
        attachment_hints = (
            attachment_context.get("entity_hints")
            if isinstance(attachment_context, dict) and isinstance(attachment_context.get("entity_hints"), dict)
            else {}
        )
        merged_entity_hints = self._merge_entity_hints(entity_hints or {}, attachment_hints)
        merged_entity_hints = self._merge_context_entity_hints(merged_entity_hints, context_state or {})
        effective_query = (
            str((attachment_context or {}).get("search_query") or "").strip()
            if isinstance(attachment_context, dict)
            else ""
        ) or query
        behavior_profile = get_behavior_profile(prompt_category)
        route_policy = build_answer_route_policy(
            prompt_category=prompt_category,
            intent_name=intent_name,
            entity_hints=merged_entity_hints,
            context_state=context_state or {},
            behavior_profile=behavior_profile,
            source_policy=source_policy,
            needs_authoritative_sources=needs_authoritative_sources,
        )
        if (
            prompt_category == "url_product_lookup"
            and str(lookup_goal or "").strip() == "product_availability_from_url"
        ):
            return await self._search_url_product_lookup(
                query=query,
                effective_query=effective_query,
                entity_hints=merged_entity_hints,
                url_lookup=url_lookup or {},
                query_variants=query_variants,
                alias_filters=alias_filters,
                rag_k=rag_k,
                cerp_limit=cerp_limit,
            )
        if self._is_cerp_first_product_lookup(
            prompt_category=prompt_category,
            attachment_context=attachment_context,
        ):
            return await self._search_cerp_first_product_lookup(
                query=query,
                effective_query=effective_query,
                attachment_context=attachment_context or {},
                entity_hints=merged_entity_hints,
                query_variants=query_variants,
                alias_filters=alias_filters,
                rag_k=rag_k,
                cerp_limit=cerp_limit,
            )
        skip_internal_search = self._should_skip_full_internal_search(
            prompt_category=prompt_category,
            needs_authoritative_sources=needs_authoritative_sources,
            source_policy=source_policy,
        )
        if skip_internal_search:
            rag_result, cerp_result = [], []
        elif self._should_skip_cerp_search(prompt_category, effective_query):
            rag_result = await self._run_rag_search(
                effective_query,
                query_variants=query_variants,
                alias_filters=alias_filters,
                rag_k=rag_k,
                prompt_category=prompt_category,
                entity_hints=merged_entity_hints,
            )
            cerp_result = []
        else:
            rag_task = self._run_rag_search(
                effective_query,
                query_variants=query_variants,
                alias_filters=alias_filters,
                rag_k=rag_k,
                prompt_category=prompt_category,
                entity_hints=merged_entity_hints,
            )
            cerp_task = self._run_cerp_search(effective_query, cerp_limit)
            rag_result, cerp_result = await asyncio.gather(
                rag_task,
                cerp_task,
                return_exceptions=True,
            )

        rag_hits: List[Dict[str, Any]] = []
        cerp_products: List[Dict[str, Any]] = []

        if isinstance(rag_result, Exception):
            errors["rag"] = f"{type(rag_result).__name__}: {rag_result}"
        else:
            rag_hits = rag_result or []

        if isinstance(cerp_result, Exception):
            errors["cerp"] = f"{type(cerp_result).__name__}: {cerp_result}"
        else:
            cerp_products = cerp_result or []

        internal_hits: List[Hit] = []
        for hit in rag_hits:
            internal_hits.append(self._rag_hit_to_model(hit))
        for product in cerp_products:
            hit = self._cerp_product_to_hit(product)
            if hit:
                internal_hits.append(hit)
        retrieval_mode_snapshot = self._build_retrieval_mode_snapshot(internal_hits)
        if retrieval_mode_snapshot.get("embedding_unavailable"):
            errors.setdefault(
                "embedding",
                str(retrieval_mode_snapshot.get("embedding_error_type") or "embedding_unavailable"),
            )
        requested_review_sources = (
            self._requested_review_source_names(effective_query)
            if prompt_category in LICENSED_REVIEW_CATEGORIES
            else []
        )
        if requested_review_sources:
            requested_review_source_set = set(requested_review_sources)
            internal_hits = [
                hit for hit in internal_hits
                if self._hit_matches_requested_review_source(hit, requested_review_source_set)
            ]
        cerp_operational_query = self._requires_current_cerp_evidence(
            effective_query,
            prompt_category=prompt_category,
        )

        review_conflict_internal_only = (
            prompt_category == "source_hierarchy_conflict"
            and ReviewConflictResolver.should_handle(effective_query)
        )
        duplicate_record_internal_only = self._is_duplicate_record_query(effective_query)
        contract_internal_only = (
            prompt_category in LICENSED_REVIEW_CATEGORIES | BOOK_CONTRACT_CATEGORIES
            or review_conflict_internal_only
            or duplicate_record_internal_only
        )
        resolved_external_reason = self._determine_external_search_reason(
            internal_hits,
            entity_hints=merged_entity_hints,
            prompt_category=prompt_category,
            needs_authoritative_sources=needs_authoritative_sources,
            source_policy=source_policy,
            requested_reason=external_search_reason,
        )
        if contract_internal_only:
            resolved_external_reason = None
        internal_coverage_low = self._internal_coverage_is_low(
            internal_hits,
            entity_hints=merged_entity_hints,
            prompt_category=prompt_category,
        )
        if contract_internal_only:
            seeded_domains = {"verified_domains": [], "candidate_domains": []}
            external_hits = []
            external_search = {
                "attempted": False,
                "reason": None,
                "provider": None,
                "query": None,
                "hit_count_pre_filter": 0,
                "hit_count_post_filter": 0,
                "fetched_url_count": 0,
                "fetched_count": 0,
                "usable_fetched_count": 0,
                "authoritative_hit_count": 0,
                "search_results": [],
                "fetched_pages": [],
                "response_sections": {},
                "response_found": False,
                "sections_covered": [],
                "failure_reasons": [],
                "termination_reason": None,
                "provider_unavailable": False,
                "budget_exhausted": False,
                "quality_gate": "internal_contract_only",
                "duration_ms": 0.0,
            }
        else:
            seeded_domains = await self._producer_source_domain_service.lookup_seeded_domains(
                merged_entity_hints.get("producer")
            )

            external_search_started = time.perf_counter()
            external_hits, external_errors, external_search = await asyncio.to_thread(
                self._external_search_service.search,
                effective_query,
                entity_hints=merged_entity_hints,
                prompt_category=prompt_category,
                external_search_reason=resolved_external_reason,
                source_policy=source_policy,
                needs_authoritative_sources=needs_authoritative_sources,
                internal_hit_count=len(internal_hits),
                limit=5 if resolved_external_reason else 0,
                verified_domains=seeded_domains.get("verified_domains") or [],
                candidate_domains=seeded_domains.get("candidate_domains") or [],
                request_deadline_at=request_deadline_at,
            )
            external_search["duration_ms"] = round((time.perf_counter() - external_search_started) * 1000, 1)
            if external_errors:
                errors.update(external_errors)

        critic_lookup = self._build_critic_lookup_snapshot(
            query=effective_query,
            entity_hints=merged_entity_hints,
            followup_context=followup_context or {},
            internal_hits=internal_hits,
            external_hits=external_hits,
            external_search=external_search,
            prompt_category=prompt_category,
        )

        fail_closed_selection = self._should_fail_closed_selection(
            prompt_category=prompt_category,
            needs_authoritative_sources=needs_authoritative_sources,
            external_search=external_search,
            external_hits=external_hits,
            internal_coverage_low=internal_coverage_low,
        )
        if contract_internal_only and internal_hits:
            fail_closed_selection = False
        if (
            prompt_category == "critic_score_lookup"
            and fail_closed_selection
            and int(critic_lookup.get("secondary_evidence_count") or 0) > 0
        ):
            fail_closed_selection = False
        general_low_coverage_short_circuit = self._should_short_circuit_general_low_coverage(
            prompt_category=prompt_category,
            internal_coverage_low=internal_coverage_low,
            entity_hints=merged_entity_hints,
            external_search_reason=resolved_external_reason,
        )
        if fail_closed_selection:
            errors.setdefault(
                "grounding",
                "Authoritative query did not yield Tier 1/Tier 2 external sources or strong internal coverage.",
            )

        selected_hits = self._select_hits(
            internal_hits,
            external_hits,
            prompt_category=prompt_category,
            external_search_reason=resolved_external_reason,
            needs_authoritative_sources=needs_authoritative_sources,
            fail_closed_selection=fail_closed_selection,
        )
        if cerp_operational_query and cerp_products:
            cerp_hits = [
                hit
                for hit in internal_hits
                if hit.source_type == "cerp"
                or str((hit.meta or {}).get("source_family") or "").strip() == "cerp_snapshot"
            ]
            if cerp_hits:
                selected_hits = self._dedupe_hit_models(cerp_hits[:4] + selected_hits[:6])
        selected_hits, retrieval_decision = self._apply_profile_policy(
            selected_hits,
            prompt_category=prompt_category,
            behavior_profile=behavior_profile,
            entity_hints=merged_entity_hints,
            context_state=context_state or {},
        )
        selected_hits, evidence_contract = apply_evidence_contract(
            query=effective_query,
            prompt_category=prompt_category,
            entity_hints=merged_entity_hints,
            selected_hits=selected_hits,
            cerp_products=cerp_products,
            source_policy=source_policy,
            route_policy=route_policy,
        )
        retrieval_decision["evidence_contract"] = evidence_contract
        if evidence_contract.get("status") == "fail_closed":
            reason = str(evidence_contract.get("fail_closed_reason") or "evidence_contract_fail_closed")
            errors.setdefault("evidence_contract", reason)
            retrieval_decision.setdefault("rejected_reasons", []).append(reason)
            retrieval_decision.setdefault("hard_error_flags", []).append(reason)
        if critic_lookup:
            critic_lookup["selected_evidence_count"] = len(selected_hits)
        official_inventory_binding = self._build_official_inventory_binding(
            query=effective_query,
            prompt_category=prompt_category,
            source_policy=source_policy,
            selected_hits=selected_hits,
            cerp_products=cerp_products,
        )
        if official_inventory_binding.get("required"):
            selected_hits = [
                hit for hit in selected_hits if self._hit_has_official_inventory_proof(hit)
            ]
            official_inventory_binding["selected_hit_count_after_filter"] = len(selected_hits)
            if not selected_hits:
                errors.setdefault(
                    "official_inventory_binding",
                    "Official-site or CERP sellable inventory binding was required, but no bound hits remained.",
                )
                retrieval_decision.setdefault("rejected_reasons", []).append("official_inventory_binding_missing")
        retrieval_decision["selected_hit_count_after_policy"] = len(selected_hits)
        citation_validation = validate_hits(
            selected_hits,
            source_policy=source_policy,
            prompt_category=prompt_category,
        )
        citation_controlling_source = controlling_source(selected_hits)
        citation_fail_closed = should_fail_closed_for_citations(
            citation_validation,
            source_policy=source_policy,
            prompt_category=prompt_category,
        )
        if citation_validation.get("hard_error_flags"):
            retrieval_decision.setdefault("hard_error_flags", []).extend(citation_validation["hard_error_flags"])
        if citation_fail_closed:
            errors.setdefault(
                "citation_validation",
                "Selected evidence failed auditability or required metadata validation.",
            )
            retrieval_decision.setdefault("rejected_reasons", []).append("citation_validation_fail_closed")
            retrieval_decision["citation_validation_fail_closed"] = True
            selected_hits = []
        source_tiers = self._collect_source_tiers(selected_hits)
        retrieval_snapshot = {
            "query": query,
            "effective_query": effective_query,
            "prompt_category": prompt_category,
            "behavior_profile": behavior_profile,
            "route_policy": route_policy,
            "context_state": context_state or {},
            "retrieval_decision": retrieval_decision,
            "needs_authoritative_sources": needs_authoritative_sources,
            "source_policy": source_policy,
            "external_search_reason": resolved_external_reason,
            "entity_hints": merged_entity_hints,
            "entity_resolution": entity_resolution or {},
            "followup_context": followup_context or {},
            "internal_hit_count": len(internal_hits),
            "external_hit_count": len(external_hits),
            "selected_hit_count": len(selected_hits),
            "source_tiers": source_tiers,
            "retrieval_modes": retrieval_mode_snapshot,
            "citation_validation": citation_validation,
            "controlling_source": citation_controlling_source,
            "official_inventory_binding": official_inventory_binding,
            "evidence_contract": evidence_contract,
            "answer_plan": evidence_contract.get("answer_plan") if isinstance(evidence_contract, dict) else None,
            "answer_plan_summary": answer_plan_summary(evidence_contract) if isinstance(evidence_contract, dict) else "",
            "critic_lookup": critic_lookup,
            "internal_search_skipped": skip_internal_search,
            "cerp_search_allowed": not self._should_skip_cerp_search(prompt_category, effective_query),
            "internal_coverage_low": internal_coverage_low,
            "authoritative_quality_gate_passed": not fail_closed_selection,
            "external_search": external_search,
            "seeded_domains": seeded_domains,
            "attachment_context_used": bool(attachment_context),
            "request_deadline_exceeded": str(external_search.get("termination_reason") or "").strip() == "request_deadline_exceeded",
            "response_mode": (
                "templated_fail_closed"
                if fail_closed_selection or citation_fail_closed or evidence_contract.get("status") == "fail_closed"
                else (
                    "critic_secondary_evidence_no_score"
                    if (
                        prompt_category == "critic_score_lookup"
                        and int(critic_lookup.get("authoritative_score_count") or 0) == 0
                        and selected_hits
                    )
                    else (
                    "templated_internal_low_coverage"
                    if (
                        prompt_category in {"producer_ranking", "tasting_note_generation", "vineyard_lookup"}
                        and not selected_hits
                    )
                    else (
                    "templated_internal_low_coverage"
                    if general_low_coverage_short_circuit or (
                        official_inventory_binding.get("required") and not selected_hits
                    )
                    else "generated"
                    )
                    )
                )
            ),
        }

        return RetrievalResult(
            hits=selected_hits,
            cerp_products=cerp_products,
            errors=errors,
            internal_hits=internal_hits,
            external_hits=external_hits,
            selected_hits=selected_hits,
            retrieval_errors=errors,
            source_tiers=source_tiers,
            external_search=external_search,
            retrieval_snapshot=retrieval_snapshot,
        )

    @staticmethod
    def _requires_current_cerp_evidence(query: str, *, prompt_category: Optional[str]) -> bool:
        if str(prompt_category or "").strip() != "source_hierarchy_conflict":
            return False
        lowered = str(query or "").casefold()
        has_current_fact = any(
            token in lowered
            for token in (
                "current",
                "retail price",
                "price",
                "stock",
                "inventory",
                "sku",
                "available",
                "availability",
                "sellable",
            )
        )
        has_internal_marker = any(
            token in lowered
            for token in (
                "cerp",
                "erp",
                "ys wine cellars",
                "ys_ai",
                "internal",
            )
        )
        return has_current_fact and has_internal_marker

    @staticmethod
    def _build_retrieval_mode_snapshot(hits: List[Hit]) -> Dict[str, Any]:
        mode_counts: Dict[str, int] = {}
        embedding_errors: List[Dict[str, Any]] = []
        models: List[str] = []
        for hit in hits or []:
            meta = hit.meta or {}
            mode = str(meta.get("retrieval_mode") or "").strip() or "unknown"
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
            model = str(meta.get("embedding_model") or "").strip()
            if model and model not in models:
                models.append(model)
            if meta.get("embedding_unavailable"):
                error_type = str(meta.get("embedding_error_type") or "embedding_unavailable").strip()
                error_message = str(meta.get("embedding_error_message") or "").strip()
                item = {"type": error_type}
                if error_message:
                    item["message"] = error_message[:240]
                if item not in embedding_errors:
                    embedding_errors.append(item)
        return {
            "mode_counts": mode_counts,
            "embedding_models": models,
            "embedding_unavailable": bool(embedding_errors),
            "embedding_error_type": embedding_errors[0]["type"] if embedding_errors else "",
            "embedding_errors": embedding_errors,
        }

    @staticmethod
    def _merge_entity_hints(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        for key, value in (extra or {}).items():
            if isinstance(value, str) and value.strip() and not merged.get(key):
                merged[key] = value.strip()
        return merged

    @staticmethod
    def _merge_context_entity_hints(base: Dict[str, Any], context_state: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        if not isinstance(context_state, dict):
            return merged
        if context_state.get("topic_shift_detected"):
            return merged
        protected = context_state.get("protected_entities")
        if not isinstance(protected, dict):
            protected = {}
        for key, value in protected.items():
            if value in (None, "", [], {}):
                continue
            if merged.get(key) in (None, "", [], {}):
                merged[key] = value
        return merged

    @staticmethod
    def _is_cerp_first_product_lookup(
        *,
        prompt_category: Optional[str],
        attachment_context: Optional[Dict[str, Any]],
    ) -> bool:
        if prompt_category not in PRODUCT_MATCH_PROMPT_CATEGORIES:
            return False
        if not isinstance(attachment_context, dict):
            return False
        return str(attachment_context.get("match_intent") or "").strip() == "cerp_match"

    @staticmethod
    def _should_skip_full_internal_search(
        *,
        prompt_category: Optional[str],
        needs_authoritative_sources: bool,
        source_policy: str,
    ) -> bool:
        return False

    @staticmethod
    def _should_skip_cerp_search(prompt_category: Optional[str], query: Optional[str] = None) -> bool:
        if prompt_category == "source_hierarchy_conflict" and ReviewConflictResolver.should_handle(str(query or "")):
            return True
        if RetrievalService._is_duplicate_record_query(str(query or "")):
            return True
        if prompt_category in CERP_SEARCH_PROMPT_CATEGORIES:
            return False
        return not RetrievalService._has_explicit_cerp_lookup_intent(query)

    @staticmethod
    def _has_explicit_cerp_lookup_intent(query: Optional[str]) -> bool:
        return bool(CERP_EXPLICIT_LOOKUP_RE.search(str(query or "")))

    @staticmethod
    def _is_generic_inventory_listing_query(query: Optional[str]) -> bool:
        return is_generic_inventory_listing_query(query)

    @classmethod
    def _build_critic_lookup_snapshot(
        cls,
        *,
        query: str,
        entity_hints: Dict[str, Any],
        followup_context: Dict[str, Any],
        internal_hits: List[Hit],
        external_hits: List[Hit],
        external_search: Dict[str, Any],
        prompt_category: Optional[str],
    ) -> Dict[str, Any]:
        if prompt_category not in CRITIC_LOOKUP_CATEGORIES:
            return {}
        subjects = cls._extract_critic_subjects(entity_hints, followup_context, query)
        query_variants = [
            str(item or "").strip()
            for item in (external_search or {}).get("query_variants_used", [])
            if str(item or "").strip()
        ]
        authoritative_score_count = sum(
            1
            for hit in [*external_hits, *internal_hits]
            if cls._hit_has_authoritative_score_trace(hit)
        )
        secondary_evidence_count = sum(
            1
            for hit in [*external_hits, *internal_hits]
            if not cls._is_inventory_hit(hit)
        )
        no_score_reason = None
        if authoritative_score_count == 0:
            no_score_reason = (
                "secondary_evidence_only"
                if secondary_evidence_count
                else str((external_search or {}).get("quality_gate") or "no_authoritative_score_trace")
            )
        return {
            "subjects": subjects,
            "critic_sources_attempted": list(CRITIC_SOURCE_NAMES),
            "query_variants_used": query_variants,
            "authoritative_score_count": authoritative_score_count,
            "secondary_evidence_count": secondary_evidence_count,
            "no_score_reason": no_score_reason,
        }

    @classmethod
    def _extract_critic_subjects(
        cls,
        entity_hints: Dict[str, Any],
        followup_context: Dict[str, Any],
        query: str,
    ) -> List[str]:
        producer = cls._clean_producer_hint((entity_hints or {}).get("producer"))
        subjects: List[str] = []
        if producer:
            subjects.append(producer)
        anchor = (
            followup_context.get("context_anchor_used")
            if isinstance(followup_context.get("context_anchor_used"), dict)
            else {}
        )
        for subject in anchor.get("subjects") or []:
            cleaned = cls._clean_producer_hint(subject)
            if cleaned and cleaned not in subjects:
                subjects.append(cleaned)
        if not subjects:
            inferred = cls._extract_subject_from_text(query)
            if inferred:
                subjects.append(inferred)
        return subjects[:4]

    @classmethod
    def _clean_producer_hint(cls, value: Any) -> str:
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = " ".join(str(item or "").replace("\n", " ").split()).strip(" ,;:[]'")
            lowered = text.lower()
            if not text:
                continue
            if cls._looks_like_critic_source_name(lowered):
                continue
            if lowered.startswith("[") and lowered.endswith("]"):
                continue
            return text
        return ""

    @staticmethod
    def _looks_like_critic_source_name(text: str) -> bool:
        lowered = str(text or "").lower()
        return any(
            token in lowered
            for token in (
                "wine advocate",
                "jasper morris",
                "burghound",
                "vinous",
                "decanter",
                "drinking window",
                "score",
                "page",
            )
        )

    @staticmethod
    def _extract_subject_from_text(text: str) -> str:
        match = re.search(
            r"\b((?:YS|Champagne|Maison|Chateau|Château)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){0,3}|[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+\s+Colin)\b",
            str(text or ""),
        )
        return " ".join(match.group(1).split()) if match else ""

    @classmethod
    def _hit_has_authoritative_score_trace(cls, hit: Hit) -> bool:
        meta = hit.meta or {}
        domain = cls._extract_domain(meta)
        text = " ".join(
            str(value or "")
            for value in (
                hit.text,
                hit.summary,
                meta.get("title"),
                meta.get("url"),
                meta.get("source_url"),
            )
        ).lower()
        has_score_language = bool(re.search(r"\b(?:score|rating|points?|pt|pts|drinking window)\b|\b\d{2,3}\s*(?:pts?|points?)\b", text))
        source_family = str(meta.get("source_family") or "").strip()
        source_site = str(meta.get("source_site") or meta.get("source_name") or "").strip()
        has_local_score = bool(
            str(meta.get("score") or meta.get("score_raw") or meta.get("score_numeric") or "").strip()
            or has_score_language
        )
        has_reviewer = bool(str(meta.get("reviewer") or "").strip() or re.search(r"\breviewer\s*:", text))
        has_trace = bool(
            str(
                meta.get("source_trace")
                or meta.get("record_key")
                or meta.get("row_number")
                or meta.get("row_id")
                or ""
            ).strip()
        )
        if (
            source_family == "licensed_review_dataset"
            and source_site in {"inside_burgundy", "vinous", "wine_advocate", "wine_spectator", "burghound", "decanter"}
            and has_local_score
            and has_reviewer
            and has_trace
        ):
            return True
        return domain in CRITIC_AUTHORITATIVE_DOMAINS and has_score_language

    @staticmethod
    def _is_inventory_hit(hit: Hit) -> bool:
        meta = hit.meta or {}
        source = str(meta.get("source") or "").strip().lower()
        return hit.source_type == "cerp" or source == "cerp"

    async def _search_cerp_first_product_lookup(
        self,
        *,
        query: str,
        effective_query: str,
        attachment_context: Dict[str, Any],
        entity_hints: Dict[str, Any],
        query_variants: Optional[List[str]],
        alias_filters: Optional[Dict[str, Any]],
        rag_k: int,
        cerp_limit: int,
    ) -> RetrievalResult:
        errors: Dict[str, str] = {}
        product_criteria = self._build_product_match_criteria(entity_hints)
        cerp_products = await self._cerp_service.search_quote_candidates(
            effective_query or query,
            query_variants=self._normalize_query_variants(effective_query or query, query_variants),
            limit=max(cerp_limit, 12),
            page_size=min(max(cerp_limit, 12), 50),
            desired_quantity=1,
            quote_criteria=product_criteria,
            max_pages_per_term=1,
            raise_on_error=True,
        )
        exact_products = [
            item for item in cerp_products
            if quote_product_matches_criteria(item, product_criteria)
        ]
        near_products = [
            item for item in cerp_products
            if item not in exact_products
        ]
        exact_rejection_reasons = [
            {
                "code": str(item.get("no") or item.get("id") or ""),
                "name": str(item.get("name") or item.get("name_en") or item.get("name_ch") or ""),
                "reasons": quote_product_exact_rejection_reasons(item, product_criteria),
            }
            for item in near_products[:5]
            if quote_product_exact_rejection_reasons(item, product_criteria)
        ]
        official_hits = await self._run_official_product_lookup_with_conn(
            effective_query or query,
            entity_hints=entity_hints,
            limit=3,
        ) if not exact_products else []
        rag_hits_raw = await self._run_rag_search(
            effective_query or query,
            query_variants=query_variants,
            alias_filters=alias_filters,
            rag_k=min(rag_k, 3),
        )
        rag_hits = [self._rag_hit_to_model(hit) for hit in rag_hits_raw]
        cerp_hits = [
            hit
            for hit in (
                self._cerp_product_to_hit(product, match_type="exact" if product in exact_products else "near")
                for product in (exact_products[:3] or near_products[:3])
            )
            if hit
        ]
        selected_hits = self._dedupe_hit_models(
            cerp_hits
            + official_hits[:2]
            + (rag_hits[:2] if (cerp_hits or official_hits) else rag_hits[:5])
        )
        internal_hits = self._dedupe_hit_models(cerp_hits + official_hits + rag_hits)
        source_tiers = self._collect_source_tiers(selected_hits)
        retrieval_snapshot = {
            "query": query,
            "effective_query": effective_query or query,
            "prompt_category": "image_product_lookup",
            "needs_authoritative_sources": False,
            "source_policy": "internal_preferred",
            "external_search_reason": None,
            "entity_hints": entity_hints,
            "internal_hit_count": len(internal_hits),
            "external_hit_count": 0,
            "selected_hit_count": len(selected_hits),
            "source_tiers": source_tiers,
            "internal_coverage_low": not bool(cerp_hits or official_hits),
            "authoritative_quality_gate_passed": True,
            "external_search": {
                "attempted": False,
                "reason": None,
                "provider": None,
                "query": None,
                "hit_count_pre_filter": 0,
                "hit_count_post_filter": 0,
                "fetched_url_count": 0,
            },
            "seeded_domains": {"producer_names": [], "verified_domains": [], "candidate_domains": [], "rows": []},
            "attachment_context_used": bool(attachment_context),
            "match_strategy": "cerp_first",
            "official_match_used": bool(official_hits),
            "exact_match_count": len(exact_products),
            "near_match_count": len(near_products),
            "exact_match_rejection_reasons": exact_rejection_reasons,
            "criteria_hard_filters": {
                key: value
                for key, value in product_criteria.items()
                if key in {"producer", "wine_name", "vintage", "color"} and value
            },
        }
        return RetrievalResult(
            hits=selected_hits,
            cerp_products=cerp_products,
            errors=errors,
            internal_hits=internal_hits,
            external_hits=[],
            selected_hits=selected_hits,
            retrieval_errors=errors,
            source_tiers=source_tiers,
            external_search=retrieval_snapshot["external_search"],
            retrieval_snapshot=retrieval_snapshot,
        )

    async def _search_url_product_lookup(
        self,
        *,
        query: str,
        effective_query: str,
        entity_hints: Dict[str, Any],
        url_lookup: Dict[str, Any],
        query_variants: Optional[List[str]],
        alias_filters: Optional[Dict[str, Any]],
        rag_k: int,
        cerp_limit: int,
    ) -> RetrievalResult:
        errors: Dict[str, str] = {}
        url_lookup_meta = dict(url_lookup or {})
        lookup_hints = (
            url_lookup_meta.get("entity_hints")
            if isinstance(url_lookup_meta.get("entity_hints"), dict)
            else {}
        )
        merged_entity_hints = self._merge_entity_hints(entity_hints or {}, lookup_hints or {})
        product_criteria = self._build_product_match_criteria(merged_entity_hints)
        official_hits = await self._run_official_product_lookup_with_conn(
            effective_query or query,
            entity_hints=merged_entity_hints,
            limit=3,
            canonical_url=str(url_lookup_meta.get("canonical_url") or "").strip() or None,
            product_handle=str(url_lookup_meta.get("product_handle") or "").strip() or None,
        )
        url_page_hit = self._url_lookup_to_official_hit(url_lookup_meta)
        if url_page_hit and not any((hit.meta or {}).get("url") == (url_page_hit.meta or {}).get("url") for hit in official_hits):
            official_hits.insert(0, url_page_hit)

        cerp_query = str(url_lookup_meta.get("search_query") or effective_query or query).strip() or query
        cerp_products = await self._cerp_service.search_quote_candidates(
            cerp_query,
            query_variants=self._build_url_lookup_query_variants(cerp_query, merged_entity_hints, query_variants),
            limit=max(cerp_limit, 12),
            page_size=min(max(cerp_limit, 12), 50),
            desired_quantity=1,
            quote_criteria=product_criteria,
            max_pages_per_term=1,
            raise_on_error=True,
        )
        exact_products = [
            item for item in cerp_products
            if quote_product_matches_criteria(item, product_criteria)
        ]
        near_products = [
            item for item in cerp_products
            if item not in exact_products
        ]
        exact_rejection_reasons = [
            {
                "code": str(item.get("no") or item.get("id") or ""),
                "name": str(item.get("name") or item.get("name_en") or item.get("name_ch") or ""),
                "reasons": quote_product_exact_rejection_reasons(item, product_criteria),
            }
            for item in near_products[:5]
            if quote_product_exact_rejection_reasons(item, product_criteria)
        ]
        rag_hits_raw = await self._run_rag_search(
            effective_query or query,
            query_variants=query_variants,
            alias_filters=alias_filters,
            rag_k=min(rag_k, 2),
        )
        rag_hits = [self._rag_hit_to_model(hit) for hit in rag_hits_raw]
        cerp_hits = [
            hit
            for hit in (
                self._cerp_product_to_hit(product, match_type="exact" if product in exact_products else "near")
                for product in (exact_products[:3] or near_products[:3])
            )
            if hit
        ]
        selected_hits = self._dedupe_hit_models(
            cerp_hits + official_hits[:2] + (rag_hits[:1] if (cerp_hits or official_hits) else [])
        )
        internal_hits = self._dedupe_hit_models(cerp_hits + official_hits + rag_hits)
        parse_status = str(url_lookup_meta.get("parse_status") or "").strip() or "failed"
        availability_result = self._resolve_url_lookup_availability_result(
            parse_status=parse_status,
            exact_products=exact_products,
            near_products=near_products,
            official_hits=official_hits,
        )
        followup_contract = self._build_url_quote_followup_contract(
            query=query,
            effective_query=cerp_query,
            entity_hints=merged_entity_hints,
            availability_result=availability_result,
            exact_products=exact_products,
            near_products=near_products,
            url_lookup=url_lookup_meta,
        )
        source_tiers = self._collect_source_tiers(selected_hits)
        retrieval_snapshot = {
            "query": query,
            "effective_query": cerp_query,
            "prompt_category": "url_product_lookup",
            "needs_authoritative_sources": True,
            "source_policy": "authoritative_external_required",
            "external_search_reason": "inventory_verification",
            "entity_hints": merged_entity_hints,
            "internal_hit_count": len(internal_hits),
            "external_hit_count": 0,
            "selected_hit_count": len(selected_hits),
            "source_tiers": source_tiers,
            "internal_search_skipped": False,
            "internal_coverage_low": not bool(cerp_hits or official_hits),
            "authoritative_quality_gate_passed": bool(exact_products or near_products or official_hits or parse_status == "failed"),
            "external_search": {
                "attempted": False,
                "reason": "inventory_verification",
                "provider": None,
                "query": None,
                "hit_count_pre_filter": 0,
                "hit_count_post_filter": 0,
                "fetched_url_count": 0,
                "fetched_count": 0,
                "usable_fetched_count": 0,
                "authoritative_hit_count": 0,
                "search_results": [],
                "fetched_pages": [],
                "response_sections": {},
                "response_found": False,
                "sections_covered": [],
                "failure_reasons": [],
                "termination_reason": None,
                "provider_unavailable": False,
                "budget_exhausted": False,
                "quality_gate": "inventory_verification",
            },
            "seeded_domains": {"producer_names": [], "verified_domains": [], "candidate_domains": [], "rows": []},
            "attachment_context_used": False,
            "request_deadline_exceeded": False,
            "response_mode": "templated_url_product_lookup",
            "match_strategy": "cerp_first_url_lookup",
            "official_match_used": bool(official_hits),
            "exact_match_count": len(exact_products),
            "near_match_count": len(near_products),
            "exact_candidate_ids": [
                str(item.get("no") or item.get("id") or "").strip()
                for item in exact_products
                if str(item.get("no") or item.get("id") or "").strip()
            ],
            "near_candidate_ids": [
                str(item.get("no") or item.get("id") or "").strip()
                for item in near_products
                if str(item.get("no") or item.get("id") or "").strip()
            ],
            "exact_match_rejection_reasons": exact_rejection_reasons,
            "criteria_hard_filters": {
                key: value
                for key, value in product_criteria.items()
                if key in {"producer", "wine_name", "vintage", "color"} and value
            },
            "availability_result": availability_result,
            "url_lookup": url_lookup_meta,
            "quote_followup": followup_contract,
            "available_actions": list(followup_contract.get("available_actions") or []),
            "pending_goal": followup_contract.get("pending_goal"),
            "default_confirm_action": followup_contract.get("default_confirm_action"),
        }
        return RetrievalResult(
            hits=selected_hits,
            cerp_products=cerp_products,
            errors=errors,
            internal_hits=internal_hits,
            external_hits=[],
            selected_hits=selected_hits,
            retrieval_errors=errors,
            source_tiers=source_tiers,
            external_search=retrieval_snapshot["external_search"],
            retrieval_snapshot=retrieval_snapshot,
        )

    @staticmethod
    def _build_product_match_criteria(entity_hints: Dict[str, Any]) -> Dict[str, Any]:
        producer = str(entity_hints.get("producer") or "").strip()
        wine_name = str(entity_hints.get("wine_name") or entity_hints.get("full_wine_name") or "").strip()
        if producer and wine_name and wine_name.lower().startswith(producer.lower()):
            wine_name = wine_name[len(producer):].strip(" ,/-")
        return {
            "producer": producer or None,
            "wine_name": wine_name or None,
            "vintage": str(entity_hints.get("vintage") or "").strip() or None,
            "region": str(entity_hints.get("region") or "").strip() or None,
            "region_filter": str(entity_hints.get("region") or "").strip() or None,
            "color": str(entity_hints.get("color") or "").strip() or None,
            "style": str(entity_hints.get("style") or "").strip() or None,
            "recommendation_profile": {},
            "alias_filters": {},
        }

    async def _run_official_product_lookup_with_conn(
        self,
        query: str,
        *,
        entity_hints: Dict[str, Any],
        limit: int,
        canonical_url: Optional[str] = None,
        product_handle: Optional[str] = None,
    ) -> List[Hit]:
        producer = str(entity_hints.get("producer") or "").strip()
        wine_name = str(entity_hints.get("wine_name") or entity_hints.get("full_wine_name") or "").strip()
        search_query = (query or "").strip()
        official_url = str(canonical_url or "").strip()
        handle = str(product_handle or "").strip()
        if not producer and not wine_name and not search_query and not official_url and not handle:
            return []
        conn = await db.get_conn()
        try:
            rows = await conn.fetch(
                """
                SELECT product_handle, product_title, producer, official_url, availability,
                       price_min, price_max, description_text, source_tier
                FROM official_product_profiles
                WHERE COALESCE(is_active, TRUE) = TRUE
                  AND (
                    ($1::text <> '' AND official_url = $1)
                    OR ($2::text <> '' AND product_handle = $2)
                    OR ($3::text <> '' AND producer ILIKE '%' || $3 || '%')
                    OR ($4::text <> '' AND product_title ILIKE '%' || $4 || '%')
                    OR ($5::text <> '' AND product_title ILIKE '%' || $5 || '%')
                  )
                ORDER BY last_seen_at DESC
                LIMIT $6
                """,
                official_url,
                handle,
                producer,
                wine_name,
                search_query,
                max(limit, 1),
            )
        finally:
            await conn.close()
        hits: List[Hit] = []
        for row in rows:
            row_dict = dict(row)
            hits.append(
                Hit(
                    id=str(row_dict.get("product_handle") or ""),
                    text=self._build_official_product_text(row_dict),
                    summary=str(row_dict.get("description_text") or "").strip()[:220],
                    meta={
                        "source_group": "official_site",
                        "source_kind": "official_site",
                        "source_tier": str(row_dict.get("source_tier") or "internal_official"),
                        "url": str(row_dict.get("official_url") or "").strip(),
                        "product_handle": str(row_dict.get("product_handle") or "").strip(),
                        "producer": str(row_dict.get("producer") or "").strip(),
                        "inventory_binding_proof": {
                            "type": "official_site",
                            "url": str(row_dict.get("official_url") or "").strip(),
                            "availability": row_dict.get("availability"),
                        },
                    },
                    source_type="official_site",
                    source_tier=str(row_dict.get("source_tier") or "internal_official"),
                )
            )
        return hits

    @staticmethod
    def _build_url_lookup_query_variants(
        query: str,
        entity_hints: Dict[str, Any],
        query_variants: Optional[List[str]],
    ) -> List[str]:
        normalized: List[str] = []
        for item in [query, *(query_variants or [])]:
            value = str(item or "").strip()
            if value and value not in normalized:
                normalized.append(value)
        producer = str(entity_hints.get("producer") or "").strip()
        wine_name = str(entity_hints.get("wine_name") or entity_hints.get("full_wine_name") or "").strip()
        vintage = str(entity_hints.get("vintage") or "").strip()
        if producer and wine_name:
            normalized.append(" ".join(part for part in [producer, wine_name, vintage] if part))
        if producer:
            normalized.append(producer)
        if wine_name:
            normalized.append(" ".join(part for part in [wine_name, vintage] if part))
        deduped: List[str] = []
        for item in normalized:
            if item and item not in deduped:
                deduped.append(item)
        return deduped[:4]

    @staticmethod
    def _resolve_url_lookup_availability_result(
        *,
        parse_status: str,
        exact_products: List[Dict[str, Any]],
        near_products: List[Dict[str, Any]],
        official_hits: List[Hit],
    ) -> str:
        if exact_products:
            return "exact_match"
        if near_products:
            return "near_match"
        if official_hits:
            return "not_sold"
        if parse_status == "failed":
            return "uncertain"
        return "not_sold"

    @classmethod
    def _url_lookup_to_official_hit(cls, url_lookup: Dict[str, Any]) -> Optional[Hit]:
        canonical_url = str(url_lookup.get("canonical_url") or "").strip()
        if not canonical_url:
            return None
        product_handle = str(url_lookup.get("product_handle") or "").strip()
        entity_hints = url_lookup.get("entity_hints") if isinstance(url_lookup.get("entity_hints"), dict) else {}
        producer = str(entity_hints.get("producer") or "").strip()
        wine_name = str(entity_hints.get("full_wine_name") or entity_hints.get("wine_name") or "").strip()
        title = str(url_lookup.get("page_title") or wine_name or product_handle).strip()
        meta_description = str(url_lookup.get("meta_description") or "").strip()
        if not title and not meta_description:
            return None
        source_tier = (
            "internal_official"
            if cls._extract_domain({"url": canonical_url}) in INTERNAL_OFFICIAL_DOMAINS
            else "external_evidence"
        )
        line = cls._build_official_product_text(
            {
                "product_title": wine_name or title,
                "producer": producer,
                "official_url": canonical_url,
                "product_handle": product_handle,
                "availability": None,
                "description_text": meta_description,
                "source_tier": source_tier,
            }
        )
        return Hit(
            id=product_handle or canonical_url,
            text=line,
            summary=meta_description[:220],
            meta={
                "source_group": "official_site",
                "source_kind": "official_site",
                "source_tier": source_tier,
                "url": canonical_url,
                "product_handle": product_handle,
                "producer": producer,
                "inventory_binding_proof": {
                    "type": "official_site",
                    "url": canonical_url,
                    "availability": None,
                },
            },
            source_type="official_site",
            source_tier=source_tier,
        )

    @staticmethod
    def _build_url_quote_followup_contract(
        *,
        query: str,
        effective_query: str,
        entity_hints: Dict[str, Any],
        availability_result: str,
        exact_products: List[Dict[str, Any]],
        near_products: List[Dict[str, Any]],
        url_lookup: Dict[str, Any],
    ) -> Dict[str, Any]:
        producer = str(entity_hints.get("producer") or "").strip()
        wine_name = str(entity_hints.get("wine_name") or entity_hints.get("full_wine_name") or "").strip()
        vintage = str(entity_hints.get("vintage") or "").strip()
        prompt_subject = " ".join(part for part in [producer, wine_name, vintage] if part).strip()
        prompt = f"幫我詢價這款酒：{prompt_subject}" if prompt_subject else f"幫我詢價這款酒：{effective_query or query}"
        if availability_result == "near_match":
            prompt = f"幫我詢價這款酒或相近款：{prompt_subject or effective_query or query}"
        return {
            "canonical_query": prompt_subject or effective_query or query,
            "base_query": prompt_subject or effective_query or query,
            "requested_filters": {
                key: value
                for key, value in {
                    "producer": producer or None,
                    "wine_name": wine_name or None,
                    "vintage": vintage or None,
                }.items()
                if value
            },
            "available_actions": ["pivot_to_quote_chat"],
            "pending_goal": "pivot_to_quote_chat",
            "default_confirm_action": "pivot_to_quote_chat",
            "surface_origin": "chat_url_product_lookup",
            "summary": "下一步：把這款酒帶到詢價頁，繼續確認報價、庫存或相近可售品項。",
            "action_definitions": {
                "pivot_to_quote_chat": {
                    "label": "查看相近可報價品項" if availability_result == "near_match" else "轉到詢價",
                    "prompt": prompt,
                    "preferred": True,
                }
            },
            "lookup_payload": {
                "producer": producer or None,
                "wine_name": wine_name or None,
                "vintage": vintage or None,
                "canonical_query": prompt_subject or effective_query or query,
                "canonical_url": str(url_lookup.get("canonical_url") or "").strip() or None,
                "product_handle": str(url_lookup.get("product_handle") or "").strip() or None,
                "availability_result": availability_result,
                "candidate_ids": [
                    str(item.get("no") or item.get("id") or "").strip()
                    for item in (exact_products[:3] or near_products[:3])
                    if str(item.get("no") or item.get("id") or "").strip()
                ],
            },
        }

    @staticmethod
    def _build_official_product_text(row: Dict[str, Any]) -> str:
        title = str(row.get("product_title") or "").strip()
        producer = str(row.get("producer") or "").strip()
        availability = row.get("availability")
        price_min = row.get("price_min")
        price_max = row.get("price_max")
        parts = [part for part in [producer, title] if part]
        detail_bits: List[str] = []
        if availability is not None:
            detail_bits.append(f"official availability: {'yes' if availability else 'no'}")
        if price_min is not None or price_max is not None:
            if price_min == price_max:
                detail_bits.append(f"official price: {price_min}")
            else:
                detail_bits.append(f"official price: {price_min or ''}-{price_max or ''}")
        line = " / ".join(parts)
        if detail_bits:
            line = f"{line} ({', '.join(detail_bits)})".strip()
        return line.strip()

    @staticmethod
    def _dedupe_hit_models(hits: List[Hit]) -> List[Hit]:
        deduped: List[Hit] = []
        seen: set[Tuple[Any, Any, Any, Any]] = set()
        for hit in hits:
            key = (hit.id, hit.document_id, hit.chunk_idx, (hit.meta or {}).get("url"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(hit)
        return deduped

    async def _run_rag_search(
        self,
        query: str,
        *,
        query_variants: Optional[List[str]],
        alias_filters: Optional[Dict[str, Any]],
        rag_k: int,
        prompt_category: Optional[str] = None,
        entity_hints: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not query:
            return []

        variants = self._normalize_query_variants(query, query_variants)
        tasks: List[asyncio.Task] = []
        contract_filters = self._build_source_contract_filters(
            query,
            prompt_category=prompt_category,
            entity_hints=entity_hints or {},
        )
        contract_only = bool(contract_filters)
        if contract_filters:
            tasks.append(
                asyncio.create_task(
                    self._run_source_contract_search_with_conn(contract_filters, k=max(rag_k, 8))
                )
            )
            if self._should_run_burghound_issue_resolver(query, contract_filters):
                tasks.append(
                    asyncio.create_task(
                        self._run_burghound_issue_resolver(query)
                    )
                )
        if prompt_category == "source_hierarchy_conflict" and ReviewConflictResolver.should_handle(query):
            tasks.append(asyncio.create_task(self._run_review_conflict_resolver(query)))
            contract_only = True
        if self._is_duplicate_record_query(query):
            tasks.append(asyncio.create_task(self._run_duplicate_record_resolver()))
            contract_only = True
        if not contract_only:
            tasks.extend([
                asyncio.create_task(
                    self._run_vector_search_with_conn(variant, k=self._variant_k(idx, rag_k))
                )
                for idx, variant in enumerate(variants)
            ])
        if alias_filters:
            tasks.append(asyncio.create_task(self._run_structured_search_with_conn(alias_filters)))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors: List[str] = []
        hits: List[Dict[str, Any]] = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(f"{type(result).__name__}: {result}")
                continue
            for hit in result or []:
                hits.append(hit)
        if errors:
            logger.warning("RAG retrieval degraded: %s", "; ".join(errors))
        return self._dedupe_hits(hits)

    @staticmethod
    def _should_run_burghound_issue_resolver(query: str, filters: Dict[str, Any]) -> bool:
        source_names = {
            str(item or "").strip()
            for item in (filters.get("source_names") or [])
            if str(item or "").strip()
        }
        return (
            str(filters.get("source_family") or "").strip() == "licensed_review_dataset"
            and ("burghound" in source_names or BurghoundIssueResolver.should_handle(query))
        )

    async def _run_burghound_issue_resolver(self, query: str) -> List[Dict[str, Any]]:
        evidence = await BurghoundIssueResolver().resolve(query)
        return [evidence.to_hit_dict()] if evidence else []

    async def _run_review_conflict_resolver(self, query: str) -> List[Dict[str, Any]]:
        evidence = await ReviewConflictResolver().resolve(query)
        return evidence.to_hit_dicts() if evidence else []

    @staticmethod
    def _is_duplicate_record_query(query: str) -> bool:
        lowered = str(query or "").casefold()
        return (
            ("duplicate" in lowered or "near-duplicate" in lowered)
            and ("record" in lowered or "review" in lowered or "source" in lowered)
        )

    async def _run_duplicate_record_resolver(self) -> List[Dict[str, Any]]:
        conn = await db.get_conn()
        try:
            rows = await conn.fetch(
                """
                WITH candidates AS (
                  SELECT
                    c.id,
                    c.document_id,
                    c.chunk_idx,
                    c.text,
                    c.summary,
                    c.keywords,
                    c.meta,
                    c.kg,
                    regexp_replace(lower(coalesce(c.meta->>'producer', '')), '[^a-z0-9]+', '', 'g') AS producer_key,
                    regexp_replace(lower(coalesce(NULLIF(c.meta->>'wine_name', ''), c.meta->>'full_wine_name', '')), '[^a-z0-9]+', '', 'g') AS wine_key,
                    coalesce(c.meta->>'vintage', '') AS vintage_key
                  FROM chunks c
                  WHERE c.meta->>'source_family' = 'licensed_review_dataset'
                    AND COALESCE(NULLIF(c.meta->>'is_garbled', '')::boolean, false) = false
                    AND coalesce(c.meta->>'producer', '') <> ''
                    AND coalesce(NULLIF(c.meta->>'wine_name', ''), c.meta->>'full_wine_name', '') <> ''
                    AND coalesce(c.meta->>'vintage', '') <> ''
                    AND coalesce(c.meta->>'source_trace', '') <> ''
                ),
                duplicate_keys AS (
                  SELECT producer_key, wine_key, vintage_key, count(*) AS duplicate_count
                  FROM candidates
                  WHERE producer_key <> '' AND wine_key <> '' AND vintage_key <> ''
                  GROUP BY producer_key, wine_key, vintage_key
                  HAVING count(*) > 1
                  ORDER BY count(*) DESC, producer_key, wine_key, vintage_key
                  LIMIT 3
                )
                SELECT c.id, c.document_id, c.chunk_idx, c.text, c.summary, c.keywords, c.meta, c.kg,
                       50.0::double precision AS score,
                       dk.duplicate_count,
                       c.producer_key,
                       c.wine_key,
                       c.vintage_key
                FROM candidates c
                JOIN duplicate_keys dk
                  ON c.producer_key = dk.producer_key
                 AND c.wine_key = dk.wine_key
                 AND c.vintage_key = dk.vintage_key
                ORDER BY dk.duplicate_count DESC, c.producer_key, c.wine_key, c.vintage_key,
                         coalesce(c.meta->>'source_name', ''), coalesce(c.meta->>'row_id', ''), c.id
                LIMIT 12
                """
            )
        finally:
            await conn.close()
        results: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            meta = dict(item.get("meta") or {})
            group_key = " | ".join(
                part
                for part in (
                    str(meta.get("producer") or "").strip(),
                    str(meta.get("wine_name") or meta.get("full_wine_name") or "").strip(),
                    str(meta.get("vintage") or "").strip(),
                )
                if part
            )
            meta.update(
                {
                    "duplicate_group_key": group_key,
                    "duplicate_group_count": int(item.get("duplicate_count") or 0),
                    "duplicate_resolution": "candidate_duplicate_group",
                    "merge_rationale": "Same normalized producer, wine name, and vintage; keep separate reviewer/source rows unless source, reviewer, issue/date, and record key also match.",
                    "doc_type": meta.get("doc_type") or "source_note",
                    "source_tier": meta.get("source_tier") or "internal_approved",
                }
            )
            item["meta"] = meta
            results.append(item)
        return results

    @classmethod
    def _build_source_contract_filters(
        cls,
        query: str,
        *,
        prompt_category: Optional[str],
        entity_hints: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        category = str(prompt_category or "").strip()
        if category not in LICENSED_REVIEW_CATEGORIES | BOOK_CONTRACT_CATEGORIES:
            return None
        return {
            "category": category,
            "source_family": (
                "licensed_review_dataset"
                if category in LICENSED_REVIEW_CATEGORIES
                else "ocr_book_corpus"
            ),
            "record_key": cls._source_contract_record_key(query),
            "terms": cls._source_contract_terms(query, entity_hints),
            "vintage": cls._source_contract_vintage(query, entity_hints),
            "source_names": cls._requested_review_source_names(query),
        }

    @staticmethod
    def _source_contract_record_key(query: str) -> Optional[str]:
        match = re.search(r"\brecord_key\s*=\s*([^;\n\r]+)", str(query or ""), flags=re.IGNORECASE)
        if not match:
            return None
        value = match.group(1).strip().strip("'\"")
        return value or None

    @staticmethod
    def _source_contract_vintage(query: str, entity_hints: Dict[str, Any]) -> Optional[str]:
        hint = str((entity_hints or {}).get("vintage") or "").strip()
        if re.fullmatch(r"(?:19|20)\d{2}", hint):
            return hint
        match = re.search(r"\b((?:19|20)\d{2})\b", str(query or ""))
        return match.group(1) if match else None

    @staticmethod
    def _requested_review_source_names(query: str) -> List[str]:
        lowered = str(query or "").lower()
        requested: List[str] = []
        mappings = [
            (("burghound",), "burghound"),
            (("jasper morris", "inside burgundy", "insideburgundy"), "inside_burgundy"),
            (("vinous",), "vinous"),
            (("wine advocate", "robert parker", "parker"), "wine_advocate"),
            (("wine spectator",), "wine_spectator"),
        ]
        for needles, source_name in mappings:
            if any(needle in lowered for needle in needles) and source_name not in requested:
                requested.append(source_name)
        return requested

    @classmethod
    def _hit_matches_requested_review_source(cls, hit: Hit, requested_sources: set[str]) -> bool:
        meta = hit.meta or {}
        source_candidates = [
            meta.get("source_site"),
            meta.get("source_name"),
            meta.get("reviewer"),
            meta.get("source_file"),
            meta.get("source_trace"),
        ]
        canonical = {
            cls._canonical_review_source_name(value)
            for value in source_candidates
            if str(value or "").strip()
        }
        return bool(canonical & requested_sources)

    @staticmethod
    def _canonical_review_source_name(value: Any) -> str:
        lowered = str(value or "").casefold()
        if "burghound" in lowered or "allen meadows" in lowered:
            return "burghound"
        if "jasper" in lowered or "inside burgundy" in lowered or "inside_burgundy" in lowered:
            return "inside_burgundy"
        if "vinous" in lowered:
            return "vinous"
        if "wine advocate" in lowered or "robert parker" in lowered or "parker" in lowered:
            return "wine_advocate"
        if "wine spectator" in lowered or "spectator" in lowered:
            return "wine_spectator"
        return lowered.strip()

    @staticmethod
    def _source_contract_terms(query: str, entity_hints: Dict[str, Any]) -> List[str]:
        stop_words = {
            "find", "include", "tasting", "note", "notes", "review", "reviews", "score", "scores",
            "rating", "ratings", "reviewer", "source", "sources", "issue", "date", "page", "cite",
            "exact", "compare", "across", "different", "what", "does", "say", "about", "wine",
            "wines", "ys", "domain", "grand", "premier", "cru", "the", "and", "with", "for",
            "from", "available", "internal", "rag", "only", "imported", "book", "corpus",
            "historical", "importance", "within", "answer", "using", "why", "considered",
            "important", "every", "factual", "claim", "show", "all", "have", "summarize",
            "summary", "consensus", "where", "reviewers", "agree", "disagree", "passage", "passages",
            "used", "red", "white", "still", "sparkling", "appellation", "style", "burghound", "jasper", "morris",
            "inside", "burgundy", "vinous", "advocate", "robert", "parker", "spectator",
        }
        parts = [str(query or "")]
        for key in ("producer", "wine_name", "full_wine_name", "vineyard", "region"):
            value = (entity_hints or {}).get(key)
            if value:
                parts.append(str(value))
        tokens: List[str] = []
        for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9'-]+", " ".join(parts)):
            cleaned = token.strip("'-").lower()
            token_parts = [part for part in re.split(r"[-']", cleaned) if part] if "-" in cleaned or "'" in cleaned else [cleaned]
            for part in token_parts:
                if not part or part in stop_words or part in {"st", "saint"}:
                    continue
                if re.fullmatch(r"(?:19|20)\d{2}", part):
                    continue
                if len(part) < 3:
                    continue
                if part not in tokens:
                    tokens.append(part)
        return tokens[:8]

    @staticmethod
    def _source_contract_term_variants(term: str) -> List[str]:
        base = str(term or "").strip()
        variants = [base] if base else []
        accent_map = {
            "tache": "tâche",
            "romanee": "romanée",
            "romanee-conti": "romanée-conti",
            "cote": "côte",
        }
        mapped = accent_map.get(base.lower())
        if mapped and mapped not in variants:
            variants.append(mapped)
        return variants

    async def _run_source_contract_search_with_conn(self, filters: Dict[str, Any], k: int) -> List[Dict[str, Any]]:
        conn = await db.get_conn()
        try:
            return await self._source_contract_search(conn, filters, k=k)
        finally:
            await conn.close()

    @staticmethod
    async def _source_contract_search(conn, filters: Dict[str, Any], k: int = 8) -> List[Dict[str, Any]]:
        source_family = str(filters.get("source_family") or "").strip()
        if source_family not in {"licensed_review_dataset", "ocr_book_corpus"}:
            return []
        terms = [
            str(term or "").strip()
            for term in (filters.get("terms") or [])
            if str(term or "").strip()
        ][:8]
        source_names = [
            str(item or "").strip()
            for item in (filters.get("source_names") or [])
            if str(item or "").strip()
        ]
        source_name_variants = RetrievalService._review_source_name_variants(source_names)
        record_key = str(filters.get("record_key") or "").strip()
        if record_key:
            terms = []
        clauses = ["COALESCE(NULLIF(c.meta->>'is_garbled', '')::boolean, false) = false"]
        vals: List[Any] = [source_family]
        clauses.append("c.meta->>'source_family' = $1")
        if source_family == "licensed_review_dataset":
            if record_key:
                vals.append(record_key)
                clauses.append(f"(c.meta->>'record_key' = ${len(vals)} OR c.meta->>'row_id' = ${len(vals)})")
            vintage = str(filters.get("vintage") or "").strip()
            if vintage:
                vals.append(vintage)
                clauses.append(f"c.meta->>'vintage' = ${len(vals)}")
            if source_name_variants:
                vals.append(source_name_variants)
                clauses.append(
                    f"(lower(coalesce(c.meta->>'source_name', '')) = ANY(${len(vals)}::text[]) "
                    f"OR lower(coalesce(c.meta->>'source_site', '')) = ANY(${len(vals)}::text[]) "
                    f"OR lower(c.meta::text) LIKE ANY(${len(vals)}::text[]))"
                )
        term_score_parts: List[str] = []
        for term in terms:
            variant_clauses: List[str] = []
            score_clauses: List[str] = []
            for variant in RetrievalService._source_contract_term_variants(term):
                vals.append(f"%{variant}%")
                idx = len(vals)
                variant_clauses.append(f"(c.text ILIKE ${idx} OR c.summary ILIKE ${idx} OR c.meta::text ILIKE ${idx})")
                score_clauses.append(f"c.meta::text ILIKE ${idx} OR c.text ILIKE ${idx}")
            if variant_clauses:
                clauses.append("(" + " OR ".join(variant_clauses) + ")")
                term_score_parts.append("CASE WHEN " + " OR ".join(score_clauses) + " THEN 1 ELSE 0 END")
        where = " AND ".join(clauses)
        term_score = " + ".join(term_score_parts) if term_score_parts else "CAST(0 AS double precision)"
        vals.append(max(k, 1))
        rows = await conn.fetch(
            f"""
            SELECT c.id, c.document_id, c.chunk_idx, c.text, c.summary, c.keywords, c.meta, c.kg,
                   ({term_score})::double precision AS score,
                   COALESCE(NULLIF(c.meta->>'content_quality', '')::double precision, 1.0) AS content_quality,
                   COALESCE(NULLIF(c.meta->>'encoding_quality', '')::double precision, 1.0) AS encoding_quality,
                   COALESCE(NULLIF(c.meta->>'is_garbled', '')::boolean, false) AS is_garbled
            FROM chunks c
            WHERE {where}
            ORDER BY ({term_score}) DESC,
                     COALESCE(NULLIF(c.meta->>'content_quality', '')::double precision, 1.0) DESC,
                     c.id ASC
            LIMIT ${len(vals)}
            """,
            *vals,
        )
        return [dict(row) for row in rows]

    @staticmethod
    def _review_source_name_variants(source_names: List[str]) -> List[str]:
        variants: List[str] = []
        mapping = {
            "burghound": ["burghound", "%burghound%", "%allen meadows%"],
            "inside_burgundy": ["inside_burgundy", "inside burgundy", "jasper morris", "%inside burgundy%", "%jasper morris%"],
            "vinous": ["vinous", "%vinous%"],
            "wine_advocate": ["wine_advocate", "wine advocate", "robert parker", "%wine advocate%", "%robert parker%", "%parker%"],
            "wine_spectator": ["wine_spectator", "wine spectator", "%wine spectator%"],
        }
        for name in source_names:
            for variant in mapping.get(name, [name]):
                normalized = str(variant or "").casefold()
                if normalized not in variants:
                    variants.append(normalized)
        return variants

    async def _run_vector_search_with_conn(self, query: str, k: int) -> List[Dict[str, Any]]:
        if not query:
            return []
        conn = await db.get_conn()
        try:
            return await _vector_search(conn, query, k=k)  # type: ignore
        finally:
            await conn.close()

    async def _run_structured_search_with_conn(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        structured_filters = {k: v for k, v in (filters or {}).items() if v}
        if not structured_filters:
            return []
        conn = await db.get_conn()
        try:
            return await _structured_search(conn, structured_filters, k=4)  # type: ignore
        finally:
            await conn.close()

    async def _run_cerp_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not query:
            return []
        if self._is_generic_inventory_listing_query(query):
            return await self._cerp_service.fetch_top_stock_products(
                limit=20,
                allow_zero_stock=False,
                raise_on_error=True,
            )
        plan = CerpQueryPlanner.plan(query)
        search_keyword = plan.sku or plan.search_keyword or query
        products = await self._cerp_service.search_products(
            search_keyword,
            limit=limit,
            quote_criteria=CerpQueryPlanner.quote_criteria(plan),
            raise_on_error=True,
        )
        filtered = CerpQueryPlanner.post_filter(products, plan)
        if not filtered and (plan.region or plan.color) and (plan.stock_min or plan.price_min is not None or plan.price_max is not None):
            relaxed_plan = replace(plan, region=None, color=None)
            relaxed = CerpQueryPlanner.post_filter(products, relaxed_plan)
            if relaxed:
                return relaxed
        if not filtered and (plan.stock_min or plan.price_min is not None or plan.price_max is not None or plan.region or plan.color):
            return []
        return filtered or products

    @staticmethod
    def _rag_hit_to_model(hit: Dict[str, Any]) -> Hit:
        meta = hit.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        for key in ("content_quality", "encoding_quality", "is_garbled"):
            if key in hit and key not in meta:
                meta[key] = hit.get(key)

        keywords = hit.get("keywords") or []
        if isinstance(keywords, str):
            try:
                keywords = json.loads(keywords)
            except Exception:
                keywords = []
        if not isinstance(keywords, list):
            keywords = []

        meta = normalize_source_metadata(meta)
        source_tier = RetrievalService._resolve_internal_source_tier(meta)
        meta["source_tier"] = source_tier
        meta.setdefault("source_trace", normalize_source_metadata(meta).get("source_trace"))
        return Hit(
            id=str(hit.get("id")) if hit.get("id") is not None else None,
            document_id=hit.get("document_id"),
            chunk_idx=hit.get("chunk_idx"),
            text=hit.get("text"),
            summary=hit.get("summary"),
            keywords=keywords,
            meta=meta,
            kg=hit.get("kg"),
            score=hit.get("score"),
            query_variant=hit.get("query_variant"),
            source_type=hit.get("source_type") or "rag",
            source_tier=source_tier,
        )

    @staticmethod
    def _normalize_query_variants(query: str, variants: Optional[List[str]]) -> List[str]:
        normalized: List[str] = []
        for item in variants or []:
            value = (item or "").strip()
            if value and value not in normalized:
                normalized.append(value)
        if query and query not in normalized:
            normalized.insert(0, query)
        return normalized

    @staticmethod
    def _variant_k(index: int, base_k: int) -> int:
        if index == 0:
            return max(base_k, 1)
        return max(3, base_k - index * 2)

    @staticmethod
    def _dedupe_hits(hits: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[Tuple[Any, Any, Any]] = set()
        unique: List[Dict[str, Any]] = []
        for hit in hits:
            key = (
                hit.get("id"),
                hit.get("document_id"),
                hit.get("chunk_idx"),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(hit)
        return unique

    @staticmethod
    def _cerp_product_to_hit(product: Dict[str, Any], *, match_type: Optional[str] = None) -> Optional[Hit]:
        if not isinstance(product, dict):
            return None
        code = product.get("no") or product.get("id")
        name = product.get("name") or product.get("name_en") or product.get("name_ch")
        producer = product.get("producer")
        vintage = product.get("vintage")
        stock = product.get("stock") or product.get("stock_qty")
        price = product.get("price")
        parts = [value for value in [producer, name, vintage] if value]
        line = " / ".join(str(value) for value in parts if value)
        detail_bits = []
        if stock is not None:
            detail_bits.append(f"stock: {stock}")
        if price is not None:
            detail_bits.append(f"price: {price}")
        if detail_bits:
            line = f"{line} ({', '.join(detail_bits)})"
        if not line:
            return None
        meta = {
            "source": "cerp",
            "code": code,
            "source_tier": "internal_primary",
            "source_family": "cerp_snapshot",
            "source_name": "CERP",
            "endpoint": "CERP ExportProduct/ExportProductsInfo",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": price,
            "stock": stock,
            "inventory_binding_proof": {
                "type": "cerp",
                "code": code,
                "stock": stock,
                "price": price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        plan = product.get("cerp_query_plan")
        if isinstance(plan, dict):
            meta["cerp_query_plan"] = plan
        if match_type:
            meta["match_type"] = match_type
        meta = normalize_source_metadata(meta)
        return Hit(
            id=str(code) if code is not None else None,
            text=line,
            meta=meta,
            source_type="cerp",
            source_tier="internal_primary",
        )

    @classmethod
    def _resolve_internal_source_tier(cls, meta: Dict[str, Any]) -> str:
        explicit = str(meta.get("source_tier") or "").strip()
        if explicit:
            if explicit == "internal_inventory":
                return "internal_primary"
            return explicit
        domain = cls._extract_domain(meta)
        if domain in INTERNAL_OFFICIAL_DOMAINS:
            return "internal_official"
        if domain in INTERNAL_PRIMARY_DOMAINS:
            return "internal_primary"
        searchable = cls._meta_search_text(meta)
        if cls._contains_any(searchable, INTERNAL_PRIMARY_KEYWORDS):
            return "internal_primary"
        if cls._contains_any(searchable, INTERNAL_APPROVED_KEYWORDS):
            return "internal_approved"
        return "internal"

    @staticmethod
    def _extract_domain(meta: Dict[str, Any]) -> str:
        for key in ("url", "source_url", "link", "website"):
            value = str(meta.get(key) or "").strip()
            if not value:
                continue
            parsed = urlparse(value if "://" in value else f"https://{value}")
            domain = parsed.netloc.lower().lstrip("www.")
            if domain:
                return domain
        return ""

    @staticmethod
    def _meta_search_text(meta: Dict[str, Any]) -> str:
        parts: List[str] = []
        for key in ("source", "filename", "title", "url", "source_url", "website", "domain", "category"):
            value = meta.get(key)
            if value:
                parts.append(str(value))
        return " ".join(parts).lower()

    @staticmethod
    def _contains_any(text: str, keywords: set[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    @classmethod
    def _build_official_inventory_binding(
        cls,
        *,
        query: str,
        prompt_category: Optional[str],
        source_policy: str,
        selected_hits: List[Hit],
        cerp_products: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        required = cls._requires_official_inventory_binding(
            query=query,
            prompt_category=prompt_category,
            source_policy=source_policy,
        )
        if prompt_category in CRITIC_LOOKUP_CATEGORIES:
            return {
                "required": False,
                "proof_count": 0,
                "selected_hit_count_before_filter": len(selected_hits),
                "selected_hit_count_after_filter": len(selected_hits),
                "proofs": [],
                "official_search_url": None,
            }
        proofs = [cls._inventory_binding_proof_from_hit(hit) for hit in selected_hits]
        proofs = [proof for proof in proofs if proof]
        if cerp_products:
            for product in cerp_products[:8]:
                code = str(product.get("no") or product.get("id") or "").strip()
                if not code:
                    continue
                proof = {
                    "type": "cerp",
                    "code": code,
                    "stock": product.get("stock") or product.get("stock_qty") or product.get("total_stock"),
                }
                if proof not in proofs:
                    proofs.append(proof)
        return {
            "required": required,
            "proof_count": len(proofs),
            "selected_hit_count_before_filter": len(selected_hits),
            "selected_hit_count_after_filter": len(selected_hits),
            "proofs": proofs[:8],
            "official_search_url": (
                f"https://ys.local/search?q={quote_plus(str(query or '').strip())}"
                if required and str(query or "").strip()
                else None
            ),
        }

    @classmethod
    def _requires_official_inventory_binding(
        cls,
        *,
        query: str,
        prompt_category: Optional[str],
        source_policy: str,
    ) -> bool:
        lowered = str(query or "").lower()
        official_scope_tokens = (
            "ys.local",
            "official site",
            "official website",
            "\u5b98\u7db2",
            "\u5b98\u65b9\u7db2\u7ad9",
            "\u921e\u592a",
            "\u53f0\u7063",
            "\u53f0\u5317",
            "taiwan",
            "taipei",
        )
        recommendation_tokens = (
            "recommend",
            "recommendation",
            "inventory",
            "stock",
            "\u63a8\u85a6",
            "\u5efa\u8b70",
            "\u5eab\u5b58",
            "\u73fe\u8ca8",
        )
        recommendation_category = prompt_category in {
            "quote_recommendation",
            "inventory_lookup",
            "url_product_lookup",
        }
        internal_required = str(source_policy or "").strip() == "internal_only"
        return bool(
            any(token in lowered for token in official_scope_tokens)
            and (
                recommendation_category
                or internal_required
                or any(token in lowered for token in recommendation_tokens)
            )
        )

    @classmethod
    def _hit_has_official_inventory_proof(cls, hit: Hit) -> bool:
        if cls._inventory_binding_proof_from_hit(hit):
            return True
        source_tier = str(hit.source_tier or (hit.meta or {}).get("source_tier") or "").strip()
        source_type = str(hit.source_type or "").strip()
        if source_tier in {"internal_official", "internal_primary", "internal_inventory"}:
            return True
        if source_type in {"cerp", "official_site"}:
            return True
        meta = hit.meta or {}
        if str(meta.get("source") or "").strip().lower() == "cerp":
            return True
        if str(meta.get("source_group") or "").strip() == "official_site":
            return True
        return cls._extract_domain(meta) in INTERNAL_OFFICIAL_DOMAINS

    @classmethod
    def _inventory_binding_proof_from_hit(cls, hit: Hit) -> Dict[str, Any]:
        meta = hit.meta or {}
        proof = meta.get("inventory_binding_proof")
        if isinstance(proof, dict) and proof:
            return dict(proof)
        source_type = str(hit.source_type or "").strip()
        source = str(meta.get("source") or "").strip().lower()
        if source_type == "cerp" or source == "cerp":
            code = str(meta.get("code") or hit.id or "").strip()
            return {"type": "cerp", "code": code} if code else {}
        if source_type == "official_site" or str(meta.get("source_group") or "").strip() == "official_site":
            url = str(meta.get("url") or "").strip()
            return {"type": "official_site", "url": url} if url else {"type": "official_site"}
        domain = cls._extract_domain(meta)
        if domain in INTERNAL_OFFICIAL_DOMAINS:
            return {"type": "official_site", "url": str(meta.get("url") or meta.get("source_url") or "").strip()}
        return {}

    def _determine_external_search_reason(
        self,
        internal_hits: List[Hit],
        *,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str],
        needs_authoritative_sources: bool,
        source_policy: str,
        requested_reason: Optional[str],
    ) -> Optional[str]:
        normalized_policy = (source_policy or "").strip()
        if normalized_policy == "internal_only":
            return None
        if prompt_category in LICENSED_REVIEW_CATEGORIES | BOOK_CONTRACT_CATEGORIES:
            return None
        if requested_reason:
            return requested_reason
        if normalized_policy == "authoritative_external_required":
            return "authoritative_required"
        if needs_authoritative_sources:
            return "authoritative_required"
        if prompt_category in AUTHORITATIVE_PROMPT_CATEGORIES and self._internal_coverage_is_low(
            internal_hits,
            entity_hints=entity_hints,
        ):
            return "low_internal_coverage"
        if prompt_category == "brand_profile" and self._internal_coverage_is_low(
            internal_hits,
            entity_hints=entity_hints,
            prompt_category=prompt_category,
        ):
            return "low_internal_coverage"
        return None

    def _internal_coverage_is_low(
        self,
        internal_hits: List[Hit],
        *,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str] = None,
    ) -> bool:
        candidate_hits = list(internal_hits or [])
        if prompt_category == "brand_profile":
            candidate_hits = [
                hit for hit in candidate_hits
                if not self._is_low_content_brand_profile_hit(hit)
            ]
        top_hits = candidate_hits[:4]
        if len(top_hits) < 3:
            return True
        producer_hint = self._normalize_hint(entity_hints.get("producer"))
        region_hint = self._normalize_hint(entity_hints.get("region"))
        if prompt_category == "brand_profile" and not producer_hint:
            return True
        if producer_hint and not any(self._hit_mentions(hit, producer_hint) for hit in top_hits):
            return True
        if region_hint and not any(self._hit_mentions(hit, region_hint, region_mode=True) for hit in top_hits):
            return True
        return False

    @staticmethod
    def _should_short_circuit_general_low_coverage(
        *,
        prompt_category: Optional[str],
        internal_coverage_low: bool,
        entity_hints: Dict[str, Any],
        external_search_reason: Optional[str],
    ) -> bool:
        if prompt_category != "general_chat":
            return False
        if not internal_coverage_low:
            return False
        if external_search_reason:
            return False
        producer_hint = RetrievalService._normalize_hint(entity_hints.get("producer"))
        return bool(producer_hint)

    @staticmethod
    def _select_hits(
        internal_hits: List[Hit],
        external_hits: List[Hit],
        *,
        prompt_category: Optional[str],
        external_search_reason: Optional[str],
        needs_authoritative_sources: bool,
        fail_closed_selection: bool,
    ) -> List[Hit]:
        if fail_closed_selection:
            return []
        internal_sorted = sorted(
            internal_hits,
            key=lambda hit: (source_priority(hit.meta, hit.source_type, hit.source_tier), -RetrievalService._hit_score(hit)),
        )
        external_sorted = list(external_hits)
        prefer_external = bool(
            external_sorted and (
                needs_authoritative_sources
                or prompt_category in AUTHORITATIVE_PROMPT_CATEGORIES
                or external_search_reason in {
                    "authoritative_required",
                    "source_validation",
                    "latest_info",
                    "manual_override",
                    "low_internal_coverage",
                }
            )
        )
        if prefer_external:
            selected = external_sorted[:4] + internal_sorted[:4]
        else:
            selected = internal_sorted[:8]
            if len(selected) < 5:
                selected.extend(external_sorted[: max(0, 5 - len(selected))])

        deduped: List[Hit] = []
        seen: set[Tuple[Any, Any, Any, Any]] = set()
        for hit in selected:
            key = (hit.id, hit.document_id, hit.chunk_idx, (hit.meta or {}).get("url"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(hit)
        return deduped

    def _apply_profile_policy(
        self,
        hits: List[Hit],
        *,
        prompt_category: Optional[str],
        behavior_profile: Dict[str, Any],
        entity_hints: Dict[str, Any],
        context_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Hit], Dict[str, Any]]:
        profile_name = str(prompt_category or "general_chat")
        context_state = context_state or {}
        entity_hints = self._merge_context_entity_hints(entity_hints or {}, context_state)
        required_doc_types = [
            str(item).strip()
            for item in (behavior_profile or {}).get("required_doc_types", [])
            if str(item).strip()
        ]
        blocked_doc_types = [
            str(item).strip()
            for item in (behavior_profile or {}).get("blocked_doc_types", [])
            if str(item).strip()
        ]
        priority = [
            str(item).strip()
            for item in (behavior_profile or {}).get("retrieval_priority", [])
            if str(item).strip()
        ]
        decision: Dict[str, Any] = {
            "profile": profile_name,
            "source_policy": behavior_profile.get("source_policy"),
            "retrieval_priority": priority,
            "required_doc_types": required_doc_types,
            "blocked_doc_types": blocked_doc_types,
            "citation_rule": behavior_profile.get("citation_rule"),
            "input_hit_count": len(hits or []),
            "context_used": bool((context_state or {}).get("resolved")),
            "context_followup_type": (context_state or {}).get("followup_type"),
            "context_protected_entities": (context_state or {}).get("protected_entities") or {},
            "rejected_reasons": [],
            "hit_scores": [],
        }
        if not hits:
            decision["selected_hit_count_after_policy"] = 0
            return [], decision

        strict_entity_categories = {"vineyard_lookup", "tasting_note_generation"}
        strict_doc_categories = {"vineyard_lookup", "tasting_note_generation"}
        strict_page_quality_categories = {"vineyard_lookup", "tasting_note_generation"}
        ranked: List[Tuple[float, Hit]] = []
        for hit in hits:
            reasons = self._profile_rejection_reasons(
                hit,
                prompt_category=profile_name,
                required_doc_types=required_doc_types,
                blocked_doc_types=blocked_doc_types,
                entity_hints=entity_hints,
            )
            base_score = self._hit_score(hit)
            entity_exact_match = self._profile_entity_exact_match(hit, entity_hints)
            document_type_match = self._hit_matches_doc_types(hit, required_doc_types) if required_doc_types else True
            profile_boost = self._profile_boost(
                hit,
                required_doc_types=required_doc_types,
                priority=priority,
                document_type_match=document_type_match,
            )
            total_score = base_score + profile_boost + (0.25 if entity_exact_match else 0.0)
            hit_id = hit.id or f"{hit.document_id}:{hit.chunk_idx}"
            meta = hit.meta or {}
            decision["hit_scores"].append(
                {
                    "id": hit_id,
                    "label": str(
                        meta.get("title")
                        or meta.get("filename")
                        or meta.get("source_title")
                        or hit_id
                    ).strip(),
                    "base_score": base_score,
                    "profile_boost": round(profile_boost, 3),
                    "score_breakdown": score_breakdown(
                        hit,
                        base_score=base_score,
                        source_priority_boost_value=profile_boost,
                        entity_exact_match=entity_exact_match,
                        document_type_match=document_type_match,
                        context_state=context_state,
                    ),
                    "entity_exact_match": entity_exact_match,
                    "document_type_match": document_type_match,
                    "source_tier": hit.source_tier or (hit.meta or {}).get("source_tier"),
                    "rejected_reasons": reasons,
                }
            )
            reject = bool(reasons)
            if profile_name in strict_entity_categories and "page_entity_missing" in reasons:
                reject = True
            elif profile_name in strict_doc_categories and "wrong_doc_type" in reasons:
                reject = True
            elif profile_name in strict_page_quality_categories and set(reasons) & {
                "image_only_page",
                "toc_or_index_page",
                "wrong_subject_book_section",
            }:
                reject = True
            else:
                reject = bool(set(reasons) & {"blocked_doc_type", "low_content_internal_page"})
            decision["hit_scores"][-1]["rejected"] = reject
            if reject:
                for reason in reasons:
                    if reason not in decision["rejected_reasons"]:
                        decision["rejected_reasons"].append(reason)
                continue
            ranked.append((total_score, hit))

        if not ranked and profile_name in {"tasting_note_generation", "vineyard_lookup"}:
            decision["rejected_reasons"].append("no_profile_qualified_hits")
            decision["selected_hit_count_after_policy"] = 0
            return [], decision

        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = [hit for _, hit in ranked] if ranked else hits
        decision["selected_hit_count_after_policy"] = len(selected)
        return selected, decision

    def _profile_rejection_reasons(
        self,
        hit: Hit,
        *,
        prompt_category: str,
        required_doc_types: List[str],
        blocked_doc_types: List[str],
        entity_hints: Dict[str, Any],
    ) -> List[str]:
        reasons: List[str] = []
        if blocked_doc_types and self._hit_matches_doc_types(hit, blocked_doc_types):
            reasons.append("blocked_doc_type")
        if required_doc_types and not self._hit_matches_doc_types(hit, required_doc_types):
            reasons.append("wrong_doc_type")
        if prompt_category in {"vineyard_lookup", "tasting_note_generation"}:
            producer_hint = self._normalize_hint((entity_hints or {}).get("producer"))
            vineyard_hint = self._normalize_hint(
                (entity_hints or {}).get("vineyard")
                or (entity_hints or {}).get("climat")
                or (entity_hints or {}).get("wine_name")
            )
            region_hint = self._normalize_hint((entity_hints or {}).get("region"))
            required_hint = vineyard_hint or producer_hint or region_hint
            if required_hint and not self._hit_mentions(hit, required_hint, region_mode=required_hint in {"burgundy", "champagne"}):
                reasons.append("page_entity_missing")
            if self._hit_is_image_only_page(hit):
                reasons.append("image_only_page")
            if self._hit_is_toc_or_index_page(hit):
                reasons.append("toc_or_index_page")
            if self._hit_is_wrong_subject_book_section(
                hit,
                prompt_category=prompt_category,
                entity_hints=entity_hints,
            ):
                reasons.append("wrong_subject_book_section")
        elif prompt_category == "brand_profile" and self._is_low_content_brand_profile_hit(hit):
            reasons.append("low_content_internal_page")
        return reasons

    def _profile_boost(
        self,
        hit: Hit,
        *,
        required_doc_types: List[str],
        priority: List[str],
        document_type_match: bool,
    ) -> float:
        boost, _details = source_priority_boost(
            hit,
            priority=priority,
            required_doc_type_match=bool(required_doc_types and document_type_match),
        )
        return boost

    def _profile_entity_exact_match(self, hit: Hit, entity_hints: Dict[str, Any]) -> bool:
        for key in ("producer", "vineyard", "climat", "wine_name", "region"):
            hint = self._normalize_hint((entity_hints or {}).get(key))
            if hint and self._hit_mentions(hit, hint, region_mode=hint in {"burgundy", "champagne"}):
                return True
        return False

    def _hit_matches_doc_types(self, hit: Hit, doc_types: List[str]) -> bool:
        if not doc_types:
            return False
        search_text = self._hit_search_text(hit)
        aliases = {
            "tasting_note": {"tasting note", "tasting_note", "full_tasting_note", "品飲", "試飲", "香氣", "口感"},
            "critic": {"critic", "wine advocate", "jasper", "burghound", "vinous", "decanter", "score", "rating", "酒評"},
            "review": {"review", "rating", "score", "評論", "評分"},
            "producer_note": {"producer note", "producer_note", "酒莊筆記"},
            "source_notes": {"source_notes", "source note", "source_notes"},
            "source_note": {"source_note", "source notes", "source note"},
            "vineyard": {"vineyard", "clos", "climat", "lieu-dit", "lieu dit", "葡萄園"},
            "terroir": {"terroir", "soil", "風土", "土壤"},
            "climat": {"climat", "clos", "lieu-dit", "lieu dit"},
            "lieu_dit": {"lieu-dit", "lieu dit"},
            "vintage_overview": {"vintage overview", "vintage_region_overview", "vintage characteristics"},
            "inventory_only": {"inventory only", "stock only"},
            "inventory": {"inventory", "stock", "cerp", "庫存", "現貨"},
            "stock": {"stock", "inventory", "庫存", "現貨"},
            "product": {"product", "sku", "wine_name", "full_wine_name", "商品", "品項"},
            "official": {"official", "official_site", "ys.local", "官網", "官方"},
            "website": {"website", "url", "official site", "官網", "網址"},
            "source": {"source", "citation", "reference", "來源", "引用"},
            "citation": {"citation", "reference", "source", "引用"},
            "reference": {"reference", "source", "citation", "參考"},
            "profile": {"profile", "background", "history", "producer", "酒莊", "背景"},
            "producer": {"producer", "winery", "estate", "ys", "酒莊"},
            "background": {"background", "history", "story", "背景", "歷史"},
            "winemaking": {"winemaking", "釀造"},
            "region": {"region", "village", "產區", "村莊"},
            "vintage": {"vintage", "年份"},
            "overview": {"overview", "summary", "概覽"},
            "portfolio": {"portfolio", "ys.local", "cerp", "鈞太"},
            "internal_approved": {"rap", "internal_approved"},
            "external_unverified": {"external_unverified", "tier 3"},
            "generic_profile": {"generic profile"},
        }
        for doc_type in doc_types:
            normalized = str(doc_type or "").strip().lower()
            candidates = aliases.get(normalized, {normalized})
            if any(candidate and candidate in search_text for candidate in candidates):
                return True
        return False

    def _hit_search_text(self, hit: Hit) -> str:
        meta = hit.meta or {}
        return " ".join(
            filter(
                None,
                [
                    str(hit.text or ""),
                    str(hit.summary or ""),
                    " ".join(str(item) for item in (hit.keywords or [])),
                    self._meta_to_text(meta),
                    str(hit.source_type or ""),
                    str(hit.source_tier or ""),
                ],
            )
        ).lower()

    def _hit_is_image_only_page(self, hit: Hit) -> bool:
        meta = hit.meta or {}
        page_type = str(meta.get("content_type") or meta.get("page_type") or meta.get("doc_type") or "").lower()
        if page_type in {"image", "image_only", "scan_only"}:
            return True
        text = " ".join([str(hit.text or "").strip(), str(hit.summary or "").strip()]).strip()
        if len(text) >= 80:
            return False
        lowered = self._hit_search_text(hit)
        return any(token in lowered for token in {"image only", "scan only", "photo page", "full page image"})

    def _hit_is_toc_or_index_page(self, hit: Hit) -> bool:
        lowered = self._hit_search_text(hit)
        title = str((hit.meta or {}).get("title") or "").lower()
        tokens = {"table of contents", "contents", "index", "appendix", "chapter list"}
        if any(token in title for token in tokens):
            return True
        return any(token in lowered for token in tokens) and len(str(hit.text or "").strip()) < 240

    def _is_low_content_brand_profile_hit(self, hit: Hit) -> bool:
        meta = hit.meta or {}
        tier = str(hit.source_tier or meta.get("source_tier") or "").strip().lower()
        source_type = str(hit.source_type or meta.get("source_type") or "").strip().lower()
        if tier in {"internal_approved", "internal_official", "internal_primary"}:
            return False
        if source_type in {"official_site", "cerp"}:
            return False
        if self._hit_is_image_only_page(hit) or self._hit_is_toc_or_index_page(hit):
            return True

        density_keys = ("content_density", "text_density", "body_text_density")
        for key in density_keys:
            raw = meta.get(key)
            if raw in (None, ""):
                continue
            try:
                if float(raw) <= 0.05:
                    return True
            except (TypeError, ValueError):
                continue

        length_keys = ("body_text_length", "text_length", "content_length")
        for key in length_keys:
            raw = meta.get(key)
            if raw in (None, ""):
                continue
            try:
                if int(raw) < 80:
                    return True
            except (TypeError, ValueError):
                continue

        return False

    def _hit_is_wrong_subject_book_section(
        self,
        hit: Hit,
        *,
        prompt_category: str,
        entity_hints: Dict[str, Any],
    ) -> bool:
        lowered = self._hit_search_text(hit)
        doc_type = str((hit.meta or {}).get("doc_type") or "").lower()
        if prompt_category == "vineyard_lookup" and "vintage_overview" in doc_type:
            return True
        target_region = self._normalize_hint((entity_hints or {}).get("region"))
        if target_region and target_region not in {"burgundy", "champagne"} and target_region not in lowered:
            known_regions = {"vosne", "gevrey", "marsannay", "fixin", "meursault", "puligny", "chambolle"}
            if any(region in lowered for region in known_regions):
                return True
        return False

    @classmethod
    def _should_fail_closed_selection(
        cls,
        *,
        prompt_category: Optional[str],
        needs_authoritative_sources: bool,
        external_search: Dict[str, Any],
        external_hits: List[Hit],
        internal_coverage_low: bool,
    ) -> bool:
        authoritative_query = bool(
            needs_authoritative_sources
            or prompt_category in AUTHORITATIVE_PROMPT_CATEGORIES
        )
        if not authoritative_query:
            return False
        if prompt_category in LICENSED_REVIEW_CATEGORIES | BOOK_CONTRACT_CATEGORIES:
            return False
        authoritative_hit_count = 0
        try:
            authoritative_hit_count = int((external_search or {}).get("authoritative_hit_count") or 0)
        except (TypeError, ValueError):
            authoritative_hit_count = 0
        authoritative_hit_count = max(authoritative_hit_count, cls._count_authoritative_hits(external_hits))
        if authoritative_hit_count > 0:
            return False
        termination_reason = str((external_search or {}).get("termination_reason") or "").strip()
        if termination_reason in {
            "provider_timeout",
            "budget_exhausted",
            "provider_error",
            "request_deadline_exceeded",
        }:
            return True
        if bool((external_search or {}).get("attempted")) and internal_coverage_low:
            return True
        return authoritative_query and internal_coverage_low

    @staticmethod
    def _count_authoritative_hits(hits: List[Hit]) -> int:
        count = 0
        for hit in hits:
            tier = str(hit.source_tier or (hit.meta or {}).get("source_tier") or "").strip()
            if tier in AUTHORITATIVE_SOURCE_TIERS:
                count += 1
        return count

    @staticmethod
    def _collect_source_tiers(hits: List[Hit]) -> Dict[str, str]:
        tiers: Dict[str, str] = {}
        for hit in hits:
            key = hit.id or str(hit.document_id or "")
            if key:
                tiers[key] = hit.source_tier or str((hit.meta or {}).get("source_tier") or "")
        return tiers

    @staticmethod
    def _hit_score(hit: Hit) -> float:
        try:
            return float(hit.score) if hit.score is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalize_hint(value: Any) -> Optional[str]:
        if isinstance(value, list):
            for item in value:
                normalized = RetrievalService._normalize_hint(item)
                if normalized:
                    return normalized
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "bourgogne":
                return "burgundy"
            return normalized or None
        return None

    def _hit_mentions(self, hit: Hit, hint: str, *, region_mode: bool = False) -> bool:
        meta = hit.meta or {}
        haystack = " ".join(
            filter(
                None,
                [
                    str(hit.text or ""),
                    str(hit.summary or ""),
                    self._meta_to_text(meta),
                ],
            )
        ).lower()
        if not haystack:
            return False
        candidates = [hint]
        if region_mode and hint == "burgundy":
            candidates.append("bourgogne")
        return any(candidate in haystack for candidate in candidates)

    def _meta_to_text(self, value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(self._meta_to_text(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return " ".join(self._meta_to_text(item) for item in value)
        return str(value or "")
