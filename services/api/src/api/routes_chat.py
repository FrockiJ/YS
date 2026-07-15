from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Optional, List, Dict, Any
import asyncio
import traceback
from urllib.error import HTTPError
from datetime import datetime, timezone
import re
import uuid
import json
import logging
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.sql import func

from ..core import db
from ..core.auth import get_current_user_optional
from ..core.database import SessionLocal
from ..core.chat_history import (
    add_message_to_conversation,
    find_conversation_by_project,
    list_conversations_by_user,
    update_message_enrichment,
    get_messages_by_conversation,
    get_message_in_conversation,
    find_product_bridge_response,
    get_conversation_meta,
    merge_conversation_context_state,
    update_conversation_label,
    update_conversation_customer,
    update_conversation_visibility,
    update_conversation_project,
    archive_conversation,
    restore_conversation,
)
from ..core.store_profile import get_store_profile
from ..core.i18n import t, normalize_lang
from ..core.models import Conversation
from ..core.module_registry import is_module_enabled
from ..pipelines.nlp.embedder import (
    EmbeddingUnavailableError,
    embed_texts,
    embedding_dimension,
    embedding_model_name,
    embedding_provider_name,
)
from ..pipelines.rag.searcher import (
    rag_corpus_status,
    vector_search as _vector_search,
    structured_search as _structured_search,
)
from ..pipelines.rag.query_rewrite import expand_aliases as _expand_aliases
from ..pipelines.compose.composer import compose_answer as _compose_answer
from ..pipelines.compose.generator import generate_answer as _generate_summary
from .routes_cerp import CERPClientError
from ..models.customer import Customer
from ..models.project import Project
from ..services.ai.benchmark_guardrails import build_guardrail_response
from ..services.ai.orchestrator import ChatOrchestrator
from ..services.ai.retrieval import RetrievalService
from ..services.ai.product_need_extractor import ProductNeedResult, NEED_PROFILE_VERSION
from ..services.ai.product_bridge import ProductBridgeService
from ..services.ai.product_intent_analysis import merge_need_profile_patch
from ..services.ai.trip_plan import TripPlanService
from ..services.ai.chat_planner import ChatExecutionPlan, ChatPlanningService
from ..services.ai.erp_ast import ERPQueryExecutor
from ..pipelines.llm.openai_client import LLMRequestBudget
from ..services.project_service import can_read_conversation, can_write_conversation
from ..utils.lang import detect_lang

logger = logging.getLogger(__name__)

