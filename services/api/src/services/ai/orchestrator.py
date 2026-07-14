import logging
import os
import re
import uuid
import time
import types
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ...core import db
from ...core.chat_history import add_message_to_conversation, get_messages_by_conversation
from ...core.i18n import t
from ...schemas.ai import ChatResponse
from .analysis import AnalysisService
from .claim_validation import ClaimValidationService
from .generation import GenerationService
from .grounding import GroundingService
from .response_summary import ResponseSummaryService
from ...core.model_lane import resolve_model_config
from .retrieval import RetrievalService
try:
    from .context_core import ContextCoreService
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    class ContextCoreService:  # type: ignore
        async def build(self, **kwargs):
            behavior_profile = kwargs.get("behavior_profile") or {}
            query = kwargs.get("query") or ""
            return {
                "context_state": {
                    "resolved": False,
                    "current_user_goal": query,
                    "recent_summary": [],
                    "recent_summary_used": False,
                    "active_topic": {},
                    "followup_type": "new_question",
                    "protected_entities": {},
                    "topic_shift_detected": False,
                    "project_profile": {},
                    "project_profile_used": False,
                    "related_conversation_summaries": [],
                    "related_conversation_count": 0,
                    "behavior_profile": behavior_profile,
                    "source_policy": behavior_profile.get("source_policy"),
                    "citation_rule": behavior_profile.get("citation_rule"),
                },
                "context_package": {"sections": [], "text": ""},
            }

try:
    from .behavior_profiles import get_behavior_profile
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    def get_behavior_profile(prompt_category: Optional[str]) -> Dict[str, Any]:
        category = str(prompt_category or "").strip()
        if category in {"source_validation", "critic_score_lookup", "terroir_comparison", "url_product_lookup"}:
            return {"source_policy": "authoritative_external_required"}
        if category == "quote_recommendation":
            return {"source_policy": "internal_only"}
        return {"source_policy": "internal_preferred"}

