import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, or_, select

from ...core.chat_history import get_messages_by_conversation
from ...core.database import SessionLocal
from ...core.models import Conversation, Message
from ...models.project import Project


FOLLOWUP_TOKENS = {
    "承上": "same_subject_followup",
    "上題": "same_subject_followup",
    "上题": "same_subject_followup",
    "前題": "same_subject_followup",
    "前题": "same_subject_followup",
    "剛剛": "same_subject_followup",
    "刚刚": "same_subject_followup",
    "為什麼": "same_subject_followup",
    "为什么": "same_subject_followup",
    "為何": "same_subject_followup",
    "why": "same_subject_followup",
    "原因": "same_subject_followup",
    "來源": "source_challenge",
    "引用": "source_challenge",
    "source": "source_challenge",
    "citation": "source_challenge",
    "reference": "source_challenge",
    "分數": "same_subject_followup",
    "評分": "same_subject_followup",
    "score": "same_subject_followup",
    "rating": "same_subject_followup",
    "比較": "same_subject_followup",
    "差異": "same_subject_followup",
    "compare": "same_subject_followup",
    "vs": "same_subject_followup",
    "短一點": "rewrite",
    "簡短": "rewrite",
    "精簡": "rewrite",
    "shorter": "rewrite",
    "換一批": "quote_revision",
    "看更多": "quote_revision",
    "補滿": "quote_revision",
    "類似": "quote_revision",
}

CONTEXTUAL_FOLLOWUP_PATTERNS = (
    r"^(?:why|how|source|citation|reference|compare|vs)\b",
    r"^(?:為什麼|為何|原因|來源|引用|比較|差異|承上|上題|剛剛)",
    r"^(?:那|那個|這個|這款|這支|這瓶|它|他|她|其實這個)",
    r"^(?:換一批|看更多|補滿|類似|短一點|簡短|精簡)",
    r"^(?:what about|how about|and what about|tell me more about)\b",
)