router = APIRouter()
retrieval_service = RetrievalService()
chat_orchestrator = ChatOrchestrator(retrieval_service=retrieval_service)
product_bridge_service = ProductBridgeService()
trip_plan_service = TripPlanService()
chat_planning_service = ChatPlanningService()
erp_query_executor = ERPQueryExecutor()
_MOJIBAKE_MARKER_RE = re.compile(r"[鈭鋆撅蝮銝摰憭靘隞嚗餈箏喲瑼]")
def _looks_like_mojibake_input(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    marker_count = len(_MOJIBAKE_MARKER_RE.findall(text))
    question_marks = text.count("?")
    han_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if marker_count >= 3 and (question_marks >= 1 or marker_count / max(han_count, 1) >= 0.2):
        return True
    if question_marks >= 4 and marker_count >= 1:
        return True
    return False


_TRACEBACK_PATTERN = re.compile(r"traceback\s*\(most recent call last\)", re.IGNORECASE)

def _resolve_lang(value: Optional[str]) -> str:
    return normalize_lang(value)


def _resolve_chat_language(text: str, raw_lang: Optional[str]) -> tuple[str, str, str]:
    requested_lang = _resolve_lang(raw_lang)
    detected_lang = _resolve_lang(detect_lang(text))
    return detected_lang, requested_lang, detected_lang


ADMIN_PROFILE = {
    "api_base": "/api",
    "admin_base": "/api/admin",
    "auth_flow_key": "admin.profile.auth_flow",
    "notes_key": "admin.profile.notes",
    "docs": [],
}

ADMIN_RESOURCES = {
    "users": {
        "id": "users",
        "label_key": "admin.resources.users.label",
        "description_key": "admin.resources.users.description",
        "paths": {
            "list": "/users/?skip=0&limit=50",
            "create": "/users/",
            "update": "/users/{id}",
            "delete": "/users/{id}",
        },
        "allowed_roles": ["admin", "SAdmin"],
        "columns": [
            {"id": "id", "label_key": "admin.resources.common.id"},
            {"id": "username", "label_key": "admin.resources.users.fields.username"},
            {"id": "role", "label_key": "admin.resources.users.fields.role"},
        ],
        "fields": [
            {
                "name": "username",
                "label_key": "admin.resources.users.fields.username",
                "required": True,
                "placeholder_key": "admin.resources.users.placeholders.username",
            },
            {
                "name": "password",
                "label_key": "admin.resources.users.fields.password",
                "required_on_create": True,
                "type": "password",
            },
            {
                "name": "role",
                "label_key": "admin.resources.users.fields.role",
                "type": "select",
                "default": "user",
                "source": "roles",
            },
        ],
        "actions": ["create", "read", "update", "delete"],
    },
    "roles": {
        "id": "roles",
        "label_key": "admin.resources.roles.label",
        "description_key": "admin.resources.roles.description",
        "paths": {
            "list": "/roles/?skip=0&limit=200",
            "create": "/roles/",
            "update": "/roles/{id}",
            "delete": "/roles/{id}",
        },
        "allowed_roles": ["SAdmin"],
        "columns": [
            {"id": "id", "label_key": "admin.resources.common.id"},
            {"id": "name", "label_key": "admin.resources.roles.fields.name"},
            {"id": "description", "label_key": "admin.resources.roles.fields.description"},
            {"id": "permissions", "label_key": "admin.resources.roles.fields.permissions"},
        ],
        "fields": [
            {
                "name": "name",
                "label_key": "admin.resources.roles.fields.name",
                "required": True,
                "placeholder_key": "admin.resources.roles.placeholders.name",
            },
            {
                "name": "description",
                "label_key": "admin.resources.roles.fields.description",
                "type": "textarea",
                "placeholder_key": "admin.resources.roles.placeholders.description",
            },
            {
                "name": "permissions",
                "label_key": "admin.resources.roles.fields.permissions",
                "type": "multiselect",
                "source": "permissions",
                "helper_key": "admin.resources.roles.helpers.permissions",
            },
        ],
        "actions": ["create", "read", "update", "delete"],
    },
    "permissions": {
        "id": "permissions",
        "label_key": "admin.resources.permissions.label",
        "description_key": "admin.resources.permissions.description",
        "paths": {
            "list": "/permissions/?skip=0&limit=200",
            "create": "/permissions/",
            "update": "/permissions/{id}",
            "delete": "/permissions/{id}",
        },
        "allowed_roles": ["SAdmin"],
        "columns": [
            {"id": "id", "label_key": "admin.resources.common.id"},
            {"id": "code", "label_key": "admin.resources.permissions.fields.code"},
            {"id": "scope", "label_key": "admin.resources.permissions.fields.scope"},
        ],
        "fields": [
            {
                "name": "code",
                "label_key": "admin.resources.permissions.fields.code",
                "required": True,
                "placeholder_key": "admin.resources.permissions.placeholders.code",
            },
            {
                "name": "scope",
                "label_key": "admin.resources.permissions.fields.scope",
                "placeholder_key": "admin.resources.permissions.placeholders.scope",
            },
            {
                "name": "description",
                "label_key": "admin.resources.permissions.fields.description",
                "type": "textarea",
                "placeholder_key": "admin.resources.permissions.placeholders.description",
            },
        ],
        "actions": ["create", "read", "update", "delete"],
    },
}

ADMIN_INTENT_COMMANDS = [
    {
        "command": "{l}",
        "label_key": "admin.commands.login.label",
        "description_key": "admin.commands.login.description",
    },
    {
        "command": "{lo}",
        "label_key": "admin.commands.logout.label",
        "description_key": "admin.commands.logout.description",
    },
    {
        "command": "{be}",
        "label_key": "admin.commands.backend.label",
        "description_key": "admin.commands.backend.description",
    },
    {
        "command": "compact toggle",
        "label_key": "admin.commands.compact.label",
        "description_key": "admin.commands.compact.description",
    },
]

ADMIN_CATEGORIES = [
    {
        "id": "management",
        "label_key": "admin.categories.management",
    }
]

class ConversationRenamePayload(BaseModel):
    label: Optional[str] = None
    customer_id: Optional[int] = None


class ConversationVisibilityPayload(BaseModel):
    visibility: str


class ConversationCustomerPayload(BaseModel):
    customer_id: str


class ConversationProjectPayload(BaseModel):
    project_id: Optional[str] = None


class CustomerSummary(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    cerp_id: Optional[str] = None
    tags: Optional[Any] = None


class ConversationMessagesResponse(BaseModel):
    ok: bool = True
    conversation_id: str
    project: Optional[Dict[str, Any]] = None
    messages: List[Dict[str, Any]]
    visibility: str
    customer: Optional[CustomerSummary] = None

class DebugRetrievePayload(BaseModel):
    query: str
    rag_k: Optional[int] = None
    cerp_limit: Optional[int] = None


class ProductRecommendationPayload(BaseModel):
    conversation_id: str
    source_message_id: str
    lang: Optional[str] = None


def _knowledge_contract(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    metadata = metadata if isinstance(metadata, dict) else {}
    snapshot = metadata.get("retrieval_snapshot") if isinstance(metadata.get("retrieval_snapshot"), dict) else {}
    selected_hits = int(
        metadata.get("used_rag_hit_count")
        if metadata.get("used_rag_hit_count") is not None
        else snapshot.get("rag_hit_count")
        if snapshot.get("rag_hit_count") is not None
        else (metadata.get("rag_hit_count") or 0)
    )
    rag_status = str(snapshot.get("rag_status") or metadata.get("rag_status") or "").strip()
    if rag_status not in {"empty_corpus", "no_relevant_hits", "used", "error"}:
        rag_status = "used" if selected_hits > 0 else "no_relevant_hits"

    external = metadata.get("external_search") if isinstance(metadata.get("external_search"), dict) else {}
    external_attempted = bool(
        external.get("attempted")
        or external.get("requested")
        or metadata.get("external_search_attempted")
    )
    external_hit_count = int(
        metadata.get("used_external_hit_count")
        if metadata.get("used_external_hit_count") is not None
        else external.get("hit_count_post_filter")
        or external.get("hit_count")
        or external.get("result_count")
        or 0
    )
    raw_external_status = str(external.get("status") or "").strip().lower()
    if not external_attempted:
        external_status = "not_attempted"
    elif external_hit_count > 0 or raw_external_status in {"used", "success", "grounded"}:
        external_status = "used"
    elif external.get("provider_unavailable") or raw_external_status in {"unavailable", "not_configured", "disabled"}:
        external_status = "unavailable"
    else:
        external_status = raw_external_status or "no_results"

    if external_status == "used":
        mode = "external_grounded"
    elif rag_status == "used" and selected_hits > 0:
        mode = "rag_grounded"
    else:
        mode = "llm_only"
    return {
        "mode": mode,
        "rag_status": rag_status,
        "rag_hit_count": selected_hits,
        "external_attempted": external_attempted,
        "external_status": external_status,
    }


def _product_bridge_metadata(
    result: ProductNeedResult,
    *,
    trigger: str,
    source_message_id: Optional[str] = None,
    fulfilled: bool = False,
    intent_source: Optional[str] = None,
    intent_confidence: Optional[float] = None,
    intent_task_type: Optional[str] = None,
    intent_decision: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {
        "eligible": bool(result.eligible),
        "trigger": trigger if result.eligible else "none",
        "need_profile_version": NEED_PROFILE_VERSION,
        "preview_categories": list(result.preview_categories),
        "source_message_id": source_message_id,
        "need_profile": dict(result.profile),
        "fulfilled": bool(fulfilled),
    }
    if intent_source:
        payload["intent_source"] = intent_source
    if intent_confidence is not None:
        payload["intent_confidence"] = round(float(intent_confidence), 3)
    if intent_task_type:
        payload["intent_task_type"] = intent_task_type
    if intent_decision:
        payload["intent_decision"] = intent_decision
    return payload


def _chat_response_from_persisted_bridge(message: Dict[str, Any], language: str) -> Dict[str, Any]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    answer = {
        "text": str(message.get("content") or ""),
        "citations": [],
        "conversation_id": message.get("conversation_id"),
        "message_id": message.get("id"),
        "metadata": metadata,
    }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "PRODUCT_RECOMMENDATION"},
        "answer": answer,
        "content": answer["text"],
        "language": language,
        "product_results": list(metadata.get("product_results") or []),
        "idempotent_replay": True,
    }


def _is_super_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    role = user.get("role")
    if not role:
        return False
    return str(role).strip().lower() == "sadmin"


async def _user_can_view_conversation(
    user: Optional[Dict[str, Any]],
    conversation: Dict[str, Any],
) -> bool:
    if not user or not user.get("id"):
        return False
    async with SessionLocal() as session:
        return await can_read_conversation(session, user, conversation)


def _require_conversation_owner(
    user: Optional[Dict[str, Any]],
    conversation: Dict[str, Any],
    lang: str,
) -> None:
    if not user or conversation.get("user_id") != user.get("id"):
        raise HTTPException(status_code=403, detail=t("errors.conversation_unavailable", lang))


async def _ensure_conversation_write_access(
    conversation_id: Optional[str],
    user: Optional[Dict[str, Any]],
    lang: str,
) -> None:
    if not conversation_id:
        return
    try:
        conv_uuid = uuid.UUID(str(conversation_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=t("errors.invalid_conversation_id", lang)) from exc
    conversation = await get_conversation_meta(conv_uuid)
    if not conversation:
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", lang))
    if conversation.get("is_archived"):
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", lang))
    async with SessionLocal() as session:
        if not await can_write_conversation(session, user, conversation):
            raise HTTPException(status_code=403, detail=t("errors.conversation_unavailable", lang))



async def vector_search(conn, q, k=8):
    owned_conn = None
    try:
        if conn is None:
            owned_conn = await db.get_conn()
            conn = owned_conn
        if conn is None:
            return []
        return await _vector_search(conn, q, k=k)  # type: ignore
    except Exception:
        return []
    finally:
        if owned_conn:
            await owned_conn.close()

async def structured_search(conn, filters, k=4):
    owned_conn = None
    try:
        if conn is None:
            owned_conn = await db.get_conn()
            conn = owned_conn
        if conn is None:
            return []
        return await _structured_search(conn, filters, k=k)  # type: ignore
    except Exception:
        return []
    finally:
        if owned_conn:
            await owned_conn.close()

async def expand_aliases(conn, query: str):
    owned_conn = None
    try:
        if conn is None:
            owned_conn = await db.get_conn()
            conn = owned_conn
        if conn is None:
            return [query], {}
        return await _expand_aliases(conn, query)  # type: ignore
    except Exception:
        return [query], {}
    finally:
        if owned_conn:
            await owned_conn.close()

def summarize_hits(query: str, hits, lang: str):
    try:
        return _generate_summary(query, hits, ctx={"language": lang}, lang=lang)  # type: ignore
    except Exception:
        return {}


def _localize_admin_resource(resource: Dict[str, Any], lang: str) -> Dict[str, Any]:
    localized = {k: v for k, v in resource.items() if not k.endswith("_key")}
    label_key = resource.get("label_key")
    description_key = resource.get("description_key")
    if label_key:
        localized["label"] = t(label_key, lang)
    if description_key:
        localized["description"] = t(description_key, lang)
    columns = []
    for col in resource.get("columns") or []:
        col_label = col.get("label")
        col_label_key = col.get("label_key")
        resolved = dict(col)
        if col_label_key:
            resolved["label"] = t(col_label_key, lang)
        elif col_label:
            resolved["label"] = col_label
        columns.append(resolved)
    localized["columns"] = columns
    fields = []
    for field in resource.get("fields") or []:
        resolved = dict(field)
        label_key = resolved.pop("label_key", None)
        placeholder_key = resolved.pop("placeholder_key", None)
        helper_key = resolved.pop("helper_key", None)
        if label_key:
            resolved["label"] = t(label_key, lang)
        if placeholder_key:
            resolved["placeholder"] = t(placeholder_key, lang)
        if helper_key:
            resolved["helper"] = t(helper_key, lang)
        fields.append(resolved)
    localized["fields"] = fields
    return localized


def build_admin_panel_payload(user: Dict[str, Any], lang: str) -> Dict[str, Any]:
    resources = {
        key: _localize_admin_resource(value, lang) for key, value in ADMIN_RESOURCES.items()
    }
    categories = []
    for category in ADMIN_CATEGORIES:
        label_key = category.get("label_key")
        categories.append(
            {
                "id": category.get("id"),
                "label": t(label_key, lang) if label_key else category.get("label"),
                "options": [
                    {"id": key, "label": resources[key]["label"], "target": key}
                    for key in resources
                ],
            }
        )
    intent_commands = []
    for cmd in ADMIN_INTENT_COMMANDS:
        intent_commands.append(
            {
                "command": cmd.get("command"),
                "label": t(cmd.get("label_key"), lang),
                "description": t(cmd.get("description_key"), lang),
            }
        )
    return {
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "operator": {
            "username": user.get("username") if isinstance(user, dict) else None,
            "role": user.get("role") if isinstance(user, dict) else None,
        },
        "profile": {
            "api_base": ADMIN_PROFILE["api_base"],
            "admin_base": ADMIN_PROFILE["admin_base"],
            "auth_flow": t(ADMIN_PROFILE["auth_flow_key"], lang),
            "notes": t(ADMIN_PROFILE["notes_key"], lang),
            "docs": ADMIN_PROFILE.get("docs", []),
        },
        "resources": resources,
        "intent_commands": intent_commands,
        "categories": categories,
    }

async def compose_answer(
    query: str,
    hits,
    conversation_id: Optional[str] = None,
    analysis_weight: float = 0.0,
    compact: bool = False,
    user_id: Optional[int] = None,
    summary: Optional[str] = None,
    alias_terms: Optional[List[str]] = None,
    intent_name: Optional[str] = None,
    project_context: Optional[Dict[str, Any]] = None,
    history_cutoff: Optional[datetime] = None,
    guardrail_message: Optional[str] = None,
    lang: Optional[str] = None,
):
    try:
        resolved_lang = _resolve_lang(lang)
        return await _compose_answer(
            query,
            hits,
            conversation_id=conversation_id,
            analysis_weight=analysis_weight,
            compact=compact,
            user_id=user_id,
            summary=summary,
            alias_terms=alias_terms,
            intent_name=intent_name,
            project_context=project_context,
            history_cutoff=history_cutoff,
            guardrail_message=guardrail_message,
            lang=resolved_lang,
        )  # type: ignore
    except HTTPError as e:
        error_body = e.read().decode("utf-8", "ignore")
        error_message = t("errors.openai_http_error", resolved_lang, code=e.code)
        try:
            error_json = __import__("json").loads(error_body)
            reason = error_json.get("error", {}).get("message", "")
            if reason:
                error_message += f" {t('errors.openai_reason', resolved_lang, reason=reason)}"
        except Exception:
            pass
        return {"text": error_message, "citations": []}
    except Exception as e:
        print(f"[compose_answer] error: {type(e).__name__}: {e}")
        traceback.print_exc()
        return {
            "text": t("errors.compose_failed", resolved_lang, error=type(e).__name__),
            "citations": [],
        }

@router.get("/chat/history")
async def chat_history(
    limit: int = 50,
    lang: Optional[str] = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    resolved_lang = _resolve_lang(lang)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail=t("errors.login_required", resolved_lang))
    safe_limit = max(1, min(limit, 200))
    items = await list_conversations_by_user(
        user.get("id"),
        user.get("role"),
        limit=safe_limit,
    )
    return {"ok": True, "items": items}

@router.get("/chat/history/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def conversation_messages(
    conversation_id: str,
    limit: int = 5,
    lang: Optional[str] = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    resolved_lang = _resolve_lang(lang)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail=t("errors.login_required", resolved_lang))
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=t("errors.invalid_conversation_id", resolved_lang))
    conversation = await get_conversation_meta(conv_uuid)
    if not conversation:
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", resolved_lang))
    if conversation.get("is_archived") and not _is_super_admin_user(user):
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", resolved_lang))
    if not await _user_can_view_conversation(user, conversation):
        raise HTTPException(status_code=403, detail=t("errors.conversation_unavailable", resolved_lang))
    messages = await get_messages_by_conversation(conv_uuid, include_metadata=True)
    clamped = max(1, min(limit, 20))
    window = clamped * 2
    if window < len(messages):
        messages = messages[-window:]
    project_payload = None
    project_id = conversation.get("project_id")
    project_label = conversation.get("project_label") or conversation.get("title")
    if project_id or project_label:
        project_payload = {
            "id": project_id,
            "label": project_label,
        }
    return {
        "ok": True,
        "conversation_id": str(conv_uuid),
        "project": project_payload,
        "messages": messages,
        "visibility": conversation.get("visibility") or "private",
        "customer": conversation.get("customer"),
    }


@router.patch("/chat/history/{conversation_id}/customer")
async def conversation_customer_link(
    conversation_id: str,
    payload: ConversationCustomerPayload,
    lang: Optional[str] = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    resolved_lang = _resolve_lang(lang)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail=t("errors.login_required", resolved_lang))
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=t("errors.invalid_conversation_id", resolved_lang))
    conversation = await get_conversation_meta(conv_uuid)
    if not conversation:
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", resolved_lang))
    _require_conversation_owner(user, conversation, resolved_lang)

    async with SessionLocal() as session:
        customer_result = await session.execute(
            select(Customer).where(Customer.id == payload.customer_id)
        )
        customer = customer_result.scalars().first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        await session.execute(
            update(Conversation)
            .where(Conversation.id == conv_uuid)
            .values(customer_id=payload.customer_id, updated_at=func.now())
        )
        await session.commit()

        return {
            "ok": True,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "phone": customer.phone,
                "cerp_id": customer.cerp_id,
                "tags": customer.tags,
            },
        }