try:
    from .answer_route_policy import build_answer_route_policy
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    def build_answer_route_policy(**kwargs) -> Dict[str, Any]:
        prompt_category = str(kwargs.get("prompt_category") or "general_chat").strip()
        return {
            "route": prompt_category,
            "intent": str(kwargs.get("intent_name") or "FREE_CHAT"),
            "evidence_type": ChatOrchestrator._evidence_type_for_prompt_category(prompt_category) if "ChatOrchestrator" in globals() else "grounded_answer",
            "source_policy": kwargs.get("source_policy") or "internal_preferred",
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
CERP_RESULT_PROMPT_CATEGORIES = {
    "quote_recommendation",
    "inventory_lookup",
    "url_product_lookup",
    "image_product_lookup",
    "alias_inventory_equivalence",
    "source_hierarchy_conflict",
}
CERP_RESULT_INTENTS = {"QUOTE_LIST"}
CERP_EXPLICIT_LOOKUP_RE = re.compile(
    r"\b(?:cerp|stock|inventory|availability|quote|quotation)\b|庫存|現貨|有貨|缺貨|報價|詢價",
    re.IGNORECASE,
)


def _normalize_conversation_uuid(conversation_id: Optional[str]) -> Optional[uuid.UUID]:
    if not conversation_id:
        return None
    try:
        return uuid.UUID(str(conversation_id))
    except (ValueError, TypeError, AttributeError):
        return None


class ChatOrchestrator:
    def __init__(
        self,
        analysis_service: Optional[AnalysisService] = None,
        retrieval_service: Optional[RetrievalService] = None,
        generation_service: Optional[GenerationService] = None,
        grounding_service: Optional[GroundingService] = None,
        context_core_service: Optional[ContextCoreService] = None,
        claim_validation_service: Optional[ClaimValidationService] = None,
        response_summary_service: Optional[ResponseSummaryService] = None,
    ) -> None:
        self._analysis_service = analysis_service or AnalysisService()
        self._retrieval_service = retrieval_service or RetrievalService()
        self._generation_service = generation_service or GenerationService()
        self._grounding_service = grounding_service or GroundingService()
        self._context_core_service = context_core_service or ContextCoreService()
        self._claim_validation_service = claim_validation_service or ClaimValidationService()
        self._response_summary_service = response_summary_service or ResponseSummaryService()
        self._authoritative_request_deadline_seconds = self._get_float_env(
            "AUTHORITATIVE_REQUEST_DEADLINE_SECONDS",
            60.0,
        )
        self._general_request_deadline_seconds = self._get_float_env(
            "GENERAL_REQUEST_DEADLINE_SECONDS",
            45.0,
        )
        model_config = resolve_model_config(default_base_model="gpt-5.4-mini")
        self._chat_model = str(model_config["primary_model"])
        self._external_search_model = (
            os.getenv("OPENAI_WEB_SEARCH_MODEL", "").strip()
            or os.getenv("OPENAI_FALLBACK_CHAT_MODEL", "").strip()
            or self._chat_model
        )

    async def chat(
        self,
        query: str,
        *,
        conversation_id: Optional[str] = None,
        analysis_weight: float = 0.0,
        compact: bool = False,
        user_id: Optional[int] = None,
        project_context: Optional[Dict[str, Any]] = None,
        history_cutoff=None,
        store_profile: Optional[Dict[str, Any]] = None,
        language: Optional[str] = None,
        attachment: Optional[Dict[str, Any]] = None,
        prior_attachment_context: Optional[Dict[str, Any]] = None,
        url_inputs: Optional[list[str]] = None,
        source_policy: Optional[str] = None,
        needs_authoritative_sources: Optional[bool] = None,
        prompt_category_override: Optional[str] = None,
        authoritative_reason_override: Optional[str] = None,
        benchmark_trace: bool = False,
        request_deadline_seconds: Optional[float] = None,
    ) -> ChatResponse:
        conn = None
        try:
            total_started = time.perf_counter()
            conn = await db.get_conn()
            request_started_at = time.monotonic()
            analysis_started = time.perf_counter()
            analysis = await self._analysis_service.analyze(
                query,
                conn=conn,
                attachment=attachment,
                prior_attachment_context=prior_attachment_context,
                url_inputs=url_inputs,
            )
            followup_context = await self._resolve_followup_context(
                query=query,
                conversation_id=conversation_id,
            )
            if followup_context.get("resolved"):
                prior_hints = (
                    followup_context.get("entity_hints")
                    if isinstance(followup_context.get("entity_hints"), dict)
                    else {}
                )
                merged_hints, merge_policy, protected_hints = self._merge_followup_entity_hints(
                    query,
                    analysis.entity_hints,
                    prior_hints,
                )
                analysis.entity_hints = merged_hints
                followup_context["entity_hints"] = merged_hints
                followup_context["merge_policy"] = merge_policy
                followup_context["protected_entity_hints"] = protected_hints
                analysis.followup_context = followup_context
                if (
                    analysis.prompt_category == "general_chat"
                    and str(followup_context.get("prompt_category") or "").strip()
                ):
                    analysis.prompt_category = str(followup_context.get("prompt_category")).strip()
                if not analysis.retrieval_query:
                    analysis.retrieval_query = self._build_followup_retrieval_query(query, merged_hints)
            analysis_ms = round((time.perf_counter() - analysis_started) * 1000, 1)
            effective_prompt_category = prompt_category_override or analysis.prompt_category
            if effective_prompt_category in {"critic_score_lookup", "source_validation"} and analysis.intent.name == "QUOTE_LIST":
                analysis.intent.name = "ASK_ALCOHOL_INFO"
            producer_hint = str(analysis.entity_hints.get("producer") or "").strip() or None
            if AnalysisService._should_force_brand_profile(
                query,
                base_category=effective_prompt_category or "general_chat",
                inferred_producer=producer_hint,
            ):
                effective_prompt_category = "brand_profile"
            analysis.prompt_category = effective_prompt_category
            behavior_profile = get_behavior_profile(effective_prompt_category)
            profile_source_policy = str(behavior_profile.get("source_policy") or "").strip() or None
            context_core = await self._context_core_service.build(
                query=query,
                conversation_id=conversation_id,
                project_context=project_context,
                behavior_profile=behavior_profile,
                analysis=analysis,
                user_id=user_id,
                followup_context=analysis.followup_context,
            )
            context_state = context_core.get("context_state") if isinstance(context_core.get("context_state"), dict) else {}
            context_package = context_core.get("context_package") if isinstance(context_core.get("context_package"), dict) else {}

            explicit_authoritative_override = needs_authoritative_sources is True and not analysis.needs_authoritative_sources
            resolved_authoritative = (
                analysis.needs_authoritative_sources
                if needs_authoritative_sources is None
                else bool(needs_authoritative_sources)
            )
            if str(source_policy or "").strip() == "authoritative_external_required":
                resolved_authoritative = True
            resolved_source_policy = source_policy or profile_source_policy or (
                "authoritative_external_required" if resolved_authoritative else "internal_preferred"
            )
            resolved_external_search_reason = (
                "manual_override"
                if explicit_authoritative_override
                else (authoritative_reason_override or analysis.authoritative_reason)
            )
            if (
                str(resolved_source_policy or "").strip() == "authoritative_external_required"
                and not resolved_external_search_reason
            ):
                resolved_external_search_reason = "authoritative_required"
            route_policy = build_answer_route_policy(
                prompt_category=effective_prompt_category,
                intent_name=analysis.intent.name,
                entity_hints=analysis.entity_hints,
                context_state=context_state,
                behavior_profile=behavior_profile,
                source_policy=resolved_source_policy,
                needs_authoritative_sources=resolved_authoritative,
            )
            if self._is_source_followup_query(query) and followup_context.get("source_references"):
                effective_prompt_category = "source_validation"
                analysis.prompt_category = "source_validation"
                resolved_authoritative = True
                if not source_policy:
                    resolved_source_policy = "authoritative_external_required"
                source_answer = self._build_previous_source_followup_answer(
                    query=query,
                    followup_context=followup_context,
                    language=language,
                    source_policy=resolved_source_policy,
                    prompt_category=effective_prompt_category,
                    analysis_ms=analysis_ms,
                )
                source_metadata = source_answer.get("metadata") if isinstance(source_answer.get("metadata"), dict) else {}
                source_metadata.setdefault("context_state", context_state)
                source_metadata.setdefault("context_package", context_package)
                if isinstance(source_metadata.get("retrieval_snapshot"), dict):
                    source_metadata["retrieval_snapshot"].setdefault("context_state", context_state)
                    source_metadata["retrieval_snapshot"].setdefault(
                        "retrieval_decision",
                        {
                            "context_used": bool(context_state.get("resolved")),
                            "context_followup_type": context_state.get("followup_type"),
                            "context_protected_entities": context_state.get("protected_entities") or {},
                            "rejected_reasons": [],
                        },
                    )
                source_answer["metadata"] = source_metadata
                source_answer = await self._ensure_message_persisted(
                    query=query,
                    answer=source_answer,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    project_context=project_context,
                )
                return ChatResponse(
                    intent=analysis.intent,
                    answer=source_answer,
                    context=[],
                    content=str(source_answer.get("text") or ""),
                    language=language,
                    project=project_context,
                    store=store_profile,
                )
            authoritative_query = bool(
                resolved_authoritative
                or effective_prompt_category in AUTHORITATIVE_PROMPT_CATEGORIES
                or resolved_external_search_reason in {
                    "authoritative_required",
                    "source_validation",
                    "latest_info",
                    "manual_override",
                    "low_internal_coverage",
                }
            )
            request_deadline_at = (
                request_started_at
                + (float(request_deadline_seconds) if request_deadline_seconds is not None else (
                    self._authoritative_request_deadline_seconds
                    if authoritative_query
                    else self._general_request_deadline_seconds
                ))
            )
            retrieval_started = time.perf_counter()
            request_deadline_exceeded = time.monotonic() >= request_deadline_at
            if request_deadline_exceeded:
                response_mode = "templated_fail_closed" if authoritative_query else "templated_general_timeout"
                retrieval = self._build_timeout_retrieval_result(
                    query=analysis.retrieval_query or query,
                    prompt_category=effective_prompt_category,
                    needs_authoritative_sources=resolved_authoritative,
                    source_policy=resolved_source_policy,
                    external_search_reason=resolved_external_search_reason,
                    response_mode=response_mode,
                    attachment_context=analysis.attachment_context,
                    route_policy=route_policy,
                )
            else:
                retrieval = await self._retrieval_service.search(
                    analysis.retrieval_query or query,
                    conn=conn,
                    query_variants=analysis.query_variants,
                    alias_filters=analysis.alias_filters,
                    entity_hints=analysis.entity_hints,
                    entity_resolution=analysis.entity_resolution,
                    followup_context=analysis.followup_context,
                    attachment_context=analysis.attachment_context,
                    url_lookup=analysis.url_lookup,
                    lookup_goal=analysis.lookup_goal,
                    prompt_category=effective_prompt_category,
                    intent_name=analysis.intent.name,
                    needs_authoritative_sources=resolved_authoritative,
                    source_policy=resolved_source_policy,
                    external_search_reason=resolved_external_search_reason,
                    context_state=context_state,
                    request_deadline_at=request_deadline_at,
                )
            if isinstance(getattr(retrieval, "retrieval_snapshot", None), dict):
                retrieval.retrieval_snapshot.setdefault("context_state", context_state)
                retrieval.retrieval_snapshot.setdefault("route_policy", route_policy)
                retrieval.retrieval_snapshot.setdefault(
                    "retrieval_decision",
                    {
                        "context_used": bool(context_state.get("resolved")),
                        "context_followup_type": context_state.get("followup_type"),
                        "context_protected_entities": context_state.get("protected_entities") or {},
                        "rejected_reasons": [],
                    },
                )
                if isinstance(retrieval.retrieval_snapshot.get("retrieval_decision"), dict):
                    retrieval.retrieval_snapshot["retrieval_decision"].setdefault(
                        "context_used",
                        bool(context_state.get("resolved")),
                    )
            retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000, 1)
            alias_terms = [item for item in analysis.query_variants if item != query]
            generation_started = time.perf_counter()
            response_mode = str((retrieval.retrieval_snapshot or {}).get("response_mode") or "generated")
            request_deadline_exceeded = bool((retrieval.retrieval_snapshot or {}).get("request_deadline_exceeded"))
            if request_deadline_at is not None and time.monotonic() >= request_deadline_at:
                request_deadline_exceeded = True
                response_mode = "templated_general_timeout" if not authoritative_query else "templated_fail_closed"
            usable_generation_hits = retrieval.selected_hits or retrieval.hits
            official_binding_snapshot = (
                (retrieval.retrieval_snapshot or {}).get("official_inventory_binding")
                if isinstance(retrieval.retrieval_snapshot, dict)
                else {}
            )
            official_proof_count = (
                int((official_binding_snapshot or {}).get("proof_count") or 0)
                if isinstance(official_binding_snapshot, dict)
                else 0
            )
            if (
                response_mode == "templated_fail_closed"
                and effective_prompt_category == "general_chat"
                and not authoritative_query
                and not request_deadline_exceeded
            ):
                response_mode = "generated"
                if isinstance(retrieval.retrieval_snapshot, dict):
                    retrieval.retrieval_snapshot.setdefault("original_response_mode", "templated_fail_closed")
                    retrieval.retrieval_snapshot["response_mode"] = response_mode
                    retrieval.retrieval_snapshot["general_business_llm_without_rag_override"] = True
                    retrieval.retrieval_snapshot["rag_optional"] = True
            if (
                response_mode == "templated_fail_closed"
                and effective_prompt_category not in {"critic_score_lookup", "source_validation"}
                and not request_deadline_exceeded
                and not (
                    isinstance(retrieval.retrieval_snapshot, dict)
                    and isinstance(retrieval.retrieval_snapshot.get("evidence_contract"), dict)
                    and retrieval.retrieval_snapshot["evidence_contract"].get("status") == "fail_closed"
                )
                and (
                    resolved_source_policy != "authoritative_external_required"
                    or bool(usable_generation_hits)
                    or official_proof_count > 0
                )
            ):
                response_mode = "generated"
                if isinstance(retrieval.retrieval_snapshot, dict):
                    retrieval.retrieval_snapshot.setdefault("original_response_mode", "templated_fail_closed")
                    retrieval.retrieval_snapshot["response_mode"] = response_mode
                    retrieval.retrieval_snapshot["non_authoritative_fail_closed_override"] = True
            if (
                response_mode == "templated_fail_closed"
                and effective_prompt_category == "internal_rag_only_validation"
                and usable_generation_hits
                and not request_deadline_exceeded
                and not (
                    isinstance(retrieval.retrieval_snapshot, dict)
                    and isinstance(retrieval.retrieval_snapshot.get("evidence_contract"), dict)
                    and retrieval.retrieval_snapshot["evidence_contract"].get("status") == "fail_closed"
                )
            ):
                response_mode = "generated"
                if isinstance(retrieval.retrieval_snapshot, dict):
                    retrieval.retrieval_snapshot.setdefault("original_response_mode", "templated_fail_closed")
                    retrieval.retrieval_snapshot["response_mode"] = response_mode
                    retrieval.retrieval_snapshot["internal_rag_generation_override"] = True
            if (
                response_mode == "templated_internal_low_coverage"
                and effective_prompt_category == "general_chat"
                and (
                    AnalysisService._looks_like_outdoor_advice_query(query)
                    or AnalysisService._looks_like_outdoor_location_advice_query(query)
                )
                and not request_deadline_exceeded
            ):
                response_mode = "generated"
                if isinstance(retrieval.retrieval_snapshot, dict):
                    retrieval.retrieval_snapshot.setdefault("original_response_mode", "templated_internal_low_coverage")
                    retrieval.retrieval_snapshot["response_mode"] = response_mode
                    retrieval.retrieval_snapshot["outdoor_general_generation_override"] = True
            if (
                response_mode == "templated_internal_low_coverage"
                and usable_generation_hits
                and not request_deadline_exceeded
            ):
                response_mode = "generated"
                if isinstance(retrieval.retrieval_snapshot, dict):
                    retrieval.retrieval_snapshot.setdefault("original_response_mode", "templated_internal_low_coverage")
                    retrieval.retrieval_snapshot["response_mode"] = response_mode
                    retrieval.retrieval_snapshot["low_coverage_generation_override"] = True
            if response_mode == "templated_fail_closed" and self._should_generate_answerable_gap(
                query=query,
                prompt_category=effective_prompt_category,
                retrieval_snapshot=retrieval.retrieval_snapshot or {},
                request_deadline_exceeded=request_deadline_exceeded,
            ):
                answer = self._generation_service.generate_answerable_gap_response(
                    query=query,
                    prompt_category=effective_prompt_category,
                    hits=retrieval.selected_hits or retrieval.hits,
                    retrieval_snapshot=retrieval.retrieval_snapshot or {},
                    language=language,
                )
                response_mode = "answerable_with_gaps"
                if isinstance(retrieval.retrieval_snapshot, dict):
                    retrieval.retrieval_snapshot.setdefault("original_response_mode", "templated_fail_closed")
                    retrieval.retrieval_snapshot["response_mode"] = "answerable_with_gaps"
                    retrieval.retrieval_snapshot["answerable_gap_applied"] = True
            elif response_mode == "templated_fail_closed":
                answer = self._generation_service.generate_authoritative_fail_closed(
                    language=language,
                    request_deadline_exceeded=request_deadline_exceeded,
                )
            elif response_mode == "critic_secondary_evidence_no_score":
                answer = self._generation_service.generate_critic_secondary_evidence_response(
                    query=query,
                    hits=retrieval.selected_hits or retrieval.hits,
                    retrieval_snapshot=retrieval.retrieval_snapshot or {},
                    language=language,
                )
            elif response_mode == "templated_internal_low_coverage":
                answer = self._generation_service.generate_low_coverage_fallback(
                    language=language,
                    producer_name=str(analysis.entity_hints.get("producer") or "").strip() or None,
                    prompt_category=effective_prompt_category,
                    query=query,
                    hits=retrieval.selected_hits or retrieval.hits,
                )
            elif response_mode == "templated_general_timeout":
                answer = self._generation_service.generate_general_timeout_fallback(
                    language=language,
                    producer_name=str(analysis.entity_hints.get("producer") or "").strip() or None,
                )
            elif response_mode == "templated_url_product_lookup":
                answer = self._generation_service.generate_url_product_lookup_response(
                    query=query,
                    hits=retrieval.selected_hits or retrieval.hits,
                    retrieval_snapshot=retrieval.retrieval_snapshot or {},
                    language=language,
                )
            else:
                answer = await self._generation_service.generate(
                    query,
                    retrieval.selected_hits or retrieval.hits,
                    conversation_id=conversation_id,
                    analysis_weight=analysis_weight,
                    compact=compact,
                    user_id=user_id,
                    summary=(
                        str((retrieval.retrieval_snapshot or {}).get("answer_plan_summary") or "").strip()
                        or None
                    ),
                    alias_terms=alias_terms or None,
                    intent_name=analysis.intent.name,
                    prompt_category=effective_prompt_category,
                    context_package=context_package,
                    project_context=project_context,
                    history_cutoff=history_cutoff,
                    language=language,
                    benchmark_trace=benchmark_trace,
                )
            if isinstance(answer, dict):
                answer_metadata = answer.get("metadata") if isinstance(answer.get("metadata"), dict) else {}
                for key in (
                    "availability_result",
                    "url_lookup",
                    "quote_ui",
                    "quote_followup",
                    "recommended_alternatives",
                    "suggested_alternatives",
                    "available_actions",
                    "pending_goal",
                    "default_confirm_action",
                ):
                    value = (retrieval.retrieval_snapshot or {}).get(key)
                    if value not in (None, "", [], {}):
                        answer_metadata[key] = value
                if response_mode:
                    answer_metadata.setdefault("response_mode", response_mode)
                answer_metadata.setdefault("source_policy", resolved_source_policy)
                answer_metadata.setdefault("prompt_category", effective_prompt_category)
                answer_metadata.setdefault("needs_authoritative_sources", resolved_authoritative)
                answer["metadata"] = answer_metadata
            generation_ms = round((time.perf_counter() - generation_started) * 1000, 1)
            if benchmark_trace and isinstance(answer, dict):
                answer_metadata = answer.get("metadata") if isinstance(answer.get("metadata"), dict) else {}
                trace_payload = answer_metadata.get("benchmark_trace") if isinstance(answer_metadata.get("benchmark_trace"), dict) else {}
                if not trace_payload:
                    trace_payload = {
                        "trace_kind": "templated_or_deterministic_generation",
                        "llm_called": False,
                        "generation_type": response_mode or "templated_or_deterministic_generation",
                        "no_llm_reason": response_mode or "templated_or_deterministic_generation",
                        "llm_request_messages": [],
                        "llm_raw_response": str(answer.get("text") or ""),
                        "llm_response_json": {
                            "template_response_mode": response_mode,
                            "llm_called": False,
                        },
                    }
                trace_payload.setdefault("llm_raw_response", str(answer.get("text") or ""))
                trace_payload["retrieval_context"] = self._build_benchmark_retrieval_trace(
                    retrieval_snapshot=retrieval.retrieval_snapshot or {},
                    selected_hits=retrieval.selected_hits or retrieval.hits,
                )
                trace_payload["response_mode_before_grounding"] = response_mode
                answer_metadata["benchmark_trace"] = trace_payload
                answer["metadata"] = answer_metadata
            grounding_started = time.perf_counter()
            grounded_answer = self._grounding_service.post_process(
                query=query,
                answer=answer if isinstance(answer, dict) else {"text": str(answer)},
                hits=retrieval.selected_hits or retrieval.hits,
                analysis=analysis,
                language=language,
                attachment=attachment,
            )
            grounding_ms = round((time.perf_counter() - grounding_started) * 1000, 1)
            metadata = answer.get("metadata") if isinstance(answer, dict) else None
            if not isinstance(metadata, dict):
                metadata = {}
            grounded_metadata = grounded_answer.get("metadata") if isinstance(grounded_answer, dict) else None
            if isinstance(grounded_metadata, dict):
                metadata.update(grounded_metadata)

            metadata.setdefault(
                "aliases",
                {
                    "filters": analysis.alias_filters,
                    "query_variants": alias_terms or [],
                },
            )
            metadata.setdefault("intent", analysis.intent.name)
            if not metadata.get("entity_hints") and analysis.entity_hints:
                metadata["entity_hints"] = analysis.entity_hints
            else:
                metadata.setdefault("entity_hints", analysis.entity_hints)
            metadata.setdefault("entity_resolution", analysis.entity_resolution)
            metadata.setdefault("followup_context", analysis.followup_context)
            metadata.setdefault("context_state", context_state)
            metadata.setdefault("context_package", context_package)
            metadata.setdefault("followup_context_resolved", bool((analysis.followup_context or {}).get("resolved")))
            if isinstance(analysis.followup_context, dict) and analysis.followup_context.get("context_anchor_used"):
                metadata.setdefault("context_anchor_used", analysis.followup_context.get("context_anchor_used"))
            else:
                metadata.setdefault("context_anchor_used", None)
            metadata.setdefault("source_followup_resolved_from_previous_answer", False)
            metadata.setdefault("attachment_context", analysis.attachment_context)
            metadata.setdefault("attachment_summary", (analysis.attachment_context or {}).get("summary"))
            metadata.setdefault(
                "attachment_entity_hints",
                (analysis.attachment_context or {}).get("entity_hints") or {},
            )
            metadata.setdefault(
                "attachment_match_intent",
                (analysis.attachment_context or {}).get("match_intent"),
            )
            metadata.setdefault("prompt_category", effective_prompt_category)
            metadata.setdefault("lookup_goal", analysis.lookup_goal)
            metadata.setdefault("url_inputs", analysis.url_inputs)
            metadata.setdefault("url_input_count", len(analysis.url_inputs or []))
            metadata.setdefault("primary_url", analysis.primary_url)
            metadata.setdefault("url_input_source", analysis.url_input_source)
            metadata.setdefault("needs_authoritative_sources", resolved_authoritative)
            metadata.setdefault("authoritative_reason", resolved_external_search_reason)
            if project_context:
                metadata.setdefault("project", project_context)
            metadata.setdefault("project_context_used", bool(project_context))
            metadata.setdefault("store_context_used", bool(store_profile))
            metadata.setdefault("source_policy", resolved_source_policy)
            metadata.setdefault("route_policy", route_policy)
            metadata.setdefault("evidence_type", self._evidence_type_for_prompt_category(effective_prompt_category))
            if retrieval.retrieval_errors:
                metadata.setdefault("retrieval_errors", retrieval.retrieval_errors)
            metadata.setdefault("source_tier", metadata.get("source_tier") or retrieval.source_tiers)
            metadata["external_search"] = retrieval.external_search or {
                "attempted": False,
                "reason": resolved_external_search_reason,
                "provider": None,
                "query": None,
                "hit_count_pre_filter": 0,
                "hit_count_post_filter": 0,
                "fetched_url_count": 0,
            }
            metadata["retrieval_snapshot"] = retrieval.retrieval_snapshot or {
                "query": query,
                    "effective_query": analysis.retrieval_query or query,
                    "prompt_category": effective_prompt_category,
                    "needs_authoritative_sources": resolved_authoritative,
                    "source_policy": resolved_source_policy,
                }
            should_attach_cerp_results = self._should_attach_cerp_results(
                prompt_category=effective_prompt_category,
                intent_name=analysis.intent.name,
                lookup_goal=analysis.lookup_goal,
                attachment_context=analysis.attachment_context,
                query=query,
            )
            cerp_results = self._build_cerp_results(
                getattr(retrieval, "cerp_products", []) or [],
                kind=self._cerp_results_kind(
                    prompt_category=effective_prompt_category,
                    intent_name=analysis.intent.name,
                    lookup_goal=analysis.lookup_goal,
                    attachment_context=analysis.attachment_context,
                    query=query,
                ),
            )
            if cerp_results.get("items") and should_attach_cerp_results:
                metadata["cerp_results"] = cerp_results
                if isinstance(metadata.get("retrieval_snapshot"), dict):
                    metadata["retrieval_snapshot"]["cerp_results"] = cerp_results
            retrieval_snapshot = metadata.get("retrieval_snapshot")
            if isinstance(retrieval_snapshot, dict) and not retrieval_snapshot.get("entity_hints") and analysis.entity_hints:
                retrieval_snapshot["entity_hints"] = analysis.entity_hints
            if isinstance(retrieval_snapshot, dict):
                retrieval_snapshot.setdefault("entity_resolution", analysis.entity_resolution)
                retrieval_snapshot.setdefault("followup_context", analysis.followup_context)
                retrieval_snapshot.setdefault("context_state", context_state)
            model_config = resolve_model_config(default_base_model="gpt-5.4-mini")
            metadata["generation_model"] = str(model_config["primary_model"])
            metadata["model_lane"] = model_config["model_lane"]
            metadata["base_model"] = model_config["base_model"]
            metadata["fine_tuned_model"] = model_config["fine_tuned_model"]
            metadata["phase3_style_eval_version"] = model_config["phase3_style_eval_version"]
            metadata.setdefault("model_generation_failed", False)
            metadata.setdefault("model_access_denied", False)
            metadata.setdefault("generation_error_status", None)
            metadata.setdefault("generation_error_body", None)
            metadata.setdefault("generation_model_attempted", metadata["generation_model"])
            if model_config["requested_model_lane"] != model_config["model_lane"]:
                metadata["requested_model_lane"] = model_config["requested_model_lane"]
            metadata["external_search_model"] = (
                retrieval.external_search.get("model")
                if isinstance(retrieval.external_search, dict) and retrieval.external_search.get("model")
                else self._external_search_model
            )
            metadata["request_deadline_exceeded"] = request_deadline_exceeded
            metadata.setdefault("response_mode", response_mode)
            metadata["answer_mode"] = self._build_answer_mode(
                prompt_category=effective_prompt_category,
                response_mode=response_mode,
                selected_hits=retrieval.selected_hits or retrieval.hits,
            )
            metadata["answer_verification_mode"] = self._build_answer_verification_mode(
                metadata=metadata,
                prompt_category=effective_prompt_category,
                response_mode=response_mode,
                selected_hits=retrieval.selected_hits or retrieval.hits,
            )
            metadata["answer_verification"] = self._build_answer_verification(
                metadata=metadata,
                mode=metadata["answer_verification_mode"],
            )
            metadata["source_mix"] = self._build_source_mix(retrieval.selected_hits or retrieval.hits)
            metadata["coverage_report"] = self._build_coverage_report(
                retrieval.retrieval_snapshot or {},
                selected_hits=retrieval.selected_hits or retrieval.hits,
            )
            citation_validation = (
                (retrieval.retrieval_snapshot or {}).get("citation_validation")
                if isinstance(retrieval.retrieval_snapshot, dict)
                else None
            )
            if isinstance(citation_validation, dict):
                metadata["citation_validation"] = citation_validation
                if citation_validation.get("hard_error_flags"):
                    existing_flags = list(metadata.get("hard_error_flags") or [])
                    for flag in citation_validation.get("hard_error_flags") or []:
                        if flag not in existing_flags:
                            existing_flags.append(flag)
                    metadata["hard_error_flags"] = existing_flags
            if isinstance(retrieval.retrieval_snapshot, dict):
                evidence_contract = retrieval.retrieval_snapshot.get("evidence_contract")
                if isinstance(evidence_contract, dict):
                    metadata["evidence_contract"] = evidence_contract
                    metadata["missing_contract_fields"] = evidence_contract.get("missing_contract_fields") or []
                    if evidence_contract.get("missing_authorized_sources"):
                        metadata["missing_authorized_sources"] = evidence_contract.get("missing_authorized_sources") or []
                    if evidence_contract.get("partial_pass_reason"):
                        metadata["gap_reason"] = evidence_contract.get("partial_pass_reason")
                    answer_plan = evidence_contract.get("answer_plan")
                    if isinstance(answer_plan, dict):
                        metadata["answer_plan"] = answer_plan
                    reason = str(evidence_contract.get("fail_closed_reason") or "").strip()
                    if reason and not metadata.get("fail_closed_reason"):
                        metadata["fail_closed_reason"] = reason
            metadata["evidence_summary"] = self._build_evidence_summary(retrieval.selected_hits or retrieval.hits)
            metadata["rejected_evidence"] = self._build_rejected_evidence(retrieval.retrieval_snapshot or {})
            if "substantive_answer" not in metadata:
                final_mode = str(metadata.get("response_mode") or "")
                final_text = str((grounded_answer or {}).get("text") or "").strip()
                metadata["substantive_answer"] = bool(final_text) and final_mode not in {
                    "generation_fallback",
                    "templated_fail_closed",
                    "templated_general_timeout",
                    "templated_internal_low_coverage",
                }
            context_anchor = self._build_context_anchor(
                query=query,
                analysis=analysis,
                answer=grounded_answer if isinstance(grounded_answer, dict) else {},
                metadata=metadata,
                prompt_category=effective_prompt_category,
            )
            if context_anchor:
                metadata["context_anchor"] = context_anchor
            if str((analysis.attachment_context or {}).get("status") or "").strip() == "analysis_partial":
                metadata.setdefault("attachment_understood_but_not_fully_processed", True)
            for key in (
                "lookup_goal",
                "match_strategy",
                "official_match_used",
                "exact_match_count",
                "near_match_count",
                "exact_match_rejection_reasons",
                "criteria_hard_filters",
                "availability_result",
                "url_lookup",
                "quote_ui",
                "quote_followup",
                "recommended_alternatives",
                "suggested_alternatives",
                "available_actions",
                "pending_goal",
                "default_confirm_action",
                "official_inventory_binding",
                "citation_validation",
                "controlling_source",
                "route_policy",
                "answer_plan",
                "behavior_profile",
                "retrieval_decision",
                "critic_lookup",
                "primary_url",
                "url_inputs",
                "url_input_count",
                "url_input_source",
            ):
                value = (retrieval.retrieval_snapshot or {}).get(key)
                if value not in (None, "", [], {}):
                    metadata[key] = value
            metadata.setdefault("official_inventory_binding", {"required": False, "proof_count": 0})
            if str(metadata.get("response_mode") or "").startswith("templated_") and not metadata.get("fail_closed_reason"):
                decision = metadata.get("retrieval_decision") if isinstance(metadata.get("retrieval_decision"), dict) else {}
                reasons = decision.get("rejected_reasons") if isinstance(decision.get("rejected_reasons"), list) else []
                metadata["fail_closed_reason"] = str(reasons[0]) if reasons else str(metadata.get("response_mode") or "")
            if (
                str(metadata.get("response_mode") or "").strip() == "answerable_with_gaps"
                and self._is_duplicate_audit_query(query)
            ):
                self._clear_answerable_duplicate_source_flags(metadata)
            metadata["timing"] = {
                "analysis_ms": analysis_ms,
                "retrieval_ms": retrieval_ms,
                "external_search_ms": (
                    retrieval.external_search.get("duration_ms")
                    if isinstance(retrieval.external_search, dict)
                    else None
                ),
                "generation_ms": generation_ms,
                "grounding_ms": grounding_ms,
                "total_ms": round((time.perf_counter() - total_started) * 1000, 1),
            }
            grounding_info = metadata.get("grounding") if isinstance(metadata.get("grounding"), dict) else {}
            if (
                grounding_info.get("fallback_applied")
                and self._should_generate_answerable_gap(
                    query=query,
                    prompt_category=effective_prompt_category,
                    retrieval_snapshot=retrieval.retrieval_snapshot or {},
                    request_deadline_exceeded=request_deadline_exceeded,
                )
                and isinstance(grounded_answer, dict)
            ):
                gap_answer = self._generation_service.generate_answerable_gap_response(
                    query=query,
                    prompt_category=effective_prompt_category,
                    hits=retrieval.selected_hits or retrieval.hits,
                    retrieval_snapshot=retrieval.retrieval_snapshot or {},
                    language=language,
                )
                grounded_answer["text"] = gap_answer.get("text")
                grounded_answer["citations"] = gap_answer.get("citations") or []
                gap_metadata = gap_answer.get("metadata") if isinstance(gap_answer.get("metadata"), dict) else {}
                metadata.update(gap_metadata)
                metadata["response_mode"] = "answerable_with_gaps"
                metadata["answer_mode"] = "partial_answer_with_gaps"
                metadata["answer_verification_mode"] = "partial_answer_with_gaps"
                metadata["substantive_answer"] = True
                metadata["grounding"]["fallback_replaced_by_answerable_gap"] = True
                if self._is_duplicate_audit_query(query):
                    self._clear_answerable_duplicate_source_flags(metadata)
            claim_validation = self._claim_validation_service.validate(
                answer_text=str((grounded_answer or {}).get("text") if isinstance(grounded_answer, dict) else ""),
                metadata=metadata,
                hits=retrieval.selected_hits or retrieval.hits,
                prompt_category=effective_prompt_category,
            )
            metadata["claim_validation"] = claim_validation
            if claim_validation.get("unsupported_claim_count"):
                metadata["unsupported_claims"] = claim_validation.get("unsupported_claims") or []
                if claim_validation.get("status") == "failed_authoritative" and isinstance(grounded_answer, dict):
                    if self._can_preserve_missing_evidence_disclosure(
                        metadata=metadata,
                        prompt_category=effective_prompt_category,
                        claim_validation=claim_validation,
                    ):
                        existing_flags = list(metadata.get("soft_error_flags") or [])
                        if "unsupported_missing_evidence_disclosure" not in existing_flags:
                            existing_flags.append("unsupported_missing_evidence_disclosure")
                        metadata["soft_error_flags"] = existing_flags
                        metadata["answer_mode"] = "partial_answer_with_gaps"
                        metadata["answer_verification_mode"] = "partial_answer_with_gaps"
                        metadata["substantive_answer"] = True
                    else:
                        existing_flags = list(metadata.get("hard_error_flags") or [])
                        if "unsupported_authoritative_claim" not in existing_flags:
                            existing_flags.append("unsupported_authoritative_claim")
                        metadata["hard_error_flags"] = existing_flags
                        grounded_answer["text"] = t("ai.fail_closed.unsupported_claims", language)
                        grounded_answer["citations"] = []
                        metadata["response_mode"] = "templated_fail_closed"
                        metadata["answer_mode"] = "fail_closed"
                        metadata["answer_verification_mode"] = "data_or_permission_needed"
                        metadata["answer_verification"] = self._build_answer_verification(
                            metadata=metadata,
                            mode="data_or_permission_needed",
                        )
                        metadata["fail_closed_reason"] = "unsupported_authoritative_claim"
                        metadata["substantive_answer"] = False
            if metadata.get("response_mode") != "templated_fail_closed":
                metadata["answer_verification_mode"] = self._build_answer_verification_mode(
                    metadata=metadata,
                    prompt_category=effective_prompt_category,
                    response_mode=str(metadata.get("response_mode") or response_mode),
                    selected_hits=retrieval.selected_hits or retrieval.hits,
                )
                metadata["answer_verification"] = self._build_answer_verification(
                    metadata=metadata,
                    mode=metadata["answer_verification_mode"],
                )
            metadata.setdefault("attachment_ingested", bool(attachment))
            metadata.setdefault(
                "processing_state",
                (
                    "attachment_analyzed"
                    if (analysis.attachment_context or {}).get("status") == "analyzed"
                    else "attachment_analysis_partial"
                ) if (analysis.attachment_context or {}).get("summary") else (
                    "metadata_only" if attachment else (
                    "url_lookup_pending" if effective_prompt_category == "url_product_lookup" else "no_attachment"
                    )
                ),
            )

            if isinstance(grounded_answer, dict):
                metadata["language"] = language
                metadata["lang"] = language
                summary_result = await self._response_summary_service.summarize(
                    answer_text=str(grounded_answer.get("text") or ""),
                    language=language,
                    prompt_category=effective_prompt_category,
                    fallback_highlights=metadata.get("grounded_highlights") if isinstance(metadata.get("grounded_highlights"), list) else [],
                )
                summary_points = summary_result.get("points") if isinstance(summary_result, dict) else []
                if isinstance(summary_points, list):
                    metadata["result_card_summary_points"] = summary_points[:3]
                    grounded_answer["summary_points"] = summary_points[:3]
                    grounded_answer["summary"] = str(summary_result.get("summary") or "\n".join(summary_points[:3]))
                metadata["summary_generation"] = (
                    summary_result.get("metadata")
                    if isinstance(summary_result.get("metadata"), dict)
                    else {"mode": "unknown", "used_llm": False}
                )

            if isinstance(grounded_answer, dict):
                if benchmark_trace:
                    metadata_trace = metadata.get("benchmark_trace") if isinstance(metadata.get("benchmark_trace"), dict) else {}
                    metadata_trace.setdefault("llm_raw_response", str(answer.get("text") if isinstance(answer, dict) else ""))
                    metadata_trace.setdefault(
                        "retrieval_context",
                        self._build_benchmark_retrieval_trace(
                            retrieval_snapshot=retrieval.retrieval_snapshot or {},
                            selected_hits=retrieval.selected_hits or retrieval.hits,
                        ),
                    )
                    metadata_trace["final_response_json"] = {
                        "text": grounded_answer.get("text"),
                        "citations": grounded_answer.get("citations"),
                        "metadata": {
                            key: value
                            for key, value in metadata.items()
                            if key != "benchmark_trace"
                        },
                    }
                    metadata_trace["trace_status"] = "captured"
                    metadata["benchmark_trace"] = metadata_trace
                grounded_answer["metadata"] = metadata
                if not grounded_answer.get("conversation_id") and isinstance(answer, dict):
                    grounded_answer["conversation_id"] = answer.get("conversation_id")
                if not grounded_answer.get("message_id") and isinstance(answer, dict):
                    grounded_answer["message_id"] = answer.get("message_id")

            grounded_answer = await self._ensure_message_persisted(
                query=query,
                answer=grounded_answer if isinstance(grounded_answer, dict) else {"text": str(grounded_answer), "metadata": metadata},
                conversation_id=conversation_id,
                user_id=user_id,
                project_context=project_context,
            )

            content = ""
            if isinstance(grounded_answer, dict):
                content = str(grounded_answer.get("text") or "")
            return ChatResponse(
                intent=analysis.intent,
                answer=grounded_answer if isinstance(grounded_answer, dict) else {"text": str(grounded_answer)},
                context=retrieval.selected_hits or retrieval.hits,
                content=content,
                language=language,
                project=project_context,
                store=store_profile,
            )
        except Exception as exc:
            logger.exception("Chat orchestration failed: %s", exc)
            raise
        finally:
            if conn:
                await conn.close()

    async def _resolve_followup_context(
        self,
        *,
        query: str,
        conversation_id: Optional[str],
    ) -> Dict[str, Any]:
        if not conversation_id or not self._looks_like_context_followup(query):
            return {}
        conv_uuid = _normalize_conversation_uuid(conversation_id)
        if conv_uuid is None:
            return {}
        try:
            messages = await get_messages_by_conversation(conv_uuid, include_metadata=True)
        except Exception as exc:
            logger.warning("Follow-up context lookup failed: %s", exc)
            return {"resolved": False, "error": f"{type(exc).__name__}: {exc}"}

        for message in reversed(messages[-12:]):
            role = str(message.get("role") or "").strip().lower()
            if role != "assistant":
                continue
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            anchor = metadata.get("context_anchor") if isinstance(metadata.get("context_anchor"), dict) else {}
            if not self._context_anchor_is_eligible(anchor, metadata):
                continue
            subjects = self._clean_subject_values(anchor.get("subjects"))
            if not subjects:
                continue
            carried: Dict[str, Any] = {}
            if len(subjects) == 1:
                carried["producer"] = subjects[0]
            else:
                carried["producer"] = subjects
            for key in ("region", "vintage", "color", "color_scope", "style", "classification", "wine"):
                value = anchor.get(key)
                if value not in (None, "", [], {}):
                    carried[key] = value
            return {
                "resolved": True,
                "source_message_id": message.get("id"),
                "source_role": role,
                "summary_snapshot": message.get("summary_snapshot") or message.get("summary"),
                "entity_hints": carried,
                "prompt_category": anchor.get("topic_type") or metadata.get("prompt_category"),
                "raw_query": query,
                "context_anchor_used": anchor,
                "source_references": anchor.get("source_references") or [],
            }

        for message in reversed(messages[-12:]):
            role = str(message.get("role") or "").strip().lower()
            if role not in {"assistant", "user"}:
                continue
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            if role == "assistant" and self._metadata_is_bad_followup_source(metadata):
                continue
            hints = metadata.get("entity_hints") if isinstance(metadata.get("entity_hints"), dict) else {}
            snapshot = metadata.get("retrieval_snapshot") if isinstance(metadata.get("retrieval_snapshot"), dict) else {}
            if not hints and isinstance(snapshot.get("entity_hints"), dict):
                hints = snapshot["entity_hints"]
            hints = self._clean_context_entity_hints(hints)
            carried = {
                key: value
                for key, value in (hints or {}).items()
                if key in {"producer", "region", "vintage", "color", "color_scope", "style", "classification"}
                and value not in (None, "", [], {})
            }
            if not carried:
                carried = self._infer_context_hints_from_text(
                    " ".join(
                        str(value or "")
                        for value in (
                            message.get("content"),
                            message.get("summary_snapshot"),
                            message.get("summary"),
                        )
                    )
                )
            if not carried:
                continue
            return {
                "resolved": True,
                "source_message_id": message.get("id"),
                "source_role": role,
                "summary_snapshot": message.get("summary_snapshot") or message.get("summary"),
                "entity_hints": carried,
                "prompt_category": (
                    metadata.get("prompt_category")
                    or snapshot.get("prompt_category")
                    or self._infer_followup_prompt_category(carried)
                ),
                "raw_query": query,
            }
        return {"resolved": False, "reason": "no_prior_entity_context", "raw_query": query}

    @classmethod
    def _metadata_is_bad_followup_source(cls, metadata: Dict[str, Any]) -> bool:
        if not isinstance(metadata, dict):
            return False
        hard_flags = metadata.get("hard_error_flags") or []
        if isinstance(hard_flags, str):
            hard_flags = [hard_flags]
        normalized_flags = {str(flag or "").strip() for flag in hard_flags if str(flag or "").strip()}
        if normalized_flags:
            return True
        if bool(metadata.get("missing_source")):
            return True
        guardrail = metadata.get("guardrail") if isinstance(metadata.get("guardrail"), dict) else {}
        guardrail_flags = guardrail.get("flags") or metadata.get("guardrail_flags") or []
        if isinstance(guardrail_flags, str):
            guardrail_flags = [guardrail_flags]
        if any(str(flag or "").strip() == "entity_guardrail_filtered" for flag in guardrail_flags):
            return True
        claim_validation = metadata.get("claim_validation") if isinstance(metadata.get("claim_validation"), dict) else {}
        if str(claim_validation.get("status") or "").strip() in {"failed_authoritative", "failed", "warning"}:
            return True
        if claim_validation.get("unsupported_claim_count"):
            return True
        if str(metadata.get("answer_verification_mode") or "").strip() == "assisted_general_answer":
            return True
        response_mode = str(metadata.get("response_mode") or "").strip()
        return response_mode in {
            "templated_fail_closed",
            "templated_internal_low_coverage",
            "generation_fallback",
        }

    @classmethod
    def _context_anchor_is_eligible(cls, anchor: Dict[str, Any], metadata: Dict[str, Any]) -> bool:
        if not isinstance(anchor, dict) or not anchor:
            return False
        if anchor.get("context_eligible") is False:
            return False
        if cls._metadata_is_bad_followup_source(metadata):
            subject_source = str(anchor.get("subject_source") or "").strip()
            if subject_source != "user_prompt":
                return False
        return bool(cls._clean_subject_values(anchor.get("subjects")))

    @classmethod
    def _clean_context_entity_hints(cls, hints: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = dict(hints or {})
        if "producer" in cleaned:
            producers = cls._clean_subject_values(cleaned.get("producer"))
            if len(producers) == 1:
                cleaned["producer"] = producers[0]
            elif len(producers) > 1:
                cleaned["producer"] = producers
            else:
                cleaned.pop("producer", None)
        return cleaned

    @classmethod
    def _clean_subject_values(cls, values: Any) -> list[str]:
        raw_values = values if isinstance(values, list) else [values]
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in raw_values:
            text = " ".join(str(value or "").replace("\u3000", " ").split()).strip(" ,;:|")
            if not text:
                continue
            if cls._looks_like_source_or_critic_entity(text):
                continue
            if cls._looks_like_producer_noise(text):
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        return cleaned[:4]

    @classmethod
    def _build_context_anchor(
        cls,
        *,
        query: str,
        analysis: Any,
        answer: Dict[str, Any],
        metadata: Dict[str, Any],
        prompt_category: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        explicit_subjects = cls._extract_user_prompt_subjects(query)
        hint_subjects = cls._clean_subject_values((analysis.entity_hints or {}).get("producer"))
        subjects = explicit_subjects or hint_subjects
        if not subjects:
            return None
        hard_flags = metadata.get("hard_error_flags") or []
        if isinstance(hard_flags, str):
            hard_flags = [hard_flags]
        source_references = cls._compact_source_references((answer or {}).get("citations"))
        subject_source = "user_prompt" if explicit_subjects else "entity_hints"
        context_eligible = bool(metadata.get("substantive_answer", True)) and not hard_flags
        if cls._metadata_is_bad_followup_source(metadata) and subject_source != "user_prompt":
            context_eligible = False
        anchor: Dict[str, Any] = {
            "subjects": subjects,
            "topic_type": prompt_category or metadata.get("prompt_category") or "general_chat",
            "source_message_id": (answer or {}).get("message_id"),
            "confidence": "high" if subject_source == "user_prompt" else "medium",
            "context_eligible": context_eligible,
            "subject_source": subject_source,
            "source_references": source_references,
        }
        for key in ("region", "vintage", "color", "color_scope", "style", "classification", "wine"):
            value = (analysis.entity_hints or {}).get(key)
            if value not in (None, "", [], {}):
                anchor[key] = value
        return anchor

    @classmethod
    def _extract_user_prompt_subjects(cls, query: str) -> list[str]:
        text = str(query or "")
        candidates: list[str] = []
        for pattern in (
            r"\b(?:YS|Champagne|Maison|Chateau|Château)\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){0,3}\b",
            r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+\s+Colin\b",
            r"\bLa\s+Rogerie\b",
            r"\bJean\s+Marshall\b",
        ):
            for match in re.finditer(pattern, text):
                candidates.append(match.group(0))
        cleaned = cls._clean_subject_values(candidates)
        if len(cleaned) > 1:
            return cleaned
        if re.search(r"\b(?:vs|versus|compare|comparison)\b|比較|對比|差異", text, flags=re.IGNORECASE):
            for token in re.split(r"\bvs\b|versus|,|/|、|和|與|及|比較|對比", text, flags=re.IGNORECASE):
                token_clean = " ".join(token.split()).strip(" ?，。:：")
                if re.search(r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,3}\b", token_clean):
                    candidates.append(token_clean)
        return cls._clean_subject_values(candidates)

    @classmethod
    def _compact_source_references(cls, citations: Any) -> list[Dict[str, Any]]:
        refs: list[Dict[str, Any]] = []
        if not isinstance(citations, list):
            return refs
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            meta = citation.get("meta") if isinstance(citation.get("meta"), dict) else {}
            url = (
                citation.get("url")
                or citation.get("source_url")
                or meta.get("url")
                or meta.get("source_url")
                or meta.get("canonical_url")
            )
            filename = citation.get("filename") or citation.get("source") or meta.get("filename") or meta.get("file_name")
            title = (
                citation.get("title")
                or meta.get("title")
                or meta.get("page_title")
                or filename
                or url
                or citation.get("id")
            )
            summary = citation.get("summary") or meta.get("summary") or citation.get("text")
            ref = {
                "title": str(title or "").strip(),
                "url": str(url or "").strip(),
                "filename": str(filename or "").strip(),
                "page": citation.get("page") or meta.get("page") or meta.get("page_number"),
                "line": citation.get("line") or meta.get("line") or meta.get("line_number"),
                "source_type": citation.get("source_type") or meta.get("source_type"),
                "summary": str(summary or "").strip()[:320],
            }
            if ref["title"] or ref["url"] or ref["filename"]:
                refs.append(ref)
        return refs[:8]

    @staticmethod
    def _is_source_followup_query(query: str) -> bool:
        text = str(query or "").strip().lower()
        if not text:
            return False
        followup_tokens = (
            "承上",
            "上題",
            "前題",
            "上面",
            "剛剛",
            "這個",
            "這款",
            "source",
            "citation",
            "reference",
        )
        source_tokens = (
            "來源",
            "引用",
            "網站",
            "文件",
            "第幾頁",
            "頁碼",
            "第幾行",
            "行號",
            "url",
            "link",
            "source",
            "citation",
            "reference",
        )
        return any(token in text for token in followup_tokens) and any(token in text for token in source_tokens)

    @classmethod
    def _build_previous_source_followup_answer(
        cls,
        *,
        query: str,
        followup_context: Dict[str, Any],
        language: Optional[str],
        source_policy: str,
        prompt_category: str,
        analysis_ms: float,
    ) -> Dict[str, Any]:
        sources = [
            source
            for source in (followup_context.get("source_references") or [])
            if isinstance(source, dict)
        ]
        zh = str(language or "").strip() == "zh-Hant"
        lines: list[str] = []
        if zh:
            lines.append("以下是上一則回答使用的來源：")
        else:
            lines.append("These are the sources used by the previous answer:")
        for index, source in enumerate(sources[:6], start=1):
            title = str(source.get("title") or source.get("filename") or source.get("url") or f"Source {index}").strip()
            url = str(source.get("url") or "").strip()
            filename = str(source.get("filename") or "").strip()
            page = source.get("page")
            line = source.get("line")
            location_parts = []
            if filename:
                location_parts.append(filename)
            if page not in (None, "", [], {}):
                location_parts.append(("第 {page} 頁" if zh else "page {page}").format(page=page))
            if line not in (None, "", [], {}):
                location_parts.append(("第 {line} 行" if zh else "line {line}").format(line=line))
            elif filename and zh:
                location_parts.append("系統沒有行號 metadata")
            elif filename:
                location_parts.append("no line-number metadata")
            location = f" ({'; '.join(location_parts)})" if location_parts else ""
            suffix = f" - {url}" if url else ""
            lines.append(f"{index}. **{title}**{location}{suffix}")
            summary = str(source.get("summary") or "").strip()
            if summary:
                lines.append(f"   - {summary[:220]}")
        text = "\n".join(lines)
        metadata = {
            "response_mode": "source_followup_from_previous_answer",
            "answer_mode": "generated",
            "answer_verification_mode": "verified_answer" if sources else "data_or_permission_needed",
            "answer_verification": {
                "mode": "verified_answer" if sources else "data_or_permission_needed",
                "verified": bool(sources),
                "requires_disclaimer": False,
                "reason": "previous_answer_source_references" if sources else "missing_previous_source_references",
            },
            "source_mix": cls._build_source_mix_from_source_dicts(sources),
            "coverage_report": {
                "qualified_hit_count": len(sources),
                "rejected_hit_count": 0,
                "entity_match_required": False,
                "doc_type_rule": [],
                "page_qualification_applied": False,
            },
            "evidence_summary": [
                {
                    "id": source.get("id"),
                    "title": str(source.get("title") or source.get("filename") or source.get("url") or "").strip(),
                    "doc_type": str(source.get("doc_type") or source.get("source_type") or "").strip(),
                    "source_tier": str(source.get("source_tier") or "").strip(),
                }
                for source in sources[:6]
            ],
            "rejected_evidence": [],
            "substantive_answer": True,
            "source_followup_resolved_from_previous_answer": True,
            "context_anchor_used": followup_context.get("context_anchor_used"),
            "followup_context": followup_context,
            "followup_context_resolved": True,
            "source_policy": source_policy,
            "prompt_category": prompt_category,
            "model_generation_failed": False,
            "model_access_denied": False,
            "external_search": {
                "attempted": False,
                "reason": "previous_answer_sources",
                "provider": None,
                "query": None,
                "hit_count_pre_filter": 0,
                "hit_count_post_filter": 0,
                "fetched_url_count": 0,
            },
            "retrieval_snapshot": {
                "query": query,
                "prompt_category": prompt_category,
                "source_policy": source_policy,
                "response_mode": "source_followup_from_previous_answer",
                "source_followup_resolved_from_previous_answer": True,
            },
            "citation_validation": {"unmapped_citation_count": 0},
            "hard_error_flags": [],
            "official_inventory_binding": {"required": False, "proof_count": 0},
            "timing": {
                "analysis_ms": analysis_ms,
                "retrieval_ms": 0,
                "external_search_ms": None,
                "generation_ms": 0,
                "grounding_ms": 0,
                "total_ms": analysis_ms,
            },
        }
        return {"text": text, "citations": sources, "metadata": metadata}

    @staticmethod
    def _infer_context_hints_from_text(text: str) -> Dict[str, Any]:
        lowered = str(text or "").lower()
        hints: Dict[str, Any] = {}
        if any(token in lowered for token in ("burgundy", "bourgogne", "布根地", "勃艮第")):
            hints["region"] = "Burgundy"
        elif any(token in lowered for token in ("champagne", "香檳", "香槟")):
            hints["region"] = "Champagne"
        elif any(token in lowered for token in ("bordeaux", "波爾多", "波尔多")):
            hints["region"] = "Bordeaux"

        vintage_match = None
        try:
            import re

            vintage_match = re.search(r"\b((?:19|20)\d{2})\b", str(text or ""))
        except Exception:
            vintage_match = None
        if vintage_match:
            hints["vintage"] = vintage_match.group(1)

        colors = []
        if any(token in lowered for token in ("red", "紅酒", "红酒", "紅", "红")):
            colors.append("red")
        if any(token in lowered for token in ("white", "白酒", "白")):
            colors.append("white")
        if colors:
            hints["color_scope"] = colors
        return hints

    @staticmethod
    def _infer_followup_prompt_category(entity_hints: Dict[str, Any]) -> Optional[str]:
        if entity_hints.get("region") and entity_hints.get("vintage"):
            return "vintage_region_overview"
        return None

    @staticmethod
    def _looks_like_context_followup(query: str) -> bool:
        lowered = str(query or "").strip().lower()
        if not lowered:
            return False
        tokens = (
            "follow up",
            "as above",
            "previous",
            "same as above",
            "why",
            "cause",
            "source",
            "sources",
            "citation",
            "citations",
            "score",
            "scores",
            "rating",
            "ratings",
            "review",
            "reviews",
            "\u627f\u4e0a",
            "\u627f\u63a5",
            "\u7e7c\u7e8c",
            "\u4e0a\u984c",
            "\u524d\u984c",
            "\u524d\u4e00\u984c",
            "\u9019\u6a23",
            "\u9019\u500b",
            "\u9019\u6b3e",
            "\u5b83",
            "\u540c\u4e00\u6b3e",
            "\u540c\u4e00\u500b",
            "\u525b\u525b",
            "\u4e0a\u8ff0",
            "\u539f\u56e0",
            "\u70ba\u4ec0\u9ebc",
            "\u98a8\u683c",
            "\u4f86\u6e90",
            "\u5f15\u7528",
            "\u9152\u8a55",
            "\u5206\u6578",
            "\u54ea\u500b\u7db2\u7ad9",
            "\u7b2c\u5e7e\u9801",
            "呈上",
            "上題",
            "上题",
            "前題",
            "前题",
            "前述",
            "為何",
            "为什么",
            "這樣推薦",
            "这样推荐",
            "其實我是想要",
        )
        return any(token in lowered for token in tokens)

    @staticmethod
    def _merge_missing_hints(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        for key, value in (extra or {}).items():
            if value in (None, "", [], {}):
                continue
            if merged.get(key) in (None, "", [], {}):
                merged[key] = value
        return merged

    @classmethod
    def _merge_followup_entity_hints(
        cls,
        query: str,
        current: Dict[str, Any],
        prior: Dict[str, Any],
    ) -> tuple[Dict[str, Any], str, Dict[str, Any]]:
        protected_keys = {"producer", "wine", "wine_name", "full_wine_name", "region", "vintage", "color", "color_scope"}
        merged = dict(current or {})
        protected: Dict[str, Any] = {}
        for key, prior_value in (prior or {}).items():
            if prior_value in (None, "", [], {}):
                continue
            current_value = merged.get(key)
            if current_value in (None, "", [], {}):
                merged[key] = prior_value
                protected[key] = prior_value
                continue
            if key not in protected_keys:
                continue
            if cls._looks_like_source_or_critic_entity(current_value):
                merged[key] = prior_value
                protected[key] = prior_value
                continue
            if not cls._query_mentions_entity_value(query, current_value):
                merged[key] = prior_value
                protected[key] = prior_value
        return merged, ("protected_prior_context" if protected else "fill_missing_context"), protected

    @staticmethod
    def _query_mentions_entity_value(query: str, value: Any) -> bool:
        query_text = " ".join(str(query or "").lower().split())
        if not query_text:
            return False
        values = value if isinstance(value, list) else [value]
        for item in values:
            item_text = " ".join(str(item or "").lower().split())
            if item_text and item_text in query_text:
                return True
        return False

    @staticmethod
    def _looks_like_source_or_critic_entity(value: Any) -> bool:
        text = " ".join(str(value or "").lower().split())
        if not text:
            return False
        return any(
            token in text
            for token in (
                "wine advocate",
                "jasper morris",
                "burghound",
                "vinous",
                "decanter",
                "drinking window",
                "mw page",
                "score page",
                "review page",
                "tasted november",
                "drinking window",
                "score",
                "page",
            )
        )

    @staticmethod
    def _looks_like_producer_noise(value: Any) -> bool:
        text = " ".join(str(value or "").lower().split())
        if not text:
            return False
        noise_tokens = (
            "tasted november",
            "tasted ",
            " burghound",
            "burghound",
            "db:",
            "drinking window",
            "score",
            "page",
            "clos colin banc",
            "comtes lafon db",
            "colin-deléger",
            "colin-deleger",
        )
        return any(token in text for token in noise_tokens)

    @staticmethod
    def _build_followup_retrieval_query(query: str, entity_hints: Dict[str, Any]) -> str:
        parts = [str(query or "").strip()]
        for key in ("producer", "region", "vintage", "color", "color_scope", "style", "classification"):
            value = entity_hints.get(key)
            if isinstance(value, list):
                value = " ".join(str(item) for item in value if str(item).strip())
            value_text = str(value or "").strip()
            if value_text and value_text.lower() not in " ".join(parts).lower():
                parts.append(value_text)
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _should_attach_cerp_results(
        *,
        prompt_category: Optional[str],
        intent_name: Optional[str],
        lookup_goal: Optional[str],
        attachment_context: Optional[Dict[str, Any]],
        query: Optional[str] = None,
    ) -> bool:
        if prompt_category in CERP_RESULT_PROMPT_CATEGORIES:
            return True
        if intent_name in CERP_RESULT_INTENTS:
            return True
        if str(lookup_goal or "").strip() == "product_availability_from_url":
            return True
        if isinstance(attachment_context, dict):
            if str(attachment_context.get("match_intent") or "").strip() == "cerp_match":
                return True
        return ChatOrchestrator._has_explicit_cerp_lookup_intent(query)

    @staticmethod
    def _has_explicit_cerp_lookup_intent(query: Optional[str]) -> bool:
        return bool(CERP_EXPLICIT_LOOKUP_RE.search(str(query or "")))

    @classmethod
    def _cerp_results_kind(
        cls,
        *,
        prompt_category: Optional[str],
        intent_name: Optional[str],
        lookup_goal: Optional[str],
        attachment_context: Optional[Dict[str, Any]],
        query: Optional[str] = None,
    ) -> str:
        if prompt_category in CERP_RESULT_PROMPT_CATEGORIES:
            return prompt_category
        if intent_name in CERP_RESULT_INTENTS:
            return "quote_recommendation"
        if str(lookup_goal or "").strip() == "product_availability_from_url":
            return "url_product_lookup"
        if isinstance(attachment_context, dict):
            if str(attachment_context.get("match_intent") or "").strip() == "cerp_match":
                return "image_product_lookup"
        if cls._has_explicit_cerp_lookup_intent(query):
            return "explicit_cerp_lookup"
        return "cerp_lookup"

    @staticmethod
    def _build_cerp_results(cerp_products: list[Dict[str, Any]], *, kind: str = "cerp_lookup") -> Dict[str, Any]:
        items: list[Dict[str, Any]] = []
        generated_at = datetime.now(timezone.utc).isoformat()
        for product in cerp_products or []:
            if not isinstance(product, dict):
                continue
            code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
            name = str(
                product.get("name")
                or product.get("name_en")
                or product.get("name_ch")
                or product.get("product")
                or product.get("title")
                or ""
            ).strip()
            producer = str(product.get("producer") or "").strip()
            if not (code or name or producer):
                continue
            timestamp = (
                product.get("timestamp")
                or product.get("cerp_timestamp")
                or product.get("updated_at")
                or generated_at
            )
            source_trace = str(product.get("source_trace") or "").strip()
            if not source_trace:
                source_trace = f"CERP ExportProduct/ExportProductsInfo | sku:{code or '-'} | timestamp:{timestamp}"
            stock = product.get("stock") or product.get("stock_qty") or product.get("total_stock")
            price = product.get("price") or product.get("list_price")
            vip_price = product.get("vip_price") or product.get("quote_price")
            proof = {
                "type": "cerp",
                "code": code,
                "stock": stock,
                "price": price,
                "vip_price": vip_price,
                "timestamp": timestamp,
                "endpoint": "CERP ExportProduct/ExportProductsInfo",
            }
            items.append(
                {
                    "code": code,
                    "no": code,
                    "name": name,
                    "producer": producer,
                    "vintage": product.get("vintage"),
                    "stock": stock,
                    "price": price,
                    "list_price": product.get("list_price") or price,
                    "vip_price": vip_price,
                    "status": product.get("status") or product.get("availability"),
                    "source": "CERP",
                    "source_trace": source_trace,
                    "timestamp": timestamp,
                    "endpoint": "CERP ExportProduct/ExportProductsInfo",
                    "proof": proof,
                }
            )
        return {
            "kind": kind,
            "count": len(items),
            "source": "CERP",
            "generated_at": generated_at,
            "proof_count": len(items),
            "items": items[:20],
        }

    @staticmethod
    def _get_float_env(env_name: str, default: float) -> float:
        raw = os.getenv(env_name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    @staticmethod
    def _build_benchmark_retrieval_trace(*, retrieval_snapshot: Dict[str, Any], selected_hits) -> Dict[str, Any]:
        hits = []
        for hit in list(selected_hits or [])[:12]:
            meta = getattr(hit, "meta", {}) or {}
            hits.append(
                {
                    "id": getattr(hit, "id", None),
                    "source_type": getattr(hit, "source_type", None),
                    "source_tier": getattr(hit, "source_tier", None),
                    "score": getattr(hit, "score", None),
                    "source_trace": meta.get("source_trace"),
                    "source_family": meta.get("source_family"),
                    "source_name": meta.get("source_name") or meta.get("title") or meta.get("filename"),
                    "page": meta.get("page"),
                    "row_id": meta.get("row_id"),
                    "endpoint": meta.get("endpoint"),
                    "timestamp": meta.get("timestamp"),
                    "text_excerpt": str(getattr(hit, "text", "") or "")[:600],
                }
            )
        return {
            "selected_hits": hits,
            "selected_hit_count": len(list(selected_hits or [])),
            "source_policy": retrieval_snapshot.get("source_policy"),
            "route_policy": retrieval_snapshot.get("route_policy"),
            "controlling_source": retrieval_snapshot.get("controlling_source"),
            "citation_validation": retrieval_snapshot.get("citation_validation"),
            "evidence_contract": retrieval_snapshot.get("evidence_contract"),
            "answer_plan": retrieval_snapshot.get("answer_plan"),
            "official_inventory_binding": retrieval_snapshot.get("official_inventory_binding"),
            "cerp_results": retrieval_snapshot.get("cerp_results"),
            "retrieval_decision": retrieval_snapshot.get("retrieval_decision"),
            "external_search": retrieval_snapshot.get("external_search"),
            "request_deadline_exceeded": retrieval_snapshot.get("request_deadline_exceeded"),
            "response_mode": retrieval_snapshot.get("response_mode"),
        }

    @staticmethod
    def _should_generate_answerable_gap(
        *,
        query: str,
        prompt_category: Optional[str],
        retrieval_snapshot: Dict[str, Any],
        request_deadline_exceeded: bool,
    ) -> bool:
        if request_deadline_exceeded:
            return False
        category = str(prompt_category or "").strip()
        lowered = str(query or "").casefold()
        if category in {"permission_boundary"}:
            return False
        hard_flags = set()
        for container_key in ("retrieval_decision", "citation_validation"):
            container = retrieval_snapshot.get(container_key)
            if isinstance(container, dict):
                hard_flags.update(str(item) for item in (container.get("hard_error_flags") or []))
                hard_flags.update(str(item) for item in (container.get("rejected_reasons") or []))
        hard_flags.update(str(item) for item in (retrieval_snapshot.get("hard_error_flags") or []))
        if any("permission" in flag or "prompt_injection" in flag or "denied" in flag for flag in hard_flags):
            return False
        contract = retrieval_snapshot.get("evidence_contract") if isinstance(retrieval_snapshot.get("evidence_contract"), dict) else {}
        reason = str(
            contract.get("fail_closed_reason")
            or retrieval_snapshot.get("fail_closed_reason")
            or ""
        ).strip()
        if reason in {"prompt_injection_guardrail", "permission_boundary_requires_explicit_authorization"}:
            return False
        if reason == "licensed_review_source_missing":
            return True
        if category == "critic_score_lookup" and any(
            token in lowered
            for token in ("burghound", "vinous", "wine advocate", "jasper", "inside burgundy", "decanter", "score", "review")
        ):
            return True
        if category in {"source_validation"} and (
            "source trail" in lowered
            or "citation" in lowered
            or "cite" in lowered
            or "exact source" in lowered
            or "which database" in lowered
            or "api endpoint" in lowered
        ):
            return True
        if "duplicate" in lowered or "near-duplicate" in lowered or "merged" in lowered:
            return True
        if category in {"quote_recommendation", "inventory_lookup"} and (
            "inventory" in lowered
            or "current" in lowered
            or "stock" in lowered
            or "available" in lowered
            or "list" in lowered
            or "show" in lowered
            or "庫存" in lowered
            or "現貨" in lowered
            or "有貨" in lowered
            or "商品" in lowered
            or "產品" in lowered
            or "列出" in lowered
            or "case" in lowered
            or "champagne" in lowered
        ):
            return True
        return False

    @staticmethod
    def _is_duplicate_audit_query(query: str) -> bool:
        lowered = str(query or "").casefold()
        return "duplicate" in lowered or "near-duplicate" in lowered or "merged" in lowered

    @staticmethod
    def _clear_answerable_duplicate_source_flags(metadata: Dict[str, Any]) -> None:
        removable = {
            "authoritative_sources_missing",
            "missing_authoritative_source",
            "missing_required_source_metadata",
            "citation_validation_fail_closed",
        }
        flags = metadata.get("hard_error_flags") or []
        if isinstance(flags, str):
            flags = [flags]
        metadata["hard_error_flags"] = [flag for flag in flags if str(flag) not in removable]
        for key in ("citation_validation", "retrieval_decision"):
            container = metadata.get(key) if isinstance(metadata.get(key), dict) else {}
            if not container:
                continue
            for list_key in ("hard_error_flags", "rejected_reasons"):
                values = container.get(list_key) or []
                if isinstance(values, str):
                    values = [values]
                container[list_key] = [value for value in values if str(value) not in removable]

    @staticmethod
    def _can_preserve_missing_evidence_disclosure(
        *,
        metadata: Dict[str, Any],
        prompt_category: Optional[str],
        claim_validation: Dict[str, Any],
    ) -> bool:
        category = str(prompt_category or metadata.get("prompt_category") or "").strip()
        if category not in {"exact_review_lookup", "multi_review_compare", "source_hierarchy_conflict"}:
            return False
        evidence_contract = metadata.get("evidence_contract") if isinstance(metadata.get("evidence_contract"), dict) else {}
        if str(evidence_contract.get("status") or "").strip() not in {"pass", "partial_pass"}:
            return False
        citation_validation = metadata.get("citation_validation") if isinstance(metadata.get("citation_validation"), dict) else {}
        if int(citation_validation.get("citation_count") or 0) <= 0:
            return False
        unsupported_claims = claim_validation.get("unsupported_claims") or []
        if not unsupported_claims:
            return False
        missing_markers = (
            "do not have",
            "don't have",
            "does not have",
            "no verified",
            "no licensed",
            "not verified",
            "cannot verify",
            "can't verify",
            "not available",
            "missing",
            "insufficient",
            "data is insufficient",
            "provided context",
            "retrieved evidence",
        )
        return all(
            any(marker in str(claim or "").casefold() for marker in missing_markers)
            for claim in unsupported_claims
        )

    @staticmethod
    def _build_answer_mode(
        *,
        prompt_category: Optional[str],
        response_mode: Optional[str],
        selected_hits,
    ) -> str:
        normalized_mode = str(response_mode or "").strip()
        category = str(prompt_category or "").strip()
        if normalized_mode == "answerable_with_gaps":
            return "partial_answer_with_gaps"
        if normalized_mode == "templated_fail_closed":
            return "fail_closed"
        if category == "producer_ranking":
            return "ranking_shortlist"
        if category in {"vineyard_lookup", "tasting_note_generation"} and not selected_hits:
            return "grounded_gap"
        if normalized_mode in {"templated_internal_low_coverage", "templated_general_timeout"}:
            return "grounded_gap"
        return "generated"

    @staticmethod
    def _build_answer_verification_mode(
        *,
        metadata: Dict[str, Any],
        prompt_category: Optional[str],
        response_mode: Optional[str],
        selected_hits,
    ) -> str:
        normalized_response = str(response_mode or metadata.get("response_mode") or "").strip()
        if normalized_response == "answerable_with_gaps":
            return "partial_answer_with_gaps"
        if normalized_response in {
            "templated_fail_closed",
            "templated_internal_low_coverage",
            "templated_general_timeout",
            "generation_fallback",
        }:
            return "data_or_permission_needed"
        if metadata.get("missing_permissions"):
            return "data_or_permission_needed"
        hard_flags = metadata.get("hard_error_flags") or []
        if isinstance(hard_flags, str):
            hard_flags = [hard_flags]
        if any("permission" in str(flag) or "missing_source" in str(flag) for flag in hard_flags):
            return "data_or_permission_needed"

        evidence_contract = metadata.get("evidence_contract") if isinstance(metadata.get("evidence_contract"), dict) else {}
        claim_validation = metadata.get("claim_validation") if isinstance(metadata.get("claim_validation"), dict) else {}
        citation_validation = metadata.get("citation_validation") if isinstance(metadata.get("citation_validation"), dict) else {}
        cerp_results = metadata.get("cerp_results") if isinstance(metadata.get("cerp_results"), dict) else {}
        official_binding = metadata.get("official_inventory_binding") if isinstance(metadata.get("official_inventory_binding"), dict) else {}
        cerp_proof_count = int(cerp_results.get("proof_count") or official_binding.get("proof_count") or 0)

        if cerp_proof_count > 0:
            return "verified_answer"
        if str(evidence_contract.get("status") or "").strip() == "pass":
            return "verified_answer"
        if int(citation_validation.get("citation_count") or 0) > 0 and not citation_validation.get("unmapped_citation_count"):
            return "verified_answer"
        if str(claim_validation.get("status") or "").strip() in {"failed_authoritative", "failed"}:
            return "data_or_permission_needed"

        category = str(prompt_category or metadata.get("prompt_category") or "").strip()
        if category in {
            "exact_review_lookup",
            "multi_review_compare",
            "critic_score_lookup",
            "book_corpus_lookup",
            "source_hierarchy_conflict",
            "inventory_lookup",
            "quote_recommendation",
            "alias_inventory_equivalence",
            "permission_boundary",
        }:
            return "data_or_permission_needed"
        return "assisted_general_answer"

    @staticmethod
    def _build_answer_verification(*, metadata: Dict[str, Any], mode: str) -> Dict[str, Any]:
        reason = ""
        if mode == "verified_answer":
            reason = "supported_by_evidence_contract_or_source_trace"
        elif mode == "partial_answer_with_gaps":
            reason = str(metadata.get("gap_reason") or metadata.get("fail_closed_reason") or "missing_verified_data")
        elif mode == "assisted_general_answer":
            reason = "general_llm_reference_not_verified_by_ys_sources"
        elif mode == "data_or_permission_needed":
            reason = str(metadata.get("fail_closed_reason") or "missing_verified_data_or_permission")
        return {
            "mode": mode,
            "verified": mode == "verified_answer",
            "requires_disclaimer": mode == "assisted_general_answer",
            "reason": reason,
        }

    @staticmethod
    def _evidence_type_for_prompt_category(prompt_category: Optional[str]) -> str:
        category = str(prompt_category or "").strip()
        if category in {"exact_review_lookup", "multi_review_compare", "critic_score_lookup"}:
            return "licensed_review"
        if category in {"book_corpus_lookup", "internal_rag_only_validation"}:
            return "book_ocr"
        if category == "alias_inventory_equivalence":
            return "cerp_snapshot"
        if category == "source_hierarchy_conflict":
            return "source_hierarchy"
        if category in {"inventory_lookup", "quote_recommendation", "url_product_lookup", "image_product_lookup"}:
            return "cerp_snapshot"
        return "grounded_answer"

    @staticmethod
    def _build_source_mix(selected_hits) -> Dict[str, Any]:
        buckets = {
            "internal_approved": 0,
            "internal_official": 0,
            "internal_other": 0,
            "external_authoritative": 0,
            "external_other": 0,
        }
        hits = list(selected_hits or [])
        total = len(hits)
        for hit in hits:
            meta = getattr(hit, "meta", {}) or {}
            tier = str(getattr(hit, "source_tier", "") or meta.get("source_tier") or "").strip().lower()
            source_type = str(getattr(hit, "source_type", "") or meta.get("source_type") or "").strip().lower()
            source_group = str(meta.get("source_group") or meta.get("source_kind") or "").strip().lower()
            if tier == "internal_approved":
                buckets["internal_approved"] += 1
            elif tier == "internal_official":
                buckets["internal_official"] += 1
            elif tier in {"tier 1", "tier 2", "external_evidence"}:
                buckets["external_authoritative"] += 1
            elif (
                tier.startswith("internal")
                or source_type in {"rag", "cerp", "internal", "official_site"}
                or source_group in {"internal", "official_site"}
            ):
                buckets["internal_other"] += 1
            else:
                buckets["external_other"] += 1
        return {
            key: {
                "count": value,
                "percent": round((value / total) * 100, 1) if total else 0.0,
            }
            for key, value in buckets.items()
        }

    @staticmethod
    def _build_source_mix_from_source_dicts(sources: list[Dict[str, Any]]) -> Dict[str, Any]:
        buckets = {
            "internal_approved": 0,
            "internal_official": 0,
            "internal_other": 0,
            "external_authoritative": 0,
            "external_other": 0,
        }
        total = len(sources or [])
        for source in sources or []:
            tier = str(source.get("source_tier") or "").strip().lower()
            source_type = str(source.get("source_type") or source.get("kind") or "").strip().lower()
            source_group = str(source.get("source_group") or source.get("source_kind") or "").strip().lower()
            if tier == "internal_approved":
                buckets["internal_approved"] += 1
            elif tier == "internal_official":
                buckets["internal_official"] += 1
            elif tier in {"tier 1", "tier 2", "external_evidence"} or source_type == "external":
                buckets["external_authoritative"] += 1
            elif (
                tier.startswith("internal")
                or source_type in {"internal", "rag", "cerp", "official_site"}
                or source_group in {"internal", "official_site"}
            ):
                buckets["internal_other"] += 1
            else:
                buckets["external_other"] += 1
        return {
            key: {
                "count": value,
                "percent": round((value / total) * 100, 1) if total else 0.0,
            }
            for key, value in buckets.items()
        }

    @staticmethod
    def _build_coverage_report(retrieval_snapshot: Dict[str, Any], *, selected_hits) -> Dict[str, Any]:
        decision = (
            retrieval_snapshot.get("retrieval_decision")
            if isinstance(retrieval_snapshot.get("retrieval_decision"), dict)
            else {}
        )
        hit_scores = decision.get("hit_scores") if isinstance(decision.get("hit_scores"), list) else []
        prompt_category = str(retrieval_snapshot.get("prompt_category") or "").strip()
        return {
            "qualified_hit_count": len(list(selected_hits or [])),
            "rejected_hit_count": sum(1 for item in hit_scores if item.get("rejected_reasons")),
            "entity_match_required": prompt_category in {"vineyard_lookup", "tasting_note_generation"},
            "doc_type_rule": decision.get("required_doc_types") or [],
            "page_qualification_applied": prompt_category in {"vineyard_lookup", "tasting_note_generation"},
        }

    @staticmethod
    def _build_evidence_summary(selected_hits) -> list[Dict[str, Any]]:
        rows = []
        for hit in list(selected_hits or [])[:6]:
            meta = getattr(hit, "meta", {}) or {}
            rows.append(
                {
                    "id": getattr(hit, "id", None),
                    "title": str(meta.get("title") or meta.get("filename") or getattr(hit, "id", "")).strip(),
                    "doc_type": str(meta.get("doc_type") or meta.get("source_type") or "").strip(),
                    "source_tier": str(getattr(hit, "source_tier", "") or meta.get("source_tier") or "").strip(),
                }
            )
        return rows

    @staticmethod
    def _build_rejected_evidence(retrieval_snapshot: Dict[str, Any]) -> list[Dict[str, Any]]:
        decision = (
            retrieval_snapshot.get("retrieval_decision")
            if isinstance(retrieval_snapshot.get("retrieval_decision"), dict)
            else {}
        )
        rows = []
        for item in decision.get("hit_scores") or []:
            reasons = item.get("rejected_reasons") or []
            if item.get("rejected") is False:
                continue
            if not reasons:
                continue
            rows.append(
                {
                    "id": item.get("id"),
                    "label": item.get("label") or item.get("id"),
                    "source_tier": item.get("source_tier"),
                    "rejected_reasons": reasons,
                }
            )
            if len(rows) >= 10:
                break
        return rows

    @staticmethod
    def _build_timeout_retrieval_result(
        *,
        query: str,
        prompt_category: Optional[str],
        needs_authoritative_sources: bool,
        source_policy: str,
        external_search_reason: Optional[str],
        response_mode: str,
        attachment_context: Optional[Dict[str, Any]],
        route_policy: Optional[Dict[str, Any]] = None,
    ):
        return types.SimpleNamespace(
            hits=[],
            selected_hits=[],
            internal_hits=[],
            retrieval_errors={},
            source_tiers={},
            external_search={
                "attempted": False,
                "reason": external_search_reason,
                "provider": None,
                "query": None,
                "hit_count_pre_filter": 0,
                "hit_count_post_filter": 0,
                "fetched_url_count": 0,
            },
            retrieval_snapshot={
                "query": query,
                "prompt_category": prompt_category,
                "needs_authoritative_sources": needs_authoritative_sources,
                "source_policy": source_policy,
                "route_policy": route_policy or {},
                "response_mode": response_mode,
                "request_deadline_exceeded": True,
                "attachment_context_status": str((attachment_context or {}).get("status") or "").strip() or None,
            },
        )

    async def _ensure_message_persisted(
        self,
        *,
        query: str,
        answer: Dict[str, Any],
        conversation_id: Optional[str],
        user_id: Optional[int],
        project_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if answer.get("message_id") and answer.get("conversation_id"):
            return answer

        text = str(answer.get("text") or "").strip()
        if not text:
            return answer

        project_id = None
        project_label = None
        if isinstance(project_context, dict):
            project_id = project_context.get("id") or project_context.get("project_id")
            project_label = project_context.get("label") or project_context.get("name") or project_context.get("title")

        resolved_conversation_id = answer.get("conversation_id") or conversation_id
        conv_uuid = _normalize_conversation_uuid(resolved_conversation_id)
        metadata = answer.get("metadata") if isinstance(answer.get("metadata"), dict) else {}

        if not answer.get("conversation_id"):
            conv_id = await add_message_to_conversation(
                conv_uuid,
                "user",
                query,
                user_id=user_id,
                project_id=project_id,
                project_label=project_label,
            )
        else:
            conv_id = conv_uuid
            if conv_id is None:
                conv_id = await add_message_to_conversation(
                    None,
                    "user",
                    query,
                    user_id=user_id,
                    project_id=project_id,
                    project_label=project_label,
                )

        persisted_conv_id, assistant_message_id = await add_message_to_conversation(
            conv_id,
            "assistant",
            text,
            user_id=user_id,
            project_id=project_id,
            project_label=project_label,
            summary_snapshot=metadata.get("grounded_summary"),
            highlights=metadata.get("grounded_highlights"),
            metadata=metadata,
            return_message_id=True,
        )
        answer["conversation_id"] = str(persisted_conv_id) if persisted_conv_id else None
        if assistant_message_id:
            answer["message_id"] = str(assistant_message_id)
        return answer
