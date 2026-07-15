from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ...schemas.ai import AnalysisResult, Hit


class GroundingService:
    """Keeps citations tied to retrieved hits without replacing the generated answer."""

    def post_process(
        self,
        *,
        query: str,
        answer: Dict[str, Any],
        hits: Sequence[Hit],
        analysis: AnalysisResult,
        language: Optional[str] = None,
        attachment: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized = dict(answer or {})
        metadata = dict(normalized.get("metadata") or {})
        available = [hit.model_dump() for hit in hits]
        available_by_id = {str(item.get("id")): item for item in available if item.get("id") is not None}
        citations_were_supplied = isinstance(normalized.get("citations"), list)
        requested = normalized.get("citations") if citations_were_supplied else []
        citations: List[Dict[str, Any]] = []
        seen = set()
        for record in requested:
            if not isinstance(record, dict):
                continue
            identifier = str(record.get("id") or "")
            matched = available_by_id.get(identifier) if identifier else None
            if matched is None:
                continue
            if identifier in seen:
                continue
            seen.add(identifier)
            citations.append(matched)
        if not citations_were_supplied and available:
            citations = available[:6]

        authoritative = [
            item
            for item in citations
            if str(item.get("source_tier") or (item.get("meta") or {}).get("source_tier") or "")
            in {"external_evidence", "internal_official", "internal_approved"}
        ]
        fallback_applied = False
        if analysis.needs_authoritative_sources and not authoritative:
            # Missing live evidence is metadata for the final LLM to disclose at
            # claim scope. It must never replace an otherwise useful answer.
            fallback_applied = False

        summaries: List[str] = []
        for item in citations[:4]:
            value = str(item.get("summary") or item.get("text") or "").strip()
            if value:
                summaries.append(value[:180])
        metadata.update(
            {
                "grounded_summary": summaries[0] if summaries else "",
                "grounded_highlights": summaries,
                "source_tier": list(
                    dict.fromkeys(
                        str(item.get("source_tier") or (item.get("meta") or {}).get("source_tier") or "internal")
                        for item in citations
                    )
                ),
                "confidence": "grounded" if citations else "general_knowledge",
                "attachment_ingested": bool(attachment),
                "attachment_context": analysis.attachment_context or {},
                "grounding": {
                    "pre_guardrail_hit_count": len(requested),
                    "post_guardrail_hit_count": len(citations),
                    "fallback_applied": fallback_applied,
                    "guardrail_flags": ["missing_authoritative_source"] if fallback_applied else [],
                },
                "citation_validation": {
                    "input_citation_count": len(requested),
                    "mapped_citation_count": len(citations),
                    "post_guardrail_citation_count": len(citations),
                    "unmapped_citation_count": max(len(requested) - len(citations), 0),
                    "all_citations_mapped": len(requested) == len(citations),
                },
                "hard_error_flags": [],
            }
        )
        normalized["citations"] = citations
        normalized["metadata"] = metadata
        return normalized