@router.patch("/chat/history/{conversation_id}")
async def conversation_rename(
    conversation_id: str,
    payload: ConversationRenamePayload,
    lang: Optional[str] = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    resolved_lang = _resolve_lang(lang)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail=t("errors.login_required", resolved_lang))
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=t("errors.invalid_conversation_id", resolved_lang))
    conversation = await get_conversation_meta(conv_uuid)
    if not conversation:
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", resolved_lang))
    _require_conversation_owner(user, conversation, resolved_lang)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail=t("errors.label_required", resolved_lang))
    if "label" in updates:
        new_label = (payload.label or "").strip()
        if not new_label:
            raise HTTPException(status_code=422, detail=t("errors.label_required", resolved_lang))
        updated = await update_conversation_label(conv_uuid, new_label)
        if not updated:
            raise HTTPException(status_code=500, detail=t("errors.rename_failed", resolved_lang))
    if "customer_id" in updates:
        updated = await update_conversation_customer(conv_uuid, payload.customer_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Customer not found")
    return {"ok": True, "label": payload.label}


@router.patch("/chat/history/{conversation_id}/visibility")
async def conversation_visibility(
    conversation_id: str,
    payload: ConversationVisibilityPayload,
    lang: Optional[str] = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    resolved_lang = _resolve_lang(lang)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail=t("errors.login_required", resolved_lang))
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=t("errors.invalid_conversation_id", resolved_lang))
    new_visibility = (payload.visibility or "").strip().lower()
    if new_visibility not in {"private", "public"}:
        raise HTTPException(status_code=422, detail=t("errors.visibility_invalid", resolved_lang))
    conversation = await get_conversation_meta(conv_uuid)
    if not conversation:
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", resolved_lang))
    _require_conversation_owner(user, conversation, resolved_lang)
    updated = await update_conversation_visibility(
        conv_uuid,
        new_visibility,
        owner_role=user.get("role"),
    )
    if not updated:
        raise HTTPException(status_code=500, detail=t("errors.visibility_update_failed", resolved_lang))
    return {"ok": True, "visibility": new_visibility}


