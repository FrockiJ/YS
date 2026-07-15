from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ...schemas.ai import AnalysisResult, Intent


_CURRENT_FACT_RE = re.compile(
    r"(?:最新|目前|現在|即時|今天|本週|本月|查證|核實|官方|規範|法規|公告|警報|"
    r"天氣|氣象|路況|封閉|開放|安全|風險|current|latest|today|this\s+week|"
    r"verify|fact[- ]?check|official|regulation|rule|warning|alert|weather|"
    r"road\s+condition|closure|open|safety)",
    re.IGNORECASE,
)

_OUTDOOR_RE = re.compile(
    r"(?:登山|健行|露營|溯溪|釣魚|戶外|步道|山屋|帳篷|睡袋|雨衣|裝備|"
    r"hiking|trekking|camping|climbing|trail|mountain|outdoor|tent|sleeping\s+bag|gear)",
    re.IGNORECASE,
)

_LOCATION_ADVICE_RE = re.compile(
    r"(?:玉山|雪山|合歡山|阿里山|太魯閣|陽明山|國家公園|步道|山區|"
    r"mountain|national\s+park|trail|route|location|地點|路線)",
    re.IGNORECASE,
)


class AnalysisService:
    """Domain-neutral request analysis for the Knowledge-First chat flow."""

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
        hints = self._generic_entity_hints(attachment_context)
        reason = self._determine_authoritative_reason(text, "general_chat", bool(urls))
        return AnalysisResult(
            intent=Intent(name="FREE_CHAT", slots={}),
            query_variants=[text] if text else [],
            alias_filters={},
            entity_hints=hints,
            entity_resolution={},
            followup_context={},
            attachment_context=attachment_context,
            url_lookup={"urls": urls, "status": "provided" if urls else "not_requested"},
            url_inputs=urls,
            primary_url=urls[0] if urls else None,
            url_input_source="structured" if urls else None,
            lookup_goal="verify_provided_sources" if urls else None,
            retrieval_query=text,
            prompt_category="general_chat",
            needs_authoritative_sources=bool(reason),
            authoritative_reason=reason,
        )

    @staticmethod
    def _normalize_urls(values: Optional[List[str]]) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values or []:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
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
            current.get("summary")
            or current.get("text")
            or current.get("filename")
            or ""
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
        aliases = {
            "brand": ("brand", "manufacturer", "supplier"),
            "product_name": ("product_name", "product", "name", "title"),
            "category": ("category", "product_category", "type"),
            "specification": ("specification", "spec", "model", "size"),
            "location": ("location", "area", "place"),
        }
        result: Dict[str, Any] = {}
        for target, keys in aliases.items():
            for key in keys:
                value = payload.get(key)
                if value not in (None, "", [], {}):
                    result[target] = value
                    break
        nested = payload.get("entity_hints")
        if isinstance(nested, dict):
            for key in aliases:
                if key not in result and nested.get(key) not in (None, "", [], {}):
                    result[key] = nested[key]
        return result

    @staticmethod
    def _determine_authoritative_reason(
        text: str,
        prompt_category: str = "general_chat",
        has_urls: bool = False,
    ) -> Optional[str]:
        del prompt_category
        if has_urls:
            return "provided_url_verification"
        if _CURRENT_FACT_RE.search(str(text or "")):
            return "time_sensitive_location_regulation_or_safety"
        return None

    @staticmethod
    def _looks_like_outdoor_advice_query(text: str) -> bool:
        return bool(_OUTDOOR_RE.search(str(text or "")))

    @staticmethod
    def _looks_like_outdoor_location_advice_query(text: str) -> bool:
        value = str(text or "")
        return bool(_OUTDOOR_RE.search(value) or _LOCATION_ADVICE_RE.search(value))
