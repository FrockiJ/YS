from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from ...core.chat_history import get_messages_by_conversation


_TOPIC_SHIFT_RE = re.compile(
    r"(?:換個話題|改問|不談這個|重新開始|另外一題|instead|change\s+topic|new\s+topic)",
    re.IGNORECASE,
)
_FOLLOWUP_RE = re.compile(
    r"^(?:那|那麼|所以|為什麼|怎麼做|更便宜|不要|改成|繼續|what\s+about|why|how|instead)",
    re.IGNORECASE,
)
_CONTEXT_METADATA_ALLOWLIST = {
    "knowledge",
    "product_bridge",
    "product_results",
    "language",
    "lang",
    "project",
    "routing_path",
    "intent",
    "intent_task_type",
    "intent_decision",
}


class ContextCoreService:
    async def build(
        self,
        *,
        query: str,
        conversation_id: Optional[str],
        project_context: Optional[Dict[str, Any]],
        behavior_profile: Dict[str, Any],
        analysis: Any,
        user_id: Optional[int] = None,
        followup_context: Optional[Dict[str, Any]] = None,
        persisted_context_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        del user_id
        messages = await self._load_messages(conversation_id)
        recent = messages[-12:]
        topic_shift = bool(_TOPIC_SHIFT_RE.search(str(query or "")))
        followup_type = "new_question"
        if not topic_shift and (_FOLLOWUP_RE.search(str(query or "").strip()) or followup_context):
            followup_type = "same_subject_followup"
        generic_hints = self._generic_hints(getattr(analysis, "entity_hints", {}) or {})
        project_profile = self._project_profile(project_context)
        context_state = {
            "resolved": bool(recent or project_profile),
            "current_user_goal": str(query or "").strip(),
            "recent_summary": [
                {
                    "role": str(item.get("role") or ""),
                    "content": str(item.get("content") or "")[:1200],
                }
                for item in recent
                if str(item.get("content") or "").strip()
            ],
            "recent_summary_used": bool(recent),
            "active_topic": {} if topic_shift else generic_hints,
            "followup_type": followup_type,
            "protected_entities": {} if topic_shift else generic_hints,
            "topic_shift_detected": topic_shift,
            "project_profile": project_profile,
            "project_profile_used": bool(project_profile),
            "related_conversation_summaries": [],
            "related_conversation_count": 0,
            "behavior_profile": dict(behavior_profile or {}),
            "source_policy": (behavior_profile or {}).get("source_policy"),
            "citation_rule": (behavior_profile or {}).get("citation_rule"),
        }
        persisted = persisted_context_state if isinstance(persisted_context_state, dict) else {}
        trip_plan = persisted.get("trip_plan") if isinstance(persisted.get("trip_plan"), dict) else None
        if trip_plan:
            context_state["trip_plan"] = dict(trip_plan)
        sections: List[Dict[str, Any]] = []
        if context_state["recent_summary"]:
            sections.append({"name": "recent_conversation", "items": context_state["recent_summary"]})
        if project_profile:
            sections.append({"name": "project", "items": project_profile})
        if generic_hints:
            sections.append({"name": "entities", "items": generic_hints})
        if trip_plan:
            sections.append({"name": "trip_plan", "items": trip_plan})
        return {
            "context_state": context_state,
            "context_package": {
                "sections": sections,
                "text": self._render_sections(sections),
            },
        }

    async def _load_messages(self, conversation_id: Optional[str]) -> List[Dict[str, Any]]:
        if not conversation_id:
            return []
        try:
            identifier = uuid.UUID(str(conversation_id))
        except (TypeError, ValueError, AttributeError):
            return []
        try:
            messages = await get_messages_by_conversation(identifier, include_metadata=True)
        except Exception:
            return []
        result: List[Dict[str, Any]] = []
        for message in messages:
            item = dict(message)
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            item["metadata"] = {
                key: value
                for key, value in metadata.items()
                if key in _CONTEXT_METADATA_ALLOWLIST
                and (key != "intent" or str(value or "") in {"FREE_CHAT", "PRODUCT_RECOMMENDATION"})
            }
            result.append(item)
        return result

    @staticmethod
    def _generic_hints(values: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"brand", "product_name", "category", "specification", "location", "activity"}
        return {
            key: value
            for key, value in values.items()
            if key in allowed and value not in (None, "", [], {})
        }

    @staticmethod
    def _project_profile(project_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(project_context, dict):
            return {}
        customer = project_context.get("customer_profile") if isinstance(project_context.get("customer_profile"), dict) else {}
        return {
            key: value
            for key, value in {
                "id": project_context.get("id") or project_context.get("project_id"),
                "name": project_context.get("name") or project_context.get("label"),
                "customer_type": customer.get("customer_type"),
                "preference_note": customer.get("preference_note"),
                "region": customer.get("region"),
                "avg_unit_price": customer.get("avg_unit_price"),
            }.items()
            if value not in (None, "")
        }

    @staticmethod
    def _render_sections(sections: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for section in sections:
            lines.append(f"[{section.get('name')}]")
            items = section.get("items")
            if isinstance(items, list):
                lines.extend(f"- {item.get('role')}: {item.get('content')}" for item in items if isinstance(item, dict))
            elif isinstance(items, dict):
                lines.extend(f"- {key}: {value}" for key, value in items.items())
        return "\n".join(lines)