@router.patch("/chat/history/{conversation_id}/project")
async def conversation_project_update(
    conversation_id: str,
    payload: ConversationProjectPayload,
    lang: Optional[str] = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    resolved_lang = _resolve_lang(lang)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail=t("errors.login_required", resolved_lang))
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=t("errors.invalid_conversation_id", resolved_lang))

    conversation = await get_conversation_meta(conv_uuid)
    if not conversation:
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", resolved_lang))
    _require_conversation_owner(user, conversation, resolved_lang)

    requested_project_id = (payload.project_id or "").strip() or None
    requested_project_label: Optional[str] = None
    if requested_project_id:
        async with SessionLocal() as session:
            project_result = await session.execute(
                select(Project).where(
                    Project.id == requested_project_id,
                    Project.is_archived.is_(False),
                )
            )
            project = project_result.scalars().first()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            if not _is_super_admin_user(user) and project.owner_user_id != user.get("id"):
                raise HTTPException(status_code=403, detail=t("errors.conversation_unavailable", resolved_lang))
            requested_project_label = project.name

    updated = await update_conversation_project(conv_uuid, requested_project_id, requested_project_label)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update conversation project")

    updated_meta = await get_conversation_meta(conv_uuid)
    return {
        "ok": True,
        "item": {
            "conversation_id": conversation_id,
            "project_id": updated_meta.get("project_id") if updated_meta else requested_project_id,
            "project_label": updated_meta.get("project_label") if updated_meta else requested_project_label,
            "updated_at": updated_meta.get("updated_at") if updated_meta else None,
        },
    }


@router.delete("/chat/history/{conversation_id}")
async def conversation_archive(
    conversation_id: str,
    lang: Optional[str] = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    resolved_lang = _resolve_lang(lang)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail=t("errors.login_required", resolved_lang))
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=t("errors.invalid_conversation_id", resolved_lang))
    conversation = await get_conversation_meta(conv_uuid)
    if not conversation:
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", resolved_lang))
    _require_conversation_owner(user, conversation, resolved_lang)
    archived = await archive_conversation(
        conv_uuid,
        archived_by=user.get("id"),
        archived_role=user.get("role"),
    )
    if not archived:
        raise HTTPException(status_code=500, detail=t("errors.delete_failed", resolved_lang))
    return {"ok": True, "archived": True}


@router.post("/chat/history/{conversation_id}/restore")
async def conversation_restore(
    conversation_id: str,
    lang: Optional[str] = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    resolved_lang = _resolve_lang(lang)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail=t("errors.login_required", resolved_lang))
    if not _is_super_admin_user(user):
        raise HTTPException(status_code=403, detail=t("errors.super_admin_required", resolved_lang))
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=t("errors.invalid_conversation_id", resolved_lang))
    conversation = await get_conversation_meta(conv_uuid)
    if not conversation:
        raise HTTPException(status_code=404, detail=t("errors.conversation_not_found", resolved_lang))
    restored = await restore_conversation(conv_uuid)
    if not restored:
        raise HTTPException(status_code=500, detail=t("errors.restore_failed", resolved_lang))
    return {"ok": True, "restored": True}

