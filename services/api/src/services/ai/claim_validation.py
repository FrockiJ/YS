from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from ...schemas.ai import Hit


AUTHORITATIVE_CATEGORIES = {
    "source_validation",
    "critic_score_lookup",
    "exact_review_lookup",
    "book_corpus_lookup",
    "multi_review_compare",
    "source_hierarchy_conflict",
    "internal_rag_only_validation",
    "alias_inventory_equivalence",
}
HIGH_RISK_PATTERNS = (
    re.compile(r"\b(?:1[89]|20)\d{2}\b"),
    re.compile(r"\b\d{2,3}(?:\.\d)?\s*(?:points?|pts|分)\b", re.IGNORECASE),
    re.compile(r"\b(?:score|rating|評分|评分|分數|分数)\b", re.IGNORECASE),
    re.compile(r"\b(?:burghound|jasper|vinous|parker|wine advocate|spectator|decanter)\b", re.IGNORECASE),
    re.compile(r"\b(?:sku|cerp|庫存|库存|現貨|现货|可售|售價|售价|價格|价格|vip|stock|price)\b", re.IGNORECASE),
    re.compile(r"(?:NT\$|\$|USD|TWD)\s*\d", re.IGNORECASE),
    re.compile(r"\b(?:page|p\.|頁|页|row|source|citation|來源|来源|引用)\b", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
)
CRITICAL_UNSUPPORTED_PATTERNS = (
    re.compile(r"\b\d{2,3}(?:\.\d)?\s*(?:points?|pts|分)\b", re.IGNORECASE),
    re.compile(r"\b(?:score|rating|評分|评分|分數|分数)\b", re.IGNORECASE),
    re.compile(r"\b(?:sku|cerp|庫存|库存|現貨|现货|可售|售價|售价|價格|价格|vip|stock|price)\b", re.IGNORECASE),
    re.compile(r"(?:NT\$|\$|USD|TWD)\s*\d", re.IGNORECASE),
    re.compile(r"\b(?:page|p\.|頁|页|row)\s*[:#]?\s*\d+\b", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
)
NON_ASSERTIVE_MARKERS = (
    "does not include",
    "not include",
    "could not find",
    "cannot reliably",
    "can't reliably",
    "will not guess",
    "if you want",
    "if you have",
    "once you provide",
    "insufficient data",
    "no matching",
    "no verified",
    "not found",
    "not retrieved",
    "not verified",
    "not available",
    "missing from",
    "missing in",
    "not in the authorized corpus",
    "not in authorized corpus",
    "not invent",
    "manual comparison",
    "沒有找到",
    "没有找到",
    "無法可靠",
    "无法可靠",
    "不能可靠",
    "不會猜",
    "不会猜",
    "資料不足",
    "资料不足",
    "沒有符合",
    "没有符合",
)
FAIL_CLOSED_MODES = {
    "templated_fail_closed",
    "templated_general_timeout",
    "templated_internal_low_coverage",
    "generation_fallback",
    "answerable_with_gaps",
}


class ClaimValidationService:
    def validate(
        self,
        *,
        answer_text: str,
        metadata: Dict[str, Any],
        hits: Sequence[Hit] | Sequence[Dict[str, Any]] | None = None,
        prompt_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        response_mode = str((metadata or {}).get("response_mode") or "").strip()
        if response_mode in FAIL_CLOSED_MODES:
            return {
                "status": "skipped_fail_closed",
                "supported_claim_count": 0,
                "unsupported_claim_count": 0,
                "unsupported_claims": [],
                "evidence_trace_ids": self._evidence_trace_ids(metadata, hits),
            }

        claims = self._extract_claims(answer_text)
        high_risk_claims = [claim for claim in claims if self._is_high_risk(claim)]
        evidence_traces = self._evidence_trace_ids(metadata, hits)
        evidence_text = self._evidence_text(metadata, hits)
        supported: List[str] = []
        unsupported: List[str] = []
        for claim in high_risk_claims:
            if self._is_non_assertive_or_structural(claim):
                continue
            if self._cerp_claim_supported(claim, metadata):
                supported.append(claim)
                continue
            if self._licensed_review_claim_supported(claim, metadata):
                supported.append(claim)
                continue
            if self._claim_supported(claim, evidence_text, evidence_traces):
                supported.append(claim)
            else:
                unsupported.append(claim)

        category = str(prompt_category or metadata.get("prompt_category") or "").strip()
        authoritative = bool(
            metadata.get("needs_authoritative_sources")
            or category in AUTHORITATIVE_CATEGORIES
            or str((metadata.get("evidence_contract") or {}).get("evidence_type") or "") in {"licensed_review", "book_ocr", "source_hierarchy", "cerp_snapshot"}
        )
        status = "pass"
        if unsupported:
            critical_unsupported = [claim for claim in unsupported if self._is_critical_unsupported(claim)]
            status = "failed_authoritative" if authoritative and critical_unsupported else "warning"
        return {
            "status": status,
            "supported_claim_count": len(supported),
            "unsupported_claim_count": len(unsupported),
            "unsupported_claims": unsupported[:12],
            "evidence_trace_ids": evidence_traces,
        }

    @staticmethod
    def _extract_claims(text: str) -> List[str]:
        normalized = str(text or "").replace("\r", "\n")
        parts = re.split(r"[\n。！？!?；;]+", normalized)
        claims: List[str] = []
        for part in parts:
            cleaned = re.sub(r"^\s*[-*•\d.)、]+", "", part).strip()
            if len(cleaned) < 4:
                continue
            claims.append(cleaned[:400])
        return claims[:30]

    @staticmethod
    def _is_high_risk(claim: str) -> bool:
        return any(pattern.search(claim or "") for pattern in HIGH_RISK_PATTERNS)

    @staticmethod
    def _is_critical_unsupported(claim: str) -> bool:
        return any(pattern.search(claim or "") for pattern in CRITICAL_UNSUPPORTED_PATTERNS)

    @staticmethod
    def _is_non_assertive_or_structural(claim: str) -> bool:
        raw = str(claim or "").strip()
        if raw.startswith("#") or raw.startswith("|"):
            return True
        lowered = raw.casefold()
        normalized = re.sub(r"[*_`~]+", "", lowered)
        normalized = re.sub(r"\s+", " ", normalized)
        if "cerp reference" in normalized or "source reference" in normalized:
            return True
        return any(marker in normalized for marker in NON_ASSERTIVE_MARKERS)

    @staticmethod
    def _cerp_claim_supported(claim: str, metadata: Dict[str, Any]) -> bool:
        lowered = str(claim or "").casefold()
        if not re.search(r"\b(?:sku|cerp|庫存|库存|現貨|现货|可售|售價|售价|價格|价格|vip|stock|price)\b", lowered, re.IGNORECASE):
            return False
        cerp_results = metadata.get("cerp_results") if isinstance(metadata.get("cerp_results"), dict) else {}
        official_binding = metadata.get("official_inventory_binding") if isinstance(metadata.get("official_inventory_binding"), dict) else {}
        return int(cerp_results.get("proof_count") or official_binding.get("proof_count") or 0) > 0

    @staticmethod
    def _licensed_review_claim_supported(claim: str, metadata: Dict[str, Any]) -> bool:
        lowered = str(claim or "").casefold()
        if not re.search(r"\b(?:score|rating|points?|pts|評分|评分|分數|分数|分)\b", lowered, re.IGNORECASE):
            return False
        evidence_contract = metadata.get("evidence_contract") if isinstance(metadata.get("evidence_contract"), dict) else {}
        if str(evidence_contract.get("evidence_type") or "") not in {"licensed_review", "source_hierarchy"}:
            return False
        if str(evidence_contract.get("status") or "") not in {"pass", "partial_pass"}:
            return False
        validation = metadata.get("citation_validation") if isinstance(metadata.get("citation_validation"), dict) else {}
        for item in validation.get("items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("auditable") and item.get("source_family") == "licensed_review_dataset":
                return True
        return False

    @classmethod
    def _claim_supported(cls, claim: str, evidence_text: str, evidence_traces: Sequence[str]) -> bool:
        lowered_claim = str(claim or "").casefold()
        if not lowered_claim:
            return True
        if any(trace and trace.casefold() in lowered_claim for trace in evidence_traces):
            return True
        tokens = cls._tokens(lowered_claim)
        if not tokens:
            return True
        evidence = evidence_text.casefold()
        numeric_tokens = [token for token in tokens if re.fullmatch(r"\d+(?:\.\d+)?", token)]
        text_tokens = [token for token in tokens if not re.fullmatch(r"\d+(?:\.\d+)?", token)]
        if numeric_tokens and not any(token in evidence for token in numeric_tokens):
            return False
        meaningful = [token for token in text_tokens if len(token) >= 4][:6]
        if not meaningful:
            return bool(numeric_tokens)
        matches = sum(1 for token in meaningful if token in evidence)
        return matches >= min(2, len(meaningful))

    @staticmethod
    def _tokens(text: str) -> List[str]:
        stop = {
            "this", "that", "with", "from", "have", "has", "and", "the", "for", "about",
            "score", "rating", "points", "price", "stock", "source", "review", "wine",
        }
        tokens: List[str] = []
        for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", text.casefold()):
            if token in stop:
                continue
            if token not in tokens:
                tokens.append(token)
        return tokens

    @classmethod
    def _evidence_trace_ids(
        cls,
        metadata: Dict[str, Any],
        hits: Sequence[Hit] | Sequence[Dict[str, Any]] | None = None,
    ) -> List[str]:
        traces: List[str] = []
        for item in cls._evidence_items(metadata, hits):
            trace = str(item.get("source_trace") or item.get("id") or item.get("url") or "").strip()
            if trace and trace not in traces:
                traces.append(trace)
        return traces[:20]

    @classmethod
    def _evidence_text(
        cls,
        metadata: Dict[str, Any],
        hits: Sequence[Hit] | Sequence[Dict[str, Any]] | None = None,
    ) -> str:
        parts: List[str] = []
        for item in cls._evidence_items(metadata, hits):
            for key in ("source_trace", "claim", "excerpt", "text", "summary", "producer", "name", "wine_name", "vintage", "score", "sku", "code", "price", "vip_price", "stock"):
                value = item.get(key)
                if value not in (None, "", [], {}):
                    parts.append(str(value))
        return " ".join(parts)

    @staticmethod
    def _evidence_items(
        metadata: Dict[str, Any],
        hits: Sequence[Hit] | Sequence[Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        answer_plan = metadata.get("answer_plan") if isinstance(metadata.get("answer_plan"), dict) else {}
        for item in answer_plan.get("items") or []:
            if isinstance(item, dict):
                items.append(dict(item))
        for claim in answer_plan.get("allowed_claims") or []:
            if isinstance(claim, dict):
                items.append(dict(claim))
            elif str(claim or "").strip():
                items.append({"claim": str(claim)})
        for citation in metadata.get("citations") or []:
            if isinstance(citation, dict):
                meta = citation.get("meta") if isinstance(citation.get("meta"), dict) else {}
                items.append({**citation, **meta})
        cerp_results = metadata.get("cerp_results") if isinstance(metadata.get("cerp_results"), dict) else {}
        for item in cerp_results.get("items") or []:
            if isinstance(item, dict):
                items.append(dict(item))
        validation = metadata.get("citation_validation") if isinstance(metadata.get("citation_validation"), dict) else {}
        for item in validation.get("items") or []:
            if isinstance(item, dict):
                items.append(dict(item))
        for hit in hits or []:
            if isinstance(hit, Hit):
                payload = hit.model_dump()
            else:
                payload = dict(hit or {})
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            items.append({**payload, **meta})
        return items
