from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from ...core.chat_history import add_message_to_conversation
from ...schemas.ai import ChatResponse
from ...pipelines.llm.openai_client import LLMRequestBudget
from .analysis import AnalysisService
from .behavior_profiles import get_behavior_profile
from .claim_validation import ClaimValidationService
from .context_core import ContextCoreService
from .generation import GenerationService
from .grounding import GroundingService
from .retrieval import RetrievalService
from .chat_planner import ChatExecutionPlan
from .final_answer import FinalAnswerService


class ChatOrchestrator:
    """Single Knowledge-First execution path for normal chat requests."""

    def __init__(
        self,
        analysis_service: Optional[AnalysisService] = None,
        retrieval_service: Optional[RetrievalService] = None,
        generation_service: Optional[GenerationService] = None,
        grounding_service: Optional[GroundingService] = None,
        context_core_service: Optional[ContextCoreService] = None,
        claim_validation_service: Optional[ClaimValidationService] = None,
        final_answer_service: Optional[FinalAnswerService] = None,
        **_: Any,
    ) -> None:
        self._analysis = analysis_service or AnalysisService()
        self._retrieval = retrieval_service or RetrievalService()
        self._generation = generation_service or GenerationService()
        self._grounding = grounding_service or GroundingService()
        self._context = context_core_service or ContextCoreService()
        self._claim_validation = claim_validation_service or ClaimValidationService()
        self._final_answer = final_answer_service or FinalAnswerService()

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
        persisted_context_state: Optional[Dict[str, Any]] = None,
        retrieval_query_override: Optional[str] = None,
        execution_plan: Optional[ChatExecutionPlan] = None,
        erp_result: Optional[Dict[str, Any]] = None,
        llm_budget: Optional[LLMRequestBudget] = None,
        planning_history: Optional[list[Dict[str, Any]]] = None,
    ) -> ChatResponse:
        del store_profile, request_deadline_seconds
        started = time.perf_counter()
        analysis_started = time.perf_counter()
        analysis = await self._analysis.analyze(
            query,
            attachment=attachment,
            prior_attachment_context=prior_attachment_context,
            url_inputs=url_inputs,
        )
        if execution_plan is not None:
            analysis.intent.name = {
                "erp_lookup": "ERP_PRODUCT_FACT_LOOKUP",
                "product_recommendation": "PRODUCT_RECOMMENDATION",
                "mixed": "MIXED_KNOWLEDGE_ERP",
                "destination": "DESTINATION_GUIDANCE",
            }.get(execution_plan.task_type, "FREE_CHAT")
        analysis.prompt_category = str(prompt_category_override or "general_chat").strip() or "general_chat"
        analysis_ms = round((time.perf_counter() - analysis_started) * 1000, 1)

        authoritative = (
            analysis.needs_authoritative_sources
            if needs_authoritative_sources is None
            else bool(needs_authoritative_sources)
        )
        if execution_plan is not None:
            authoritative = bool(execution_plan.external.required or url_inputs)
        analysis.needs_authoritative_sources = authoritative
        resolved_source_policy = str(source_policy or "").strip() or (
            "authoritative_external_required" if authoritative else "internal_preferred"
        )
        external_reason = authoritative_reason_override or analysis.authoritative_reason
        behavior_profile = get_behavior_profile(analysis.prompt_category)
        context_package = await self._context.build(
            query=query,
            conversation_id=conversation_id,
            project_context=project_context,
            behavior_profile=behavior_profile,
            analysis=analysis,
            user_id=user_id,
            followup_context=analysis.followup_context,
            persisted_context_state=persisted_context_state,
        )
        context_state = context_package.get("context_state") if isinstance(context_package.get("context_state"), dict) else {}

        retrieval_started = time.perf_counter()
        planned_queries = list(execution_plan.rag_queries) if execution_plan is not None else []
        retrieval_query = str(
            (planned_queries[0] if planned_queries else None)
            or retrieval_query_override
            or analysis.retrieval_query
            or query
        )
        retrieval = await self._retrieval.search(
            retrieval_query,
            query_variants=(planned_queries[1:] if planned_queries else analysis.query_variants),
            entity_hints=analysis.entity_hints,
            prompt_category=analysis.prompt_category,
            intent_name=analysis.intent.name,
            needs_authoritative_sources=authoritative,
            source_policy=resolved_source_policy,
            external_search_reason=external_reason,
            external_query=(execution_plan.external.query if execution_plan is not None else None),
            context_state=context_state,
            external_on_rag_miss=True,
        )
        retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000, 1)

        generation_started = time.perf_counter()
        if execution_plan is not None and llm_budget is not None:
            try:
                final = await self._final_answer.generate(
                    query,
                    plan=execution_plan,
                    hits=retrieval.selected_hits or retrieval.hits,
                    external_status=retrieval.external_search,
                    erp_result=erp_result,
                    history=planning_history,
                    language=language,
                    budget=llm_budget,
                )
            except Exception as exc:
                fallback_text = str((erp_result or {}).get("text") or "").strip()
                if not fallback_text:
                    fallback_text = self._generation._build_generation_failure_text({}, language)
                final = {
                    "text": fallback_text,
                    "citations": [],
                    "answer_sections": [{"type": "erp" if erp_result else "knowledge", "text": fallback_text}],
                    "claim_validation": {
                        "status": "generation_failed",
                        "supported_claim_count": 0,
                        "unsupported_claim_count": 0,
                        "unsupported_claims": [],
                        "row_proof_count": len((erp_result or {}).get("row_proofs") or []),
                        "error": type(exc).__name__,
                    },
                }
            generated = {
                "text": final["text"],
                "citations": final["citations"],
                "metadata": {
                    "response_mode": "generated",
                    "answer_sections": final["answer_sections"],
                    "claim_validation": final["claim_validation"],
                    "used_rag_hit_count": sum(
                        1 for item in final["citations"] if str(item.get("source_type") or "") != "external_search"
                    ),
                    "used_external_hit_count": sum(
                        1 for item in final["citations"] if str(item.get("source_type") or "") == "external_search"
                    ),
                },
            }
        else:
            generated = await self._generation.generate(
                query,
                retrieval.selected_hits or retrieval.hits,
                conversation_id=conversation_id,
                analysis_weight=analysis_weight,
                compact=compact,
                user_id=user_id,
                intent_name=analysis.intent.name,
                prompt_category=analysis.prompt_category,
                context_package=context_package.get("context_package") if isinstance(context_package, dict) else {},
                project_context=project_context,
                history_cutoff=history_cutoff,
                language=language,
                benchmark_trace=benchmark_trace,
            )
        generation_ms = round((time.perf_counter() - generation_started) * 1000, 1)

        metadata = generated.get("metadata") if isinstance(generated.get("metadata"), dict) else {}
        metadata.update(
            {
                "intent": analysis.intent.name,
                "prompt_category": analysis.prompt_category,
                "source_policy": resolved_source_policy,
                "needs_authoritative_sources": authoritative,
                "authoritative_reason": external_reason,
                "entity_hints": analysis.entity_hints,
                "context_state": context_state,
                "retrieval_snapshot": retrieval.retrieval_snapshot,
                "external_search": retrieval.external_search,
                "retrieval_errors": retrieval.retrieval_errors,
                "rag_status": retrieval.retrieval_snapshot.get("rag_status"),
                "rag_hit_count": retrieval.retrieval_snapshot.get("rag_hit_count", 0),
                "response_mode": str(metadata.get("response_mode") or "generated"),
            }
        )
        if execution_plan is not None:
            metadata["execution_plan"] = execution_plan.audit_metadata()
            metadata["retrieval"] = {
                "rag_queries": list(execution_plan.rag_queries),
                "external_query": execution_plan.external.query,
            }
            metadata["llm_budget"] = (llm_budget or LLMRequestBudget()).snapshot()
            if isinstance(erp_result, dict):
                metadata["erp_query"] = dict(erp_result.get("erp_query") or {})
                metadata["erp_lookup"] = dict(erp_result.get("erp_lookup") or {})
                metadata["product_results"] = list(erp_result.get("product_results") or [])
                metadata["erp_snapshot_timestamp"] = metadata["erp_query"].get("timestamp")
        generated["metadata"] = metadata

        grounding_started = time.perf_counter()
        grounded = self._grounding.post_process(
            query=query,
            answer=generated,
            hits=retrieval.selected_hits or retrieval.hits,
            analysis=analysis,
            language=language,
            attachment=attachment,
        )
        grounding_ms = round((time.perf_counter() - grounding_started) * 1000, 1)
        grounded_metadata = grounded.get("metadata") if isinstance(grounded.get("metadata"), dict) else metadata
        if execution_plan is None:
            validation = self._claim_validation.validate(
                answer_text=str(grounded.get("text") or ""),
                metadata=grounded_metadata,
                hits=retrieval.selected_hits or retrieval.hits,
                prompt_category=analysis.prompt_category,
            )
            grounded_metadata["claim_validation"] = validation

        project_id = project_context.get("id") if isinstance(project_context, dict) else None
        project_label = (
            project_context.get("label") or project_context.get("name")
            if isinstance(project_context, dict)
            else None
        )
        conv_uuid = self._conversation_uuid(conversation_id)
        conv_id = await add_message_to_conversation(
            conv_uuid,
            "user",
            query,
            user_id=user_id,
            project_id=project_id,
            project_label=project_label,
        )
        grounded_metadata["timing"] = {
            "analysis_ms": analysis_ms,
            "retrieval_ms": retrieval_ms,
            "generation_ms": generation_ms,
            "grounding_ms": grounding_ms,
            "total_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        _, assistant_message_id = await add_message_to_conversation(
            conv_id,
            "assistant",
            str(grounded.get("text") or ""),
            user_id=user_id,
            project_id=project_id,
            project_label=project_label,
            metadata=grounded_metadata,
            return_message_id=True,
        )
        grounded.update(
            {
                "conversation_id": str(conv_id),
                "message_id": str(assistant_message_id),
                "metadata": grounded_metadata,
            }
        )
        return ChatResponse(
            ok=True,
            kind="chat",
            intent=analysis.intent,
            answer=grounded,
            context=retrieval.selected_hits or retrieval.hits,
            content=str(grounded.get("text") or ""),
            language=language,
            project=project_context,
        )

    @staticmethod
    def _conversation_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
        if not value:
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return None