@router.get("/debug/health")
async def health():
    conn = await db.get_conn()
    try:
        corpus = await rag_corpus_status(conn)
        column_type = await conn.fetchval(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
              FROM pg_attribute a
              JOIN pg_class c ON c.oid = a.attrelid
             WHERE c.relname = 'chunks' AND a.attname = 'embedding' AND a.attnum > 0
            """
        )
    finally:
        await conn.close()
    configured_dim = embedding_dimension()
    column_dim_match = str(column_type or "").strip().lower() == f"vector({configured_dim})"
    ok = corpus.get("status") != "error" and column_dim_match
    return {
        "ok": ok,
        "embedding": {
            "provider": embedding_provider_name(),
            "model": embedding_model_name(),
            "dimension": configured_dim,
        },
        "pgvector": {
            "column_type": column_type,
            "dimension_match": column_dim_match,
        },
        "rag": corpus,
    }

@router.post("/debug/retrieve")
async def debug_retrieve(payload: DebugRetrievePayload):
    result = await retrieval_service.search(
        payload.query,
        rag_k=payload.rag_k or 8,
        cerp_limit=payload.cerp_limit or 50,
    )
    return {
        "ok": True,
        "hits": [hit.dict() for hit in result.hits],
        "cerp_products": result.cerp_products,
        "errors": result.errors,
    }


@router.get("/debug/retrieval-health")
async def debug_retrieval_health(q: str = "Champagne terroir chalk growers Avize Mesnil", k: int = 8):
    query = str(q or "").strip() or "Champagne terroir chalk growers Avize Mesnil"
    top_k = max(1, min(int(k or 8), 20))
    embedding_check: Dict[str, Any] = {
        "model": embedding_model_name(),
        "available": False,
        "dimension": None,
        "error_type": "",
    }
    try:
        vectors = embed_texts([query])
        embedding_check["available"] = True
        embedding_check["dimension"] = int(len(vectors[0])) if len(vectors) else 0
    except EmbeddingUnavailableError as exc:
        embedding_check["error_type"] = exc.error_type
        embedding_check["error_message"] = str(exc)[:240]
    except Exception as exc:
        embedding_check["error_type"] = type(exc).__name__
        embedding_check["error_message"] = str(exc)[:240]

    conn = await db.get_conn()
    try:
        dim_rows = await conn.fetch(
            """
            SELECT vector_dims(embedding) AS dim, COUNT(*) AS count
              FROM chunks
             WHERE embedding IS NOT NULL
             GROUP BY dim
             ORDER BY count DESC
            """
        )
        counts = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM documents) AS documents,
                (SELECT COUNT(*) FROM chunks) AS chunks,
                (SELECT COUNT(*) FROM chunks WHERE embedding IS NULL) AS embedding_null,
                (SELECT COUNT(DISTINCT d.filename)
                   FROM documents d JOIN chunks c ON c.document_id=d.id
                  WHERE d.filetype='pdf') AS pdf_docs_with_chunks
            """
        )
        rows = await _vector_search(conn, query, k=top_k)
    finally:
        await conn.close()

    sources: Dict[str, int] = {}
    families: Dict[str, int] = {}
    retrieval_modes: Dict[str, int] = {}
    scores: List[float] = []
    hits: List[Dict[str, Any]] = []
    for row in rows:
        meta = row.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        source = str(meta.get("source_name") or meta.get("book_title") or meta.get("filename") or "unknown")
        family = str(meta.get("source_family") or "unknown")
        mode = str(meta.get("retrieval_mode") or "unknown")
        score = float(row.get("score") or 0.0)
        sources[source] = sources.get(source, 0) + 1
        families[family] = families.get(family, 0) + 1
        retrieval_modes[mode] = retrieval_modes.get(mode, 0) + 1
        scores.append(score)
        hits.append(
            {
                "id": row.get("id"),
                "document_id": row.get("document_id"),
                "chunk_idx": row.get("chunk_idx"),
                "score": score,
                "retrieval_mode": mode,
                "source_family": family,
                "source_name": source,
                "page": meta.get("page") or meta.get("page_or_row"),
                "embedding_error_type": meta.get("embedding_error_type"),
                "text_sample": str(row.get("summary") or row.get("text") or "")[:180],
            }
        )
    db_counts = dict(counts) if counts else {}
    return {
        "ok": True,
        "query": query,
        "embedding": embedding_check,
        "db": {
            "documents": int(db_counts.get("documents") or 0),
            "chunks": int(db_counts.get("chunks") or 0),
            "embedding_null": int(db_counts.get("embedding_null") or 0),
            "pdf_docs_with_chunks": int(db_counts.get("pdf_docs_with_chunks") or 0),
            "vector_dimensions": [dict(row) for row in dim_rows],
        },
        "retrieval": {
            "top_k": top_k,
            "hit_count": len(hits),
            "scores_all_zero": bool(hits) and all(score == 0.0 for score in scores),
            "source_diversity": len(sources),
            "source_counts": sources,
            "source_family_counts": families,
            "retrieval_mode_counts": retrieval_modes,
            "hits": hits,
        },
    }


@router.get("/store/profile")
async def store_profile():
    """
    提供前端 / 其他服務載入店家資訊（可透過 STORE_PROFILE_PATH 切換）。
    """
    return get_store_profile()

