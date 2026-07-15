from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...core.i18n import t
from ...pipelines.compose.composer import compose_answer
from ...schemas.ai import Hit


logger = logging.getLogger(__name__)


class GenerationService:
    """Generates a knowledge answer without creating ERP product facts."""

    async def generate(
        self,
        query: str,
        hits: List[Hit],
        *,
        conversation_id: Optional[str] = None,
        analysis_weight: float = 0.0,
        compact: bool = False,
        user_id: Optional[int] = None,
        summary: Optional[str] = None,
        alias_terms: Optional[List[str]] = None,
        intent_name: Optional[str] = None,
        prompt_category: Optional[str] = None,
        context_package: Optional[Dict[str, Any]] = None,
        project_context: Optional[Dict[str, Any]] = None,
        history_cutoff=None,
        guardrail_message: Optional[str] = None,
        language: Optional[str] = None,
        benchmark_trace: bool = False,
    ) -> Dict[str, Any]:
        hit_payload = [hit.model_dump() for hit in hits[:6]]
        try:
            result = await compose_answer(
                query,
                hit_payload,
                conversation_id=conversation_id,
                analysis_weight=analysis_weight,
                compact=compact,
                user_id=user_id,
                summary=summary,
                alias_terms=alias_terms,
                intent_name=intent_name,
                prompt_category=prompt_category or "general_chat",
                context_package=context_package,
                project_context=project_context,
                history_cutoff=history_cutoff,
                guardrail_message=guardrail_message,
                lang=language,
                benchmark_trace=benchmark_trace,
                persist=False,
            )
        except Exception as exc:
            logger.exception("Knowledge answer generation failed: %s", exc)
            failure_metadata = self._generation_failure_metadata(exc, language=language)
            return {
                "text": self._build_generation_failure_text(failure_metadata, language),
                "citations": [],
                "metadata": failure_metadata,
            }
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        metadata.setdefault("response_mode", "generated")
        result["metadata"] = metadata
        return result

    @staticmethod
    def _generation_failure_metadata(exc: Exception, *, language: Optional[str]) -> Dict[str, Any]:
        del language
        status = getattr(exc, "status", None)
        try:
            status = int(status) if status is not None else None
        except (TypeError, ValueError):
            status = None
        access_denied = status in {401, 403, 404}
        return {
            "response_mode": "generation_fallback",
            "generation_error": type(exc).__name__,
            "generation_error_status": status,
            "model_access_denied": access_denied,
            "fallback_applied": True,
            "model_generation_failed": True,
        }

    @staticmethod
    def _build_generation_failure_text(metadata: Dict[str, Any], language: Optional[str]) -> str:
        # Do not expose provider response bodies, model identifiers, or retry advice
        # that implies the user's question caused a service configuration failure.
        del metadata
        return t("chat_templates.generation_unavailable", language)

    @staticmethod
    def generate_authoritative_fail_closed(
        *,
        language: Optional[str],
        request_deadline_exceeded: bool = False,
    ) -> Dict[str, Any]:
        text = t(
            "ai.fail_closed.authoritative_timeout"
            if request_deadline_exceeded
            else "ai.fail_closed.authoritative_missing",
            language,
        )
        return {
            "text": text,
            "citations": [],
            "metadata": {
                "response_mode": "templated_fail_closed",
                "external_verification_unavailable": True,
            },
        }

    @staticmethod
    def generate_general_timeout_fallback(*, language: Optional[str]) -> Dict[str, Any]:
        normalized = str(language or "").lower()
        if normalized.startswith("zh"):
            text = "目前無法在時限內完成回答，請稍後再試；本次未產生任何即時或 ERP 事實。"
        elif normalized.startswith("ja"):
            text = "時間内に回答を完了できませんでした。しばらくしてから再試行してください。"
        else:
            text = "The answer could not be completed within the time limit. Please try again shortly."
        return {
            "text": text,
            "citations": [],
            "metadata": {"response_mode": "templated_general_timeout"},
        }
