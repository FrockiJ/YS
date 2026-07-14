from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from ...core.i18n import t


RESTRICTED_FIELD_RE = re.compile(
    r"\b(cost|margin|supplier payment terms?|payment terms?|landed cost|gross margin)\b|成本|毛利|供應商付款|付款條件",
    re.IGNORECASE,
)
BUSINESS_METRIC_RE = re.compile(
    r"sales velocity|depletion|allocation|next order|reorder|overstock|recent sales|銷售速度|去化|配額|下次訂貨|補貨|庫存週轉",
    re.IGNORECASE,
)
PROMPT_INJECTION_RE = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions|reveal\s+(?:the\s+)?(?:entire\s+)?(?:imported\s+)?(?:review\s+)?database|dump\s+(?:the\s+)?database|忽略(?:所有)?(?:先前|之前)指令|揭露.*資料庫|匯出.*資料庫)",
    re.IGNORECASE,
)

SENSITIVE_PERMISSION = "cerp.sensitive.read"
BUSINESS_METRIC_PERMISSION = "business.metrics.read"


def user_has_permission(user: Optional[Dict[str, Any]], permission_code: str) -> bool:
    permissions = (user or {}).get("permissions") if isinstance(user, dict) else []
    if not isinstance(permissions, Iterable) or isinstance(permissions, (str, bytes)):
        return False
    normalized = {str(item).strip() for item in permissions if str(item).strip()}
    return permission_code in normalized


def _build_deterministic_trace(
    *,
    query: str,
    answer: str,
    metadata: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    return {
        "trace_kind": "deterministic_guardrail",
        "llm_called": False,
        "generation_type": "permission_guardrail",
        "no_llm_reason": reason,
        "llm_request_payload": {
            "mode": "no_llm_call",
            "reason": reason,
            "messages": [],
        },
        "llm_request_messages": [],
        "llm_model_attempted": None,
        "llm_response_json": {
            "mode": "deterministic",
            "text": answer,
        },
        "llm_raw_response": answer,
        "retrieval_context": {
            "query": query,
            "selected_hits": [],
            "retrieval_snapshot": {
                "response_mode": metadata.get("response_mode"),
                "missing_permissions": metadata.get("missing_permissions") or [],
                "hard_error_flags": metadata.get("hard_error_flags") or [],
            },
        },
        "final_response_json": {
            "text": answer,
            "citations": [],
            "metadata": {key: value for key, value in metadata.items() if key != "benchmark_trace"},
        },
        "trace_status": "captured",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def build_guardrail_response(
    query: str,
    user: Optional[Dict[str, Any]],
    *,
    language: str,
    benchmark_trace: bool = False,
) -> Optional[Dict[str, Any]]:
    text = str(query or "")
    prompt_injection = bool(PROMPT_INJECTION_RE.search(text))
    if prompt_injection:
        answer = t("ai.fail_closed.prompt_injection", language)
        metadata = {
            "response_mode": "templated_fail_closed",
            "answer_mode": "fail_closed",
            "answer_verification_mode": "data_or_permission_needed",
            "answer_verification": {
                "mode": "data_or_permission_needed",
                "verified": False,
                "requires_disclaimer": False,
                "reason": "prompt_injection_guardrail",
            },
            "substantive_answer": False,
            "hard_error_flags": ["prompt_injection_blocked"],
            "fail_closed_reason": "prompt_injection_guardrail",
            "citation_validation": {
                "citation_count": 0,
                "unmapped_citation_count": 0,
                "hard_error_flags": ["prompt_injection_blocked"],
            },
        }
        if benchmark_trace:
            metadata["benchmark_trace"] = _build_deterministic_trace(
                query=text,
                answer=answer,
                metadata=metadata,
                reason="prompt_injection_guardrail",
            )
        return {
            "ok": True,
            "kind": "chat",
            "intent": {"name": "SECURITY_GUARDRAIL"},
            "answer": {"text": answer, "citations": [], "metadata": metadata},
            "content": answer,
            "language": language,
        }
    return None


def build_benchmark_contract_response(
    query: str,
    *,
    language: str,
    benchmark_case_id: str,
    evidence_contract: str,
    reason: str,
) -> Dict[str, Any]:
    answer = t(
        "ai.fail_closed.benchmark_source_contract_missing",
        language,
        case_id=benchmark_case_id,
        evidence_contract=evidence_contract or "required evidence",
    )
    metadata = {
        "response_mode": "templated_fail_closed",
        "answer_mode": "fail_closed",
        "answer_verification_mode": "data_or_permission_needed",
        "answer_verification": {
            "mode": "data_or_permission_needed",
            "verified": False,
            "requires_disclaimer": False,
            "reason": reason,
        },
        "substantive_answer": False,
        "benchmark_case_id": benchmark_case_id,
        "evidence_type": evidence_contract,
        "source_policy": "internal_preferred",
        "controlling_source": {},
        "fail_closed_reason": reason,
        "hard_error_flags": [reason],
        "citation_validation": {
            "citation_count": 0,
            "unmapped_citation_count": 0,
            "missing_required_metadata_count": 0,
            "hard_error_flags": [reason],
        },
        "retrieval_snapshot": {
            "query": query,
            "response_mode": "templated_fail_closed",
            "benchmark_case_id": benchmark_case_id,
            "evidence_type": evidence_contract,
            "retrieval_decision": {
                "rejected_reasons": [reason],
                "hard_error_flags": [reason],
            },
        },
    }
    metadata["benchmark_trace"] = _build_deterministic_trace(
        query=query,
        answer=answer,
        metadata=metadata,
        reason=reason,
    )
    metadata["benchmark_trace"]["generation_type"] = "templated_fail_closed"
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "BENCHMARK_CONTRACT_FAIL_CLOSED"},
        "answer": {"text": answer, "citations": [], "metadata": metadata},
        "content": answer,
        "language": language,
    }