# ----- utils (payload + message extraction) -----
def _extract_message(request: Request, data: Dict[str, Any]) -> str:
    for k in ("message","text","q","prompt","query","content"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for k in ("message","text","q","prompt","query","content"):
        v = request.query_params.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    if isinstance(data.get("messages"), list):
        try:
            for m in data["messages"]:
                if isinstance(m, dict) and (m.get("role") == "user") and m.get("content"):
                    return str(m["content"]).strip()
        except Exception:
            pass
    return ""

async def _get_payload(request: Request) -> Dict[str, Any]:
    try:
        return await request.json()
    except Exception:
        try:
            raw = (await request.body()).decode("utf-8","ignore").strip()
            if raw.startswith("{") and raw.endswith("}"):
                import json
                return json.loads(raw)
            elif raw:
                return {"message": raw}
        except Exception:
            pass
    return {}


def _coerce_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False
    return bool(value)


def _normalize_attachment_payload(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, list):
        for item in raw:
            normalized = _normalize_attachment_payload(item)
            if normalized:
                return normalized
        return None
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path") or "").strip()
    filename = str(raw.get("filename") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not any([path, filename, url]):
        return None
    attachment = {
        "type": str(raw.get("type") or "file").strip() or "file",
        "filename": filename or None,
        "path": path or None,
        "mime": str(raw.get("mime") or "").strip() or None,
        "url": url or None,
        "size": raw.get("size"),
        "extracted_text": raw.get("extracted_text"),
        "ocr_status": str(raw.get("ocr_status") or "pending").strip() or "pending",
        "image_classification_status": str(raw.get("image_classification_status") or "pending").strip() or "pending",
    }
    return attachment


def _normalize_url_inputs_payload(raw: Any, *, max_items: int = 10) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = re.split(r"[\n,，]+", raw)
    elif isinstance(raw, list):
        values = raw
    else:
        return []
    normalized: List[str] = []
    for item in values:
        value = str(item or "").strip()
        if not value:
            continue
        if not re.match(r"^https?://", value, flags=re.IGNORECASE):
            continue
        if value in normalized:
            continue
        normalized.append(value)
        if len(normalized) >= max_items:
            break
    return normalized

HIGHLIGHT_MIN = 4
HIGHLIGHT_MAX = 5
SUMMARY_CHAR_LIMIT = 20
LACK_SOURCE_THRESHOLD = 3
LINE_CLEAN_RE = re.compile(r'^[\s\-‧·‧\d\.、、:：()\[\]]+')
MAX_CONTEXT_HITS = 8
PRODUCT_CODE_PATTERN = re.compile(r'\b[A-Z]{2,3}-[A-Z0-9-]{6,}\b')
BARCODE_PATTERN = re.compile(r'\b\d{11,13}\b')
CODE_LABEL_PATTERN = re.compile(r'(?:barcode|no|編號|品號|條碼)\s*[:：]\s*([A-Z0-9-]{3,})', re.IGNORECASE)
INLINE_BARCODE_PATTERN = re.compile(r'barcode\s*[:：]?\s*([A-Z0-9-]{6,})', re.IGNORECASE)
NAME_LABEL_PATTERN = re.compile(r'(?:品名|產品名稱|商品名稱|name|product name)\s*[:：]\s*(.+)', re.IGNORECASE)
TERM_TOKEN_RE = re.compile(r'[\w一-鿿]+', re.UNICODE)
SENTENCE_RE = re.compile(r'[^。\uff0e\.!！?？]+[。\uff0e\.!！?？]?')


def _normalize_project_payload(data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    project_block = data.get("project")
    if not isinstance(project_block, dict):
        project_block = {}
    project_id = (
        project_block.get("id")
        or project_block.get("project_id")
        or data.get("project_id")
        or data.get("project_key")
        or data.get("client_id")
    )
    if isinstance(project_id, str):
        project_id = project_id.strip()
    project_label = (
        project_block.get("label")
        or project_block.get("name")
        or project_block.get("title")
        or data.get("project_label")
        or data.get("project_name")
    )
    if isinstance(project_label, str):
        project_label = project_label.strip()
    if not project_id and not project_label:
        return None
    payload: Dict[str, str] = {}
    if project_id:
        payload["id"] = str(project_id)
    if project_label:
        payload["label"] = str(project_label)
    return payload or None


async def _load_recent_attachment_context(conversation_id: Optional[str]) -> Dict[str, Any]:
    if not conversation_id:
        return {}
    try:
        conv_uuid = uuid.UUID(str(conversation_id))
    except (ValueError, TypeError):
        return {}
    try:
        messages = await get_messages_by_conversation(conv_uuid, include_metadata=True)
    except Exception as exc:
        logger.info("Recent attachment context is unavailable; continuing chat: %s", exc)
        return {}
    for msg in reversed(messages or []):
        metadata = msg.get("metadata") if isinstance(msg, dict) else None
        if not isinstance(metadata, dict):
            continue
        if not metadata:
            continue
        attachment_context = metadata.get("attachment_context")
        if isinstance(attachment_context, dict) and attachment_context.get("summary"):
            return attachment_context
    return {}


def _build_benchmark_timeout_payload(
    *,
    query: str,
    language: str,
    deadline_seconds: Optional[float],
    project_context: Optional[Dict[str, str]],
    store_profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    deadline_label = f"{float(deadline_seconds):.1f}s" if deadline_seconds is not None else "the configured deadline"
    answer = t("ai.fail_closed.benchmark_timeout", language, deadline=deadline_label)
    metadata: Dict[str, Any] = {
        "response_mode": "templated_fail_closed",
        "answer_mode": "fail_closed",
        "substantive_answer": False,
        "request_deadline_exceeded": True,
        "hard_error_flags": ["benchmark_deadline_exceeded"],
        "citation_validation": {
            "citation_count": 0,
            "unmapped_citation_count": 0,
            "hard_error_flags": ["benchmark_deadline_exceeded"],
        },
        "retrieval_snapshot": {
            "query": query,
            "response_mode": "templated_fail_closed",
            "request_deadline_exceeded": True,
            "selected_hit_count": 0,
        },
    }
    metadata["benchmark_trace"] = {
        "trace_kind": "benchmark_timeout",
        "llm_called": False,
        "generation_type": "benchmark_timeout",
        "no_llm_reason": "benchmark_deadline_exceeded",
        "llm_request_payload": {
            "mode": "no_llm_call",
            "reason": "benchmark_deadline_exceeded",
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
            "retrieval_snapshot": metadata["retrieval_snapshot"],
        },
        "final_response_json": {
            "text": answer,
            "citations": [],
            "metadata": {key: value for key, value in metadata.items() if key != "benchmark_trace"},
        },
        "trace_status": "error",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "BENCHMARK_TIMEOUT"},
        "answer": {
            "text": answer,
            "citations": [],
            "metadata": metadata,
        },
        "content": answer,
        "language": language,
        "project": project_context,
        "store": store_profile or None,
    }


@router.post("/chat/product-recommendations")
async def product_recommendations(
    payload: ProductRecommendationPayload,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    language = normalize_lang(payload.lang or "zh-TW")
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Login required")
    try:
        conversation_id = uuid.UUID(str(payload.conversation_id))
        source_message_id = uuid.UUID(str(payload.source_message_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation or source message ID") from exc

    await _ensure_conversation_write_access(str(conversation_id), user, language)
    source_message = await get_message_in_conversation(conversation_id, source_message_id)
    if not source_message or str(source_message.get("role") or "").lower() != "assistant":
        raise HTTPException(status_code=404, detail="Source message not found")
    source_metadata = source_message.get("metadata") if isinstance(source_message.get("metadata"), dict) else {}
    source_bridge = source_metadata.get("product_bridge") if isinstance(source_metadata.get("product_bridge"), dict) else {}
    if not source_bridge.get("eligible") or source_bridge.get("trigger") != "button":
        raise HTTPException(status_code=409, detail="This message has no pending product recommendation")
    need_profile = source_bridge.get("need_profile")
    if not isinstance(need_profile, dict):
        raise HTTPException(status_code=409, detail="Saved product requirements are unavailable")

    existing = await find_product_bridge_response(conversation_id, source_message_id)
    if existing:
        return _chat_response_from_persisted_bridge(existing, language)

    try:
        recommendation = await product_bridge_service.recommend(need_profile, language=language)
    except CERPClientError:
        recommendation = {
            "product_results": [],
            "source_timestamp": datetime.now(timezone.utc).isoformat(),
            "professional_guidance": ProductBridgeService.professional_guidance(need_profile, language),
            "text": ProductBridgeService._answer_text(False, language),
            "erp_status": "error",
        }
    action_text = {
        "en": "View YS recommended products",
        "ja": "YSおすすめ商品を見る",
    }.get(language.split("-", 1)[0].lower(), "查看 YS 推薦商品")
    await add_message_to_conversation(
        conversation_id,
        "user",
        action_text,
        user_id=user.get("id"),
        metadata={
            "action": "product_recommendations",
            "source_message_id": str(source_message_id),
        },
    )

    product_results = list(recommendation.get("product_results") or [])
    answer_text = "\n\n".join(
        part
        for part in (
            str(recommendation.get("professional_guidance") or "").strip(),
            str(recommendation.get("text") or "").strip(),
        )
        if part
    )
    metadata = {
        "intent": "PRODUCT_RECOMMENDATION",
        "knowledge": source_metadata.get("knowledge") or {
            "mode": "llm_only",
            "rag_status": "no_relevant_hits",
            "rag_hit_count": 0,
            "external_attempted": False,
            "external_status": "not_attempted",
        },
        "product_bridge": {
            **dict(source_bridge),
            "trigger": "immediate",
            "source_message_id": str(source_message_id),
            "fulfilled": True,
        },
        "product_results": product_results,
        "erp_status": recommendation.get("erp_status"),
        "erp_snapshot_timestamp": recommendation.get("source_timestamp"),
        "language": language,
        "lang": language,
        "intent_task_type": "product_recommendation",
        "intent_decision": "erp_immediate",
        "intent_source": "button",
        "intent_confidence": 1.0,
    }
    _, assistant_message_id = await add_message_to_conversation(
        conversation_id,
        "assistant",
        answer_text,
        user_id=user.get("id"),
        metadata=metadata,
        return_message_id=True,
    )
    source_metadata["product_bridge"] = {
        **dict(source_bridge),
        "fulfilled": True,
    }
    await update_message_enrichment(source_message_id, metadata=source_metadata)
    await merge_conversation_context_state(
        conversation_id,
        {"product_need_profile": need_profile, "source_message_id": str(source_message_id)},
        context_version=NEED_PROFILE_VERSION,
    )
    answer = {
        "text": answer_text,
        "citations": [],
        "conversation_id": str(conversation_id),
        "message_id": str(assistant_message_id),
        "metadata": metadata,
    }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "PRODUCT_RECOMMENDATION"},
        "answer": answer,
        "content": answer_text,
        "language": language,
        "product_results": product_results,
        "idempotent_replay": False,
    }


@router.post("/chat")
async def chat(request: Request, user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)):
    try:
        data = await _get_payload(request)
        text = _extract_message(request, data)
        raw_lang = data.get("lang")
        question_lang, requested_lang, answer_lang = _resolve_chat_language(text, raw_lang)
        resolved_lang = requested_lang
        if not text:
            return {"ok": False, "error": t("errors.empty_message", resolved_lang)}
        resolved_lang = answer_lang
        project_context = _normalize_project_payload(data)
        store_profile = get_store_profile()
        attachment_payload = _normalize_attachment_payload(data.get("attachment"))
        url_inputs = _normalize_url_inputs_payload(data.get("url_inputs"))
        benchmark_trace = bool(_coerce_bool(data.get("benchmark_trace")))
        benchmark_deadline_seconds = None
        if benchmark_trace and data.get("benchmark_deadline_seconds") not in (None, ""):
            try:
                benchmark_deadline_seconds = max(5.0, float(data.get("benchmark_deadline_seconds")))
            except (TypeError, ValueError):
                benchmark_deadline_seconds = None
        
        # --- 指令檢查 ---
        # 1. 登入指令
        if text == "{l}":
            if user:
                msg = t("system.already_logged_in", resolved_lang, lo="{lo}")
                return {"ok": True, "answer": {"text": msg, "citations": []}, "content": msg}
            return {"ok": True, "kind": "system", "action": "prompt_login"}
        elif text == "{lo}":
            if user:
                return {"ok": True, "kind": "system", "action": "perform_logout"}
            msg = t("system.not_logged_in", resolved_lang, l="{l}")
            return {"ok": True, "answer": {"text": msg, "citations": []}, "content": msg}
        elif text == "{be}" and user and user.get("role") in ["admin", "SAdmin"]:
            admin_payload = build_admin_panel_payload(user, resolved_lang)
            return {"ok": True, "kind": "system", "action": "show_admin_panel", "admin_panel": admin_payload}
        elif text == "{be}":
            msg = t("system.admin_required", resolved_lang)
            return {"ok": True, "answer": {"text": msg, "citations": []}, "content": msg}
        elif not user:
            return {"ok": True, "kind": "system", "action": "login_required"}

        user_id = user.get("id") if isinstance(user, dict) else None
        reset_conversation = bool(
            data.get("reset_conversation")
            or data.get("clear_conversation")
            or data.get("clear_history")
        )
        create_new_conversation = bool(data.get("create_new_conversation"))
        requested_conversation_id = None if reset_conversation else data.get("conversation_id")
        # Authorization and archived-state checks must happen before any early route
        # is allowed to read history or persist messages.
        await _ensure_conversation_write_access(requested_conversation_id, user, resolved_lang)
        knowledge_conversation_id = requested_conversation_id
        project_id_for_knowledge = project_context.get("id") if project_context else None
        if not knowledge_conversation_id and user_id and project_id_for_knowledge and not create_new_conversation:
            existing_conv = await find_conversation_by_project(user_id, project_id_for_knowledge)
            if existing_conv:
                knowledge_conversation_id = str(existing_conv)
        product_need_history: List[Dict[str, Any]] = []
        conversation_context_state: Dict[str, Any] = {}
        if knowledge_conversation_id:
            knowledge_uuid = uuid.UUID(str(knowledge_conversation_id))
            product_need_history = (await get_messages_by_conversation(knowledge_uuid))[-12:]
            knowledge_meta = await get_conversation_meta(knowledge_uuid)
            if knowledge_meta and isinstance(knowledge_meta.get("context_state"), dict):
                conversation_context_state = dict(knowledge_meta["context_state"])
        inherited_need_profile = conversation_context_state.get("product_need_profile")
        if not isinstance(inherited_need_profile, dict):
            inherited_need_profile = {}
        product_need_result = ProductNeedResult(
            profile=merge_need_profile_patch({}, inherited_need_profile),
            eligible=False,
            explicit_product_intent=False,
            preview_categories=[],
        )
        domain_cerp_enabled = is_module_enabled("domain.cerp")
        if _looks_like_mojibake_input(text):
            clarification = _build_low_readability_message(resolved_lang)
            project_id = project_context.get("id") if project_context else None
            project_label = project_context.get("label") if project_context else None
            conv_uuid: Optional[uuid.UUID] = None
            requested_conversation_id = data.get("conversation_id")
            if requested_conversation_id and not data.get("reset_conversation"):
                try:
                    conv_uuid = uuid.UUID(str(requested_conversation_id))
                except (ValueError, TypeError):
                    conv_uuid = None
            conv_id = await add_message_to_conversation(
                conv_uuid,
                "user",
                text,
                user_id=user_id,
                project_id=project_id,
                project_label=project_label,
            )
            metadata = {
                "intent": "FREE_CHAT",
                "low_readability_query": True,
                "mojibake_detected": True,
                "routing_path": "mojibake_fallback",
                "language": resolved_lang,
                "lang": resolved_lang,
                "detected_query_language": question_lang,
                "requested_language": requested_lang,
                "project": project_context or {},
            }
            _, assistant_message_id = await add_message_to_conversation(
                conv_id,
                "assistant",
                clarification,
                user_id=user_id,
                project_id=project_id,
                project_label=project_label,
                metadata=metadata,
                return_message_id=True,
            )
            answer_payload: Dict[str, Any] = {
                "text": clarification,
                "citations": [],
                "conversation_id": str(conv_id) if conv_id else None,
                "metadata": metadata,
            }
            if assistant_message_id:
                answer_payload["message_id"] = str(assistant_message_id)
            return {
                "ok": True,
                "kind": "chat",
                "intent": {"name": "FREE_CHAT"},
                "answer": answer_payload,
                "content": clarification,
                "language": resolved_lang,
                "project": project_context,
                "store": store_profile or None,
            }
        guardrail_response = build_guardrail_response(
            text,
            user,
            language=resolved_lang,
            benchmark_trace=benchmark_trace,
        )
        if guardrail_response:
            guardrail_response["project"] = project_context
            guardrail_response["store"] = store_profile or None
            return guardrail_response
        llm_budget = LLMRequestBudget(limit=2)
        try:
            execution_plan = await chat_planning_service.plan(
                text,
                history=product_need_history,
                context_state=conversation_context_state,
                budget=llm_budget,
            )
        except Exception as exc:
            logger.warning("YS-AI planner failed; using knowledge-only fallback: %s", exc)
            execution_plan = ChatPlanningService.fallback(text)
        product_intent_decision = execution_plan
        trip_plan_result = trip_plan_service.merge_planner_patch(
            context_state=conversation_context_state,
            patch=execution_plan.trip_plan_patch.model_dump(exclude_none=True),
            task_type=product_intent_decision.task_type,
        )
        trip_need_patch: Dict[str, Any] = {}
        merged_profile = merge_need_profile_patch(
            trip_need_patch,
            product_need_result.profile,
        )
        merged_profile = merge_need_profile_patch(
            merged_profile,
            product_intent_decision.need_profile_patch.model_dump(),
        )
        product_need_result = ProductNeedResult(
            profile=merged_profile,
            eligible=product_intent_decision.bridge_eligible,
            explicit_product_intent=product_intent_decision.immediate,
            preview_categories=list(merged_profile.get("categories") or [])[:6],
        )

        erp_result: Optional[Dict[str, Any]] = None
        if domain_cerp_enabled and execution_plan.erp_ast is not None:
            erp_result = await erp_query_executor.execute(
                execution_plan.erp_ast,
                language=resolved_lang,
            )
        lang = resolved_lang

        history_cutoff_value: Optional[datetime] = None
        if bool(data.get("ignore_history_before_today")):
            history_cutoff_value = datetime.now(timezone.utc).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        compact_mode = request.query_params.get("compact") in ("1", "true")
        conversation_id = requested_conversation_id
        project_id_for_lookup = project_context.get("id") if project_context else None
        if not conversation_id and user_id and project_id_for_lookup and not create_new_conversation:
            existing_conv = await find_conversation_by_project(user_id, project_id_for_lookup)
            if existing_conv:
                conversation_id = str(existing_conv)
        recent_attachment_context = await _load_recent_attachment_context(conversation_id)

        refined_text = text
        standard_prompt_category_override: Optional[str] = "general_chat"
        standard_authoritative_reason_override: Optional[str] = None
        auto_external_verification = bool(execution_plan.external.required or url_inputs)
        standard_needs_authoritative_override = auto_external_verification
        if auto_external_verification:
            standard_authoritative_reason_override = (
                execution_plan.external.reason or "time_sensitive_or_explicit_verification"
            )

        orchestrator_call = chat_orchestrator.chat(
            refined_text,
            conversation_id=conversation_id,
            analysis_weight=0.0,
            compact=compact_mode,
            user_id=user_id,
            project_context=project_context,
            history_cutoff=history_cutoff_value,
            store_profile=store_profile or None,
            language=lang,
            attachment=attachment_payload,
            prior_attachment_context=recent_attachment_context,
            url_inputs=url_inputs,
            source_policy=("authoritative_external_required" if auto_external_verification else "internal_preferred"),
            needs_authoritative_sources=standard_needs_authoritative_override,
            prompt_category_override=standard_prompt_category_override,
            authoritative_reason_override=standard_authoritative_reason_override,
            benchmark_trace=benchmark_trace,
            request_deadline_seconds=benchmark_deadline_seconds,
            persisted_context_state={
                **conversation_context_state,
                "trip_plan": trip_plan_result.trip_plan,
            },
            retrieval_query_override=(execution_plan.rag_queries[0] if execution_plan.rag_queries else text),
            execution_plan=execution_plan,
            erp_result=erp_result,
            llm_budget=llm_budget,
            planning_history=product_need_history,
        )
        try:
            if benchmark_trace and benchmark_deadline_seconds is not None:
                orchestrated = await asyncio.wait_for(
                    orchestrator_call,
                    timeout=max(10.0, float(benchmark_deadline_seconds) + 5.0),
                )
            else:
                orchestrated = await orchestrator_call
        except asyncio.TimeoutError:
            return _build_benchmark_timeout_payload(
                query=refined_text,
                language=lang,
                deadline_seconds=benchmark_deadline_seconds,
                project_context=project_context,
                store_profile=store_profile or None,
            )
        payload = orchestrated.dict()
        answer_metadata = payload.get("answer", {}).get("metadata")
        if isinstance(answer_metadata, dict):
            answer_metadata["language"] = lang
            answer_metadata["lang"] = lang
            answer_metadata["detected_query_language"] = question_lang
            answer_metadata["requested_language"] = requested_lang
            knowledge = _knowledge_contract(answer_metadata)
            answer_metadata["knowledge"] = knowledge
            answer_metadata["intent_task_type"] = product_intent_decision.task_type
            answer_metadata["intent_decision"] = product_intent_decision.decision
            answer_metadata["intent_source"] = product_intent_decision.source
            answer_metadata["intent_confidence"] = round(float(product_intent_decision.confidence), 3)
            answer_metadata["intent_lookup_operation"] = product_intent_decision.lookup_operation
            trigger = "immediate" if erp_result is not None else ("button" if product_need_result.eligible else "none")
            answer_metadata["product_bridge"] = _product_bridge_metadata(
                product_need_result,
                trigger=trigger,
                fulfilled=erp_result is not None,
                intent_source=product_intent_decision.source,
                intent_confidence=product_intent_decision.confidence,
                intent_task_type=product_intent_decision.task_type,
                intent_decision=product_intent_decision.decision,
            )
            prompt_category = str(answer_metadata.get("prompt_category") or "").strip()
            response_mode = str(answer_metadata.get("response_mode") or "").strip()
            if prompt_category == "general_chat" and response_mode == "generated":
                retrieval_snapshot = answer_metadata.get("retrieval_snapshot") if isinstance(answer_metadata.get("retrieval_snapshot"), dict) else {}
                hit_count = int(retrieval_snapshot.get("selected_hit_count") or 0) if retrieval_snapshot else 0
                routing_path = "ys_ai_planned_with_rag" if hit_count > 0 else "ys_ai_planned_no_rag"
                answer_metadata.setdefault(
                    "routing_path",
                    routing_path,
                )
            elif response_mode == "templated_fail_closed":
                answer_metadata.setdefault("routing_path", "strict_business_fact_gate")
        if isinstance(answer_metadata, dict) and url_inputs:
            answer_metadata.setdefault("url_inputs", url_inputs)
            answer_metadata.setdefault("url_input_count", len(url_inputs))
            answer_metadata.setdefault("primary_url", url_inputs[0])
            answer_metadata.setdefault("url_input_source", "structured")
        answer_payload = payload.get("answer") or {}
        assistant_message_id = answer_payload.get("message_id")
        if isinstance(answer_metadata, dict) and assistant_message_id:
            answer_metadata["product_bridge"]["source_message_id"] = str(assistant_message_id)
            knowledge = answer_metadata.get("knowledge") if isinstance(answer_metadata.get("knowledge"), dict) else {}
            if knowledge.get("mode") == "llm_only":
                answer_payload["citations"] = []
            answer_payload["metadata"] = answer_metadata
            payload["answer"] = answer_payload
            payload["product_results"] = list((erp_result or {}).get("product_results") or [])
        if assistant_message_id:
            await update_message_enrichment(
                assistant_message_id,
                highlights=(answer_payload.get("metadata") or {}).get("grounded_highlights"),
                summary_snapshot=(answer_payload.get("metadata") or {}).get("grounded_summary"),
                metadata=answer_payload.get("metadata"),
            )
            response_conversation_id = answer_payload.get("conversation_id")
            if response_conversation_id and (
                product_need_result.eligible or trip_plan_service.has_trip_context(trip_plan_result.trip_plan)
            ):
                context_updates: Dict[str, Any] = {
                    "trip_plan": trip_plan_result.trip_plan,
                }
                if product_need_result.eligible:
                    context_updates.update(
                        {
                            "product_need_profile": product_need_result.profile,
                            "source_message_id": str(assistant_message_id),
                        }
                    )
                if isinstance(erp_result, dict) and isinstance(erp_result.get("erp_lookup"), dict):
                    context_updates["erp_lookup"] = dict(erp_result["erp_lookup"])
                await merge_conversation_context_state(
                    uuid.UUID(str(response_conversation_id)),
                    context_updates,
                    context_version=NEED_PROFILE_VERSION,
                )
        return payload

    except HTTPException:
        raise
    except Exception as ex:
        print(f"FATAL: /chat endpoint error: {type(ex).__name__}: {ex}")
        traceback.print_exc()
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
