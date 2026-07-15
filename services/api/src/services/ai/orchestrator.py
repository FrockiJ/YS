from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from ...core.chat_history import add_message_to_conversation
from ...schemas.ai import ChatResponse
from .analysis import AnalysisService
from .behavior_profiles import get_behavior_profile
from .claim_validation import ClaimValidationService
from .context_core import ContextCoreService
from .generation import GenerationService
from .grounding import GroundingService
from .retrieval import RetrievalService


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
        **_: Any,
    ) -> None:
        self._analysis = analysis_service or AnalysisService()
        self._retrieval = retrieval_service or RetrievalService()
        self._generation = generation_service or GenerationService()
        self._grounding = grounding_service or GroundingService()
        self._context = context_core_service or ContextCoreService()
        self._claim_validation = claim_validation_service or ClaimValidationService()

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
        analysis.prompt_category = str(prompt_category_override or "general_chat").strip() or "general_chat"
        analysis_ms = round((time.perf_counter() - analysis_started) * 1000, 1)

        authoritative = (
            analysis.needs_authoritative_sources
            if needs_authoritative_sources is None
            else bool(needs_authoritative_sources)
        )
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
        retrieval = await self._retrieval.search(
            str(retrieval_query_override or analysis.retrieval_query or query),
            query_variants=analysis.query_variants,
            entity_hints=analysis.entity_hints,
            prompt_category=analysis.prompt_category,
            intent_name=analysis.intent.name,
            needs_authoritative_sources=authoritative,
            source_policy=resolved_source_policy,
            external_search_reason=external_reason,
            context_state=context_state,
        )
        retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000, 1)

        generation_started = time.perf_counter()
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
        validation = self._claim_validation.validate(
            answer_text=str(grounded.get("text") or ""),
            metadata=grounded_metadata,
            hits=retrieval.selected_hits or retrieval.hits,
            prompt_category=analysis.prompt_category,
        )
        grounded_metadata["claim_validation"] = validation
        if validation.get("unsupported_claim_count"):
            grounded["text"] = self._operational_fact_limit_text(language)
            grounded["citations"] = []
            grounded_metadata["operational_fact_blocked"] = True

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

    @staticmethod
    def _operational_fact_limit_text(language: Optional[str]) -> str:
        normalized = str(language or "").lower()
        if normalized.startswith("zh"):
            return "此回答涉及未經 ERP 驗證的商品、價格或庫存事實，因此未予輸出；請改用 YS 商品推薦查詢。"
        if normalized.startswith("ja"):
            return "ERP で確認できない商品・価格・在庫情報が含まれるため出力しません。YS 商品検索をご利用ください。"
        return "This answer contained product, price, or stock facts not verified by ERP, so they were withheld. Use YS product recommendations instead."
