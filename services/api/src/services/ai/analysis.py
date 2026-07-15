from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...schemas.ai import AnalysisResult, Intent


class AnalysisService:
    """Normalizes attachments and URLs; semantic planning belongs to the LLM planner."""

    async def analyze(
        self,
        query: str,
        *,
        conn: Any = None,
        attachment: Optional[Dict[str, Any]] = None,
        prior_attachment_context: Optional[Dict[str, Any]] = None,
        url_inputs: Optional[List[str]] = None,
    ) -> AnalysisResult:
        del conn
        text = str(query or "").strip()
        urls = self._normalize_urls(url_inputs)
        attachment_context = self._attachment_context(attachment, prior_attachment_context)
        return AnalysisResult(
            intent=Intent(name="FREE_CHAT", slots={}),
            query_variants=[text] if text else [],
            entity_hints=self._generic_entity_hints(attachment_context),
            attachment_context=attachment_context,
            url_lookup={"urls": urls, "status": "provided" if urls else "not_requested"},
            url_inputs=urls,
            primary_url=urls[0] if urls else None,
            url_input_source="structured" if urls else None,
            lookup_goal="verify_provided_sources" if urls else None,
            retrieval_query=text,
            prompt_category="general_chat",
            needs_authoritative_sources=bool(urls),
            authoritative_reason="provided_url_verification" if urls else None,
        )

    @staticmethod
    def _normalize_urls(values: Optional[List[str]]) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values or []:
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result[:10]

    @staticmethod
    def _attachment_context(
        attachment: Optional[Dict[str, Any]],
        prior: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        current = dict(attachment) if isinstance(attachment, dict) else {}
        previous = dict(prior) if isinstance(prior, dict) else {}
        if not current:
            return previous
        summary = str(
            current.get("summary") or current.get("text") or current.get("filename") or ""
        ).strip()
        return {
            "status": "analyzed" if summary else "provided",
            "summary": summary[:2000],
            "filename": str(current.get("filename") or current.get("name") or "").strip(),
            "mime": str(current.get("mime") or current.get("content_type") or "").strip(),
            "entity_hints": AnalysisService._generic_entity_hints(current),
        }

    @staticmethod
    def _generic_entity_hints(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        fields = {
            "brand": ("brand", "manufacturer", "supplier"),
            "product_name": ("product_name", "product", "name", "title"),
            "category": ("category", "product_category", "type"),
            "specification": ("specification", "spec", "model", "size"),
            "location": ("location", "area", "place"),
        }
        result: Dict[str, Any] = {}
        for target, keys in fields.items():
            for key in keys:
                value = payload.get(key)
                if value not in (None, "", [], {}):
                    result[target] = value
                    break
        nested = payload.get("entity_hints")
        if isinstance(nested, dict):
            for key in fields:
                if key not in result and nested.get(key) not in (None, "", [], {}):
                    result[key] = nested[key]
        return result