TOPIC_SHIFT_RE = re.compile(
    r"(?:不是|不要|改問|改成|換成|改查|其實我是想要|instead|not\s+.+,\s+ask|change\s+to)",
    re.IGNORECASE,
)

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
    ) -> Dict[str, Any]:
        messages = await self._load_messages(conversation_id)
        project_profile = await self._load_project_profile(project_context, user_id=user_id)
        related_summaries = await self._load_related_summaries(
            conversation_id=conversation_id,
            project_context=project_context,
            project_profile=project_profile,
            user_id=user_id,
        )
        context_state = self._build_context_state(
            query=query,
            messages=messages,
            project_profile=project_profile,
            related_summaries=related_summaries,
            behavior_profile=behavior_profile,
            analysis=analysis,
            followup_context=followup_context or {},
        )
        return {
            "context_state": context_state,
            "context_package": self._build_context_package(
                query=query,
                context_state=context_state,
                behavior_profile=behavior_profile,
            ),
        }

    async def _load_messages(self, conversation_id: Optional[str]) -> List[Dict[str, Any]]:
        if not conversation_id:
            return []
        try:
            conv_uuid = uuid.UUID(str(conversation_id))
        except (ValueError, TypeError, AttributeError):
            return []
        try:
            return await get_messages_by_conversation(conv_uuid, include_metadata=True)
        except Exception:
            return []

    async def _load_project_profile(
        self,
        project_context: Optional[Dict[str, Any]],
        *,
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        project_id = str((project_context or {}).get("id") or (project_context or {}).get("project_id") or "").strip()
        fallback_profile = self._project_profile_from_payload(project_context)
        if not project_id:
            return fallback_profile
        try:
            async with SessionLocal() as session:
                stmt = select(Project).where(Project.id == project_id, Project.is_archived.is_(False))
                if user_id is not None:
                    stmt = stmt.where(or_(Project.owner_user_id == user_id, Project.visibility == "public"))
                result = await session.execute(stmt)
                project = result.scalar_one_or_none()
                if not project:
                    return fallback_profile
                return {
                    "id": project.id,
                    "name": project.name,
                    "visibility": project.visibility,
                    "customer_type": project.customer_type,
                    "trade_count": project.trade_count,
                    "last_trade_at": project.last_trade_at.isoformat() if project.last_trade_at else None,
                    "avg_unit_price": project.avg_unit_price,
                    "preference_note": project.preference_note,
                    "region": project.region,
                    "has_wine_cabinet": project.has_wine_cabinet,
                }
        except Exception:
            return fallback_profile

    @staticmethod
    def _project_profile_from_payload(project_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(project_context, dict):
            return {}
        profile = project_context.get("customer_profile") if isinstance(project_context.get("customer_profile"), dict) else {}
        payload = {
            "id": project_context.get("id") or project_context.get("project_id"),
            "name": project_context.get("label") or project_context.get("name") or project_context.get("title"),
        }
        for key in ("customer_type", "trade_count", "last_trade_at", "avg_unit_price", "preference_note", "region", "has_wine_cabinet"):
            value = profile.get(key) if isinstance(profile, dict) else None
            if value not in (None, "", [], {}):
                payload[key] = value
        return {k: v for k, v in payload.items() if v not in (None, "", [], {})}

    async def _load_related_summaries(
        self,
        *,
        conversation_id: Optional[str],
        project_context: Optional[Dict[str, Any]],
        project_profile: Dict[str, Any],
        user_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        project_id = str((project_context or {}).get("id") or (project_context or {}).get("project_id") or "").strip()
        if not project_id and project_profile:
            project_id = str(project_profile.get("id") or "").strip()
        conv_uuid = None
        if conversation_id:
            try:
                conv_uuid = uuid.UUID(str(conversation_id))
            except (ValueError, TypeError, AttributeError):
                conv_uuid = None
        try:
            async with SessionLocal() as session:
                filters = [Conversation.is_archived.is_(False)]
                if conv_uuid is not None:
                    filters.append(Conversation.id != conv_uuid)
                if user_id is not None:
                    filters.append(Conversation.user_id == user_id)
                if project_id:
                    filters.append(Conversation.project_id == project_id)
                else:
                    return []
                stmt = (
                    select(Conversation.id, Conversation.title, Message.summary_snapshot, Message.content, Message.message_metadata)
                    .join(Message, Message.conversation_id == Conversation.id)
                    .where(*filters, Message.role == "assistant")
                    .order_by(desc(Conversation.updated_at), desc(Message.created_at))
                    .limit(12)
                )
                result = await session.execute(stmt)
                summaries: List[Dict[str, Any]] = []
                seen: set[str] = set()
                for conv_id, title, summary, content, metadata in result.all():
                    conv_key = str(conv_id)
                    if conv_key in seen:
                        continue
                    if self._metadata_is_bad(metadata):
                        continue
                    text = self._clip_summary(summary or content, limit=180)
                    if not text:
                        continue
                    seen.add(conv_key)
                    summaries.append({"conversation_id": conv_key, "title": title, "summary": text})
                    if len(summaries) >= 5:
                        break
                return summaries
        except Exception:
            return []

    def _build_context_state(
        self,
        *,
        query: str,
        messages: List[Dict[str, Any]],
        project_profile: Dict[str, Any],
        related_summaries: List[Dict[str, Any]],
        behavior_profile: Dict[str, Any],
        analysis: Any,
        followup_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        recent_summary = self._build_recent_summary(messages)
        conversation_memory = self._build_conversation_memory(messages)
        followup_type = self._detect_followup_type(query, followup_context=followup_context)
        topic_shift = self._detect_topic_shift(query)
        active_topic = self._build_active_topic(
            analysis,
            followup_context,
            topic_shift_detected=topic_shift,
            followup_type=followup_type,
        )
        protected = self._build_protected_entities(
            active_topic,
            followup_context,
            topic_shift_detected=topic_shift,
            followup_type=followup_type,
        )
        return {
            "resolved": bool(recent_summary or active_topic or project_profile or related_summaries),
            "current_user_goal": self._clip_summary(query, limit=220),
            "recent_summary": recent_summary,
            "recent_summary_used": bool(recent_summary),
            "conversation_memory": conversation_memory,
            "conversation_memory_used": bool(conversation_memory),
            "active_topic": active_topic,
            "followup_type": followup_type,
            "protected_entities": protected,
            "topic_shift_detected": topic_shift,
            "project_profile": project_profile,
            "project_profile_used": bool(project_profile),
            "related_conversation_summaries": related_summaries[:5],
            "related_conversation_count": len(related_summaries[:5]),
            "behavior_profile": behavior_profile,
            "source_policy": behavior_profile.get("source_policy"),
            "citation_rule": behavior_profile.get("citation_rule"),
        }

    def _build_recent_summary(self, messages: List[Dict[str, Any]]) -> List[str]:
        summary: List[str] = []
        for message in (messages or [])[-10:]:
            role = str(message.get("role") or "").strip().lower()
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            if role == "assistant" and self._metadata_is_bad(metadata):
                continue
            text = message.get("summary_snapshot") or message.get("summary") or message.get("content")
            clipped = self._clip_summary(text, limit=180)
            if not clipped:
                continue
            prefix = "User" if role == "user" else "Assistant"
            line = f"{prefix}: {clipped}"
            if line not in summary:
                summary.append(line)
            if len(summary) >= 10:
                break
        return summary

    def _build_conversation_memory(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        memory: List[Dict[str, Any]] = []
        for message in reversed(messages or []):
            role = str(message.get("role") or "").strip().lower()
            if role != "assistant":
                continue
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            if self._metadata_is_bad(metadata):
                continue
            if not self._metadata_is_memory_eligible(metadata):
                continue
            anchor = metadata.get("context_anchor") if isinstance(metadata.get("context_anchor"), dict) else {}
            citation_validation = (
                metadata.get("citation_validation")
                if isinstance(metadata.get("citation_validation"), dict)
                else {}
            )
            source_refs = anchor.get("source_references") if isinstance(anchor.get("source_references"), list) else []
            quote_items = metadata.get("quote_items") if isinstance(metadata.get("quote_items"), list) else []
            cerp_results = metadata.get("cerp_results") if isinstance(metadata.get("cerp_results"), dict) else {}
            subjects = anchor.get("subjects") if isinstance(anchor.get("subjects"), list) else []
            if not (subjects or source_refs or quote_items or cerp_results):
                continue
            memory.append(
                {
                    "subjects": subjects[:4],
                    "topic_type": anchor.get("topic_type") or metadata.get("prompt_category"),
                    "source_references": source_refs[:4],
                    "citation_validation": {
                        "citation_count": citation_validation.get("citation_count"),
                        "unmapped_citation_count": citation_validation.get("unmapped_citation_count"),
                    },
                    "quote_item_count": len(quote_items),
                    "cerp_proof_count": (cerp_results or {}).get("proof_count"),
                    "summary": self._clip_summary(
                        message.get("summary_snapshot") or message.get("summary") or message.get("content"),
                        limit=160,
                    ),
                }
            )
            if len(memory) >= 5:
                break
        return list(reversed(memory))

    @staticmethod
    def _metadata_is_memory_eligible(metadata: Any) -> bool:
        if not isinstance(metadata, dict):
            return False
        if str(metadata.get("answer_verification_mode") or "").strip() == "assisted_general_answer":
            return False
        evidence_contract = metadata.get("evidence_contract") if isinstance(metadata.get("evidence_contract"), dict) else {}
        claim_validation = metadata.get("claim_validation") if isinstance(metadata.get("claim_validation"), dict) else {}
        cerp_results = metadata.get("cerp_results") if isinstance(metadata.get("cerp_results"), dict) else {}
        official_binding = metadata.get("official_inventory_binding") if isinstance(metadata.get("official_inventory_binding"), dict) else {}
        has_cerp_proof = int(cerp_results.get("proof_count") or official_binding.get("proof_count") or 0) > 0
        contract_pass = str(evidence_contract.get("status") or "").strip() == "pass"
        claim_ok = str(claim_validation.get("status") or "pass").strip() in {"pass", "skipped_fail_closed", "no_high_risk_claims"}
        return has_cerp_proof or (contract_pass and claim_ok)

    @staticmethod
    def _metadata_is_bad(metadata: Any) -> bool:
        if not isinstance(metadata, dict):
            return False
        flags = metadata.get("hard_error_flags") or []
        if isinstance(flags, str):
            flags = [flags]
        if any(str(flag or "").strip() for flag in flags):
            return True
        claim_validation = metadata.get("claim_validation") if isinstance(metadata.get("claim_validation"), dict) else {}
        if str(claim_validation.get("status") or "").strip() in {"failed_authoritative", "failed", "warning"}:
            return True
        if claim_validation.get("unsupported_claim_count"):
            return True
        citation_validation = metadata.get("citation_validation") if isinstance(metadata.get("citation_validation"), dict) else {}
        if citation_validation.get("unmapped_citation_count"):
            return True
        evidence_contract = metadata.get("evidence_contract") if isinstance(metadata.get("evidence_contract"), dict) else {}
        cerp_results = metadata.get("cerp_results") if isinstance(metadata.get("cerp_results"), dict) else {}
        has_cerp_proof = int(cerp_results.get("proof_count") or 0) > 0
        contract_status = str(evidence_contract.get("status") or "").strip()
        if evidence_contract and contract_status not in {"pass", "no_evidence"} and not has_cerp_proof:
            return True
        return str(metadata.get("response_mode") or "").strip() in {
            "templated_fail_closed",
            "templated_internal_low_coverage",
            "generation_fallback",
        }

    @staticmethod
    def _clip_summary(value: Any, *, limit: int) -> str:
        text = " ".join(str(value or "").replace("\n", " ").split()).strip()
        if not text:
            return ""
        return text if len(text) <= limit else text[:limit].rstrip() + "..."

    @staticmethod
    def _detect_followup_type(query: str, *, followup_context: Dict[str, Any]) -> str:
        if not followup_context and not query:
            return "new_question"
        if not followup_context.get("resolved"):
            return "new_question"
        lowered = str(query or "").lower()
        if ContextCoreService._looks_like_contextual_followup(str(query or "")):
            for token, kind in FOLLOWUP_TOKENS.items():
                if token.lower() in lowered:
                    return kind
            return "ambiguous"
        return "new_question"

    @staticmethod
    def _looks_like_contextual_followup(query: str) -> bool:
        normalized = " ".join(str(query or "").replace("\n", " ").split()).strip()
        if not normalized:
            return False
        lowered = normalized.casefold()
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in CONTEXTUAL_FOLLOWUP_PATTERNS):
            return True
        if len(normalized.split()) <= 4 and any(token in lowered for token in ("this", "that", "it", "這", "那", "其實")):
            return True
        return False

    @staticmethod
    def _detect_topic_shift(query: str) -> bool:
        return bool(TOPIC_SHIFT_RE.search(str(query or "")))

    @staticmethod
    def _build_active_topic(
        analysis: Any,
        followup_context: Dict[str, Any],
        *,
        topic_shift_detected: bool,
        followup_type: str,
    ) -> Dict[str, Any]:
        hints = dict(getattr(analysis, "entity_hints", {}) or {})
        if not hints and followup_type != "new_question" and isinstance(followup_context.get("entity_hints"), dict):
            hints = dict(followup_context.get("entity_hints") or {})
        if (
            followup_type != "new_question"
            and not topic_shift_detected
            and isinstance(followup_context.get("entity_hints"), dict)
        ):
            for key, value in followup_context["entity_hints"].items():
                if value not in (None, "", [], {}) and hints.get(key) in (None, "", [], {}):
                    hints[key] = value
        return {key: value for key, value in hints.items() if value not in (None, "", [], {})}

    @staticmethod
    def _build_protected_entities(
        active_topic: Dict[str, Any],
        followup_context: Dict[str, Any],
        *,
        topic_shift_detected: bool,
        followup_type: str,
    ) -> Dict[str, Any]:
        if topic_shift_detected or followup_type == "new_question":
            return {}
        protected = dict(followup_context.get("protected_entity_hints") or {})
        for key in ("producer", "wine", "wine_name", "full_wine_name", "vineyard", "region", "vintage", "color", "color_scope"):
            value = active_topic.get(key)
            if value not in (None, "", [], {}) and protected.get(key) in (None, "", [], {}):
                protected[key] = value
        return protected

    def _build_context_package(
        self,
        *,
        query: str,
        context_state: Dict[str, Any],
        behavior_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        lines: List[str] = [
            f"Current user goal: {self._clip_summary(query, limit=220)}",
            f"Follow-up type: {context_state.get('followup_type')}",
            f"Topic shift detected: {context_state.get('topic_shift_detected')}",
            f"Source policy: {behavior_profile.get('source_policy')}",
            f"Citation rule: {behavior_profile.get('citation_rule')}",
        ]
        if context_state.get("protected_entities"):
            lines.append(f"Protected entities: {context_state['protected_entities']}")
        if context_state.get("recent_summary"):
            lines.append("Recent conversation summary:")
            lines.extend(f"- {item}" for item in context_state["recent_summary"][:10])
        if context_state.get("conversation_memory"):
            lines.append("Structured conversation memory:")
            for item in context_state["conversation_memory"][:5]:
                lines.append(f"- {item}")
        if context_state.get("project_profile"):
            lines.append(f"Project/customer profile: {context_state['project_profile']}")
        if context_state.get("related_conversation_summaries"):
            lines.append("Related prior summaries:")
            for item in context_state["related_conversation_summaries"][:5]:
                lines.append(f"- {item.get('title') or item.get('conversation_id')}: {item.get('summary')}")
        return {
            "sections": lines,
            "text": "\n".join(lines),
        }
