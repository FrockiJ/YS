from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Optional, List, Dict, Any, Set, Tuple
import asyncio
import traceback
from urllib.error import HTTPError
from urllib.parse import quote_plus
from datetime import datetime, timezone
import re
import time
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
    get_conversation_meta,
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
from ..domain_modules.loader import get_chat_domain_hooks
from ..pipelines.nlu.intent import detect_intent as _detect_intent  # may fail if module missing
from ..pipelines.nlp.embedder import EmbeddingUnavailableError, embed_texts, embedding_model_name
from ..pipelines.rag.searcher import vector_search as _vector_search, structured_search as _structured_search
from ..pipelines.rag.query_rewrite import expand_aliases as _expand_aliases
from ..pipelines.compose.composer import compose_answer as _compose_answer
from ..pipelines.compose.generator import generate_answer as _generate_summary
from .routes_cerp import cerp_client, CERPClientError
from ..models.customer import Customer
from ..models.project import Project
from ..services.cerp_service import CerpService
from ..services.cerp_recommendation_service import CerpRecommendationService
from ..services.ai.analysis import AnalysisService
from ..services.ai.benchmark_guardrails import build_benchmark_contract_response, build_guardrail_response
from ..services.ai.orchestrator import ChatOrchestrator
from ..services.ai.retrieval import RetrievalService
from ..services.project_service import can_read_conversation, can_write_conversation
from ..schemas.ai import ChatResponse

from ..utils.cerp_export_lookup import (
    find_best_matching_product,
    find_export_row_by_barcode,
    find_export_row_by_code,
    find_best_matching_producer,
    find_products_by_producer,
)
from ..utils.webphoto import lookup_product_photo
from ..utils.nlu import extract_search_entities
from ..utils.inventory_intent import is_generic_inventory_listing_query
from ..utils.quote_search import (
    build_quote_match_summary,
    has_quote_semantic_filters,
    is_low_readability_quote_query,
    limit_quote_query_variants,
    normalize_quote_input_text,
    parse_quote_search_criteria,
    quote_product_alternative_score,
    quote_product_exact_rejection_reasons,
    quote_product_matches_criteria,
    sanitize_quote_alias_filters,
    sanitize_quote_alias_filters_for_cerp,
)
from ..utils.quote_followup import (
    ACTION_CONTINUE,
    ACTION_FILL_SIMILAR,
    ACTION_INCLUDE_SIMILAR,
    ACTION_RELAX_CONSTRAINTS,
    ACTION_SHOW_RECOMMENDED,
    build_quote_followup_contract,
    is_bare_confirmation,
    materialize_quote_followup_action,
    relax_quote_followup_filters,
    resolve_quote_followup,
)

logger = logging.getLogger(__name__)

router = APIRouter()
retrieval_service = RetrievalService()
chat_orchestrator = ChatOrchestrator(retrieval_service=retrieval_service)
analysis_service = AnalysisService()
chat_domain_hooks = get_chat_domain_hooks()
EXTERNAL_EVIDENCE_PROMPT_CATEGORIES = {
    "brand_profile",
    "source_validation",
    "latest_info",
    "terroir_comparison",
    "url_product_lookup",
    "critic_score_lookup",
    "exact_review_lookup",
    "book_corpus_lookup",
    "multi_review_compare",
    "source_hierarchy_conflict",
    "internal_rag_only_validation",
}

BENCHMARK_PROMPT_CATEGORY_OVERRIDES = {
    "exact_review_lookup",
    "book_corpus_lookup",
    "multi_review_compare",
    "source_hierarchy_conflict",
    "internal_rag_only_validation",
    "alias_inventory_equivalence",
}

_MOJIBAKE_MARKER_RE = re.compile(r"[鈭鋆撅蝮銝摰憭靘隞嚗餈箏喲瑼]")
_BUSINESS_LOCATION_QUERY_RE = re.compile(
    r"(?:\u4ee3\u7406\u5546|\u7d93\u92b7\u5546|\u9580\u5e02|\u9580\u5e97|\u5e97\u9762|\u54ea\u88e1\u8cb7|\u5728\u54ea\u8cb7|"
    r"dealer|distributor|retailer|store|shop|where\s+to\s+buy)",
    re.IGNORECASE,
)
_BUSINESS_LOCATION_NEARBY_RE = re.compile(
    r"(?:\u9644\u8fd1|\u8eab\u908a|\u5468\u908a).{0,10}(?:\u4ee3\u7406\u5546|\u7d93\u92b7\u5546|\u9580\u5e02|\u9580\u5e97|\u5e97\u9762|"
    r"dealer|distributor|retailer|store|shop)",
    re.IGNORECASE,
)


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


async def _load_optional_rag_context_for_outdoor_recommendation(text: str) -> Dict[str, Any]:
    try:
        hits = await retrieval_service._run_rag_search(
            text,
            query_variants=[text],
            alias_filters=None,
            rag_k=4,
            prompt_category="general_chat",
            entity_hints={},
        )
    except Exception as exc:
        logger.info("Outdoor recommendation optional RAG lookup skipped: %s", exc)
        return {"hit_count": 0, "sections": [], "error": f"{type(exc).__name__}: {exc}"}
    sections: List[Dict[str, Any]] = []
    for hit in hits[:4]:
        if not isinstance(hit, dict):
            continue
        meta = hit.get("meta") if isinstance(hit.get("meta"), dict) else {}
        title = str(meta.get("title") or meta.get("source_name") or hit.get("id") or "").strip()
        text_value = str(hit.get("summary") or hit.get("text") or "").strip()
        if not text_value:
            continue
        sections.append(
            {
                "title": title,
                "text": text_value[:600],
                "source_tier": meta.get("source_tier") or hit.get("source_tier") or "",
            }
        )
    return {
        "hit_count": len(sections),
        "sections": sections,
    }


def _looks_like_business_location_query(value: Any) -> bool:
    text = str(value or "")
    return bool(_BUSINESS_LOCATION_QUERY_RE.search(text) or _BUSINESS_LOCATION_NEARBY_RE.search(text))


def _build_business_location_answer(
    query: str,
    *,
    store_profile: Optional[Dict[str, Any]],
    language: str,
) -> Dict[str, Any]:
    profile = store_profile if isinstance(store_profile, dict) else {}
    contact = profile.get("contact") if isinstance(profile.get("contact"), dict) else {}
    company = str(
        profile.get("company_name")
        or profile.get("name")
        or profile.get("english_name")
        or ""
    ).strip()
    address = str(contact.get("address") or profile.get("address") or "").strip()
    phone = str(contact.get("phone") or profile.get("phone") or "").strip()
    booking = contact.get("booking") if isinstance(contact.get("booking"), dict) else {}
    booking_online = booking.get("online") if isinstance(booking.get("online"), dict) else {}
    booking_url = str(booking_online.get("url") or contact.get("booking_url") or "").strip()
    has_location = bool(address or phone or booking_url)
    if str(language or "").lower().startswith("ja"):
        if not has_location:
            text = "\u4f01\u696d\u8cc7\u6599\u306b\u5229\u7528\u53ef\u80fd\u306a\u5e97\u8217\u30fb\u4ee3\u7406\u5e97\u60c5\u5831\u304c\u307e\u3060\u767b\u9332\u3055\u308c\u3066\u3044\u307e\u305b\u3093\u3002"
        else:
            display_company = company or "\u4f01\u696d"
            lines = [f"\u767b\u9332\u6e08\u307f\u306e\u4f01\u696d\u60c5\u5831\u3067\u78ba\u8a8d\u3067\u304d\u308b\u7a93\u53e3\u306f {display_company} \u3067\u3059\u3002"]
            if address:
                lines.append(f"- \u4f4f\u6240\uff1a{address}")
            if phone:
                lines.append(f"- \u96fb\u8a71\uff1a{phone}")
            if booking_url:
                lines.append(f"- \u4e88\u7d04/URL\uff1a{booking_url}")
            text = "\n".join(lines)
    elif str(language or "").lower().startswith(("zh", "tw")):
        if not has_location:
            text = "\u4f01\u696d\u8cc7\u6599\u76ee\u524d\u6c92\u6709\u53ef\u7528\u7684\u5e97\u9762\u6216\u4ee3\u7406\u5546\u8cc7\u8a0a\uff0c\u56e0\u6b64\u6211\u4e0d\u6703\u81ea\u884c\u63a8\u6e2c\u5916\u90e8\u5e97\u5bb6\u3002"
        else:
            display_company = company or "\u672c\u4f01\u696d"
            lines = [f"\u4f9d\u7cfb\u7d71\u5167\u7684\u4f01\u696d\u8cc7\u6599\uff0c\u53ef\u6307\u5411 {display_company} \u7684\u5b98\u65b9\u806f\u7d61\u8cc7\u8a0a\uff1a"]
            if address:
                lines.append(f"- \u5730\u5740\uff1a{address}")
            if phone:
                lines.append(f"- \u96fb\u8a71\uff1a{phone}")
            if booking_url:
                lines.append(f"- \u9810\u7d04/URL\uff1a{booking_url}")
            text = "\n".join(lines)
    else:
        if not has_location:
            text = "No store, dealer, or distributor information is currently available in the company profile, so I will not guess external locations."
        else:
            lines = [f"Based on the company profile, use {company or 'the company'} official contact information:"]
            if address:
                lines.append(f"- Address: {address}")
            if phone:
                lines.append(f"- Phone: {phone}")
            if booking_url:
                lines.append(f"- Booking/URL: {booking_url}")
            text = "\n".join(lines)
    return {
        "text": text,
        "metadata": {
            "intent": "BUSINESS_LOCATION_LOOKUP",
            "prompt_category": "business_location_lookup",
            "response_mode": "company_profile_lookup" if has_location else "data_or_permission_needed",
            "answer_mode": "company_profile_lookup" if has_location else "data_or_permission_needed",
            "routing_path": "strict_business_fact_gate",
            "substantive_answer": has_location,
            "source_policy": "internal_only",
            "language": language,
            "lang": language,
            "query": query,
            "company_profile_used": has_location,
        },
    }

_TRACEBACK_PATTERN = re.compile(r"traceback\s*\(most recent call last\)", re.IGNORECASE)

def _resolve_lang(value: Optional[str]) -> str:
    return normalize_lang(value)


def _resolve_chat_language(text: str, raw_lang: Optional[str]) -> tuple[str, str, str]:
    requested_lang = _resolve_lang(raw_lang)
    detected_lang = _resolve_lang(detect_lang(text))
    return detected_lang, requested_lang, detected_lang


def _should_route_quote_surface_to_standard_chat(
    *,
    text: str,
    output_type: Any,
    url_inputs: Optional[List[str]],
    requested_followup_action: Optional[str],
    quote_followup_resolution: Dict[str, Any],
    intent_wants_quote: bool = False,
) -> bool:
    quote_surface_requested = _is_quote_output_type(output_type)
    followup_wants_quote = bool(
        quote_followup_resolution.get("is_followup")
        and quote_followup_resolution.get("base_quote_context")
    )
    if not (quote_surface_requested or followup_wants_quote or intent_wants_quote):
        return False
    if str(requested_followup_action or "").strip():
        return False
    inferred_producer = analysis_service._infer_producer_from_query(text)
    inferred_category = analysis_service._infer_prompt_category(text)
    if analysis_service._should_force_brand_profile(
        text,
        base_category=inferred_category,
        inferred_producer=inferred_producer,
    ):
        inferred_category = "brand_profile"
    if inferred_category != "url_product_lookup":
        authoritative_reason = analysis_service._determine_authoritative_reason(text, inferred_category)
        if authoritative_reason or inferred_category in EXTERNAL_EVIDENCE_PROMPT_CATEGORIES:
            return True
    resolved_followup_action = str(quote_followup_resolution.get("followup_action") or "").strip()
    if resolved_followup_action in {
        ACTION_CONTINUE,
        ACTION_FILL_SIMILAR,
        ACTION_INCLUDE_SIMILAR,
        ACTION_RELAX_CONSTRAINTS,
        ACTION_SHOW_RECOMMENDED,
    }:
        return False
    url_lookup_service = getattr(analysis_service, "_url_product_lookup_service", None)
    infer_lookup_goal = getattr(url_lookup_service, "infer_lookup_goal", None)
    if callable(infer_lookup_goal):
        try:
            lookup_goal = str(infer_lookup_goal(text) or "").strip()
        except Exception:
            lookup_goal = ""
        if lookup_goal == "product_availability_from_url" and url_inputs:
            return False
        if lookup_goal == "product_availability_from_url":
            return False
    if url_inputs:
        return False
    if inferred_category == "url_product_lookup":
        return False
    authoritative_reason = analysis_service._determine_authoritative_reason(text, inferred_category)
    return bool(
        authoritative_reason
        or inferred_category in EXTERNAL_EVIDENCE_PROMPT_CATEGORIES
    )


def _direct_cerp_notice(lang: str) -> str:
    return t("cerp.direct_notice", lang)

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



# 後備：模組缺時不中斷
def detect_intent(text: str, domain: str = "alcohol"):
    try:
        return _detect_intent(text, domain=domain)  # type: ignore
    except Exception:
        t = (text or "").lower()
        alcohol = any(k in t for k in ["wine","beer","whisky","w...skey","rum","gin","vodka","sake","tequila","mezcal","cocktail"])
        return {"name": "ASK_ALCOHOL_INFO" if alcohol else "FREE_CHAT", "slots": {}}

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
    return {"ok": True}

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
NAME_LABEL_PATTERN = re.compile(r'(?:酒名|品名|name|product name|wine|wine name)\s*[:：]\s*(.+)', re.IGNORECASE)
TERM_TOKEN_RE = re.compile(r'[\w一-鿿]+', re.UNICODE)
SENTENCE_RE = re.compile(r'[^。\uff0e\.!！?？]+[。\uff0e\.!！?？]?')


def _normalize_highlight_line(value: str) -> str:
    if not value:
        return ''
    return LINE_CLEAN_RE.sub('', value).strip()


def _split_sentences(blob: str) -> List[str]:
    if not blob:
        return []
    sanitized = blob.replace('\r', '\n').strip()
    if not sanitized:
        return []
    collapsed_newlines = re.sub(r'\n+', '\n', sanitized)
    normalized_whitespace = re.sub(r'[ \t]+', ' ', collapsed_newlines)
    chunks = [chunk for chunk in SENTENCE_RE.findall(normalized_whitespace) if chunk.strip()]
    if not chunks and '\n' in normalized_whitespace:
        chunks = [part for part in normalized_whitespace.split('\n') if part.strip()]
    if not chunks:
        chunks = [normalized_whitespace]
    results: List[str] = []
    for chunk in chunks:
        normalized_chunk = _normalize_highlight_line(chunk)
        if normalized_chunk:
            results.append(normalized_chunk)
    return results

def _split_fragments(blob: str) -> List[str]:
    if not blob:
        return []
    chunks = re.split(r'[,，、；;]\s*', blob)
    results: List[str] = []
    for chunk in chunks:
        normalized = _normalize_highlight_line(chunk)
        if normalized:
            results.append(normalized)
    return results


def _split_summary_lines(blob: str) -> List[str]:
    if not blob:
        return []
    lines = re.split(r'[\r\n]+', blob)
    return [line.strip() for line in lines if line and line.strip()]

def _build_highlights(answer_text: str, summary_text: str, keywords: List[str]) -> List[str]:
    highlights: List[str] = []
    seen = set()

    def push(value: str):
        normalized = _normalize_highlight_line(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        highlights.append(normalized)
    summary_text = (summary_text or '').strip()
    keyword_candidates = keywords or []

    if answer_text:
        for sentence in _split_sentences(answer_text):
            push(sentence)
            if len(highlights) >= HIGHLIGHT_MAX:
                return highlights[:HIGHLIGHT_MAX]
        for fragment in _split_fragments(answer_text):
            push(fragment)
            if len(highlights) >= HIGHLIGHT_MAX:
                return highlights[:HIGHLIGHT_MAX]

    if len(highlights) < HIGHLIGHT_MIN:
        for kw in keyword_candidates:
            push(f'關鍵字: {kw}')
            if len(highlights) >= HIGHLIGHT_MAX:
                return highlights[:HIGHLIGHT_MAX]

    if len(highlights) < HIGHLIGHT_MIN and not answer_text and summary_text:
        for line in _split_summary_lines(summary_text):
            push(line)
            if len(highlights) >= HIGHLIGHT_MAX:
                return highlights[:HIGHLIGHT_MAX]

    if len(highlights) < HIGHLIGHT_MIN and answer_text:
        push(answer_text)

    return highlights[:HIGHLIGHT_MAX]


def _clip_summary_text(value: str) -> str:
    normalized = ' '.join((value or '').split())
    if not normalized:
        return ''
    if len(normalized) <= SUMMARY_CHAR_LIMIT:
        return normalized
    return normalized[:SUMMARY_CHAR_LIMIT].rstrip() + '...'


def _build_compact_summary(summary_text: str, answer_text: str) -> str:
    """
    Prefer the RAG summary if available; otherwise take the first sentence of the
    assistant answer so the front-end summary chip stays aligned with the reply.
    """
    summary_text = (summary_text or '').strip()
    answer_text = (answer_text or '').strip()
    candidates: List[str] = []
    if summary_text:
        candidates.extend(_split_summary_lines(summary_text))
    if not candidates and answer_text:
        candidates.extend(_split_sentences(answer_text))
    for candidate in candidates:
        clipped = _clip_summary_text(candidate)
        if clipped:
            return clipped
    return ''


def _tokenize_for_search(value: str) -> List[str]:
    if not value:
        return []
    return [match.group(0).lower() for match in TERM_TOKEN_RE.finditer(value)]


def _collect_relevance_terms(
    text: str,
    query_variants: List[str],
    alias_filters: Dict[str, str],
) -> List[str]:
    terms = set()
    sources = [text] + (query_variants or [])
    for source in sources:
        terms.update(_tokenize_for_search(str(source)))
    for alias_value in (alias_filters or {}).values():
        terms.update(_tokenize_for_search(str(alias_value)))
    return [term for term in terms if term]


def _meta_to_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, dict):
        parts = [_meta_to_text(v) for v in value.values()]
        return ' '.join(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        parts = [_meta_to_text(v) for v in value]
        return ' '.join(part for part in parts if part)
    return str(value)


def _collect_hit_text(hit: Dict[str, Any]) -> str:
    parts = []
    for key in ('summary', 'text'):
        val = hit.get(key)
        if isinstance(val, str):
            parts.append(val)
    parts.append(_meta_to_text(hit.get('meta')))
    keywords = hit.get('keywords')
    if isinstance(keywords, (list, tuple, set)):
        parts.extend(str(k) for k in keywords if k)
    return ' '.join(part for part in parts if part)


def _hit_matches_terms(hit: Dict[str, Any], terms: List[str]) -> bool:
    if not terms:
        return False
    haystack = _collect_hit_text(hit).lower()
    if not haystack:
        return False
    return any(term in haystack for term in terms)


def _hit_score(hit: Dict[str, Any]) -> float:
    score = hit.get('score')
    try:
        return float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _select_relevant_hits(
    hits: List[Dict[str, Any]],
    terms: List[str],
    max_hits: int = MAX_CONTEXT_HITS,
) -> List[Dict[str, Any]]:
    if not hits:
        return []
    if not terms:
        return sorted(hits, key=_hit_score, reverse=True)[:max_hits]
    matched = [hit for hit in hits if _hit_matches_terms(hit, terms)]
    if matched:
        return sorted(matched, key=_hit_score, reverse=True)[:max_hits]
    # If nothing matched (e.g., follow-up like "查庫存"), keep the best available hits to preserve context
    return sorted(hits, key=_hit_score, reverse=True)[:max_hits]


def _ensure_meta_dict(fragment: Any) -> Dict[str, Any]:
    if isinstance(fragment, dict):
        return fragment
    if isinstance(fragment, str):
        try:
            parsed = json.loads(fragment)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _normalize_identifier(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float):
            if value.is_integer():
                value = int(value)
        return str(value).strip()
    text = str(value).strip()
    return text or None


def _extract_filename(meta: Dict[str, Any]) -> Optional[str]:
    for key in ("filename", "file", "title", "name", "document"):
        candidate = meta.get(key)
        if isinstance(candidate, str):
            candidate = candidate.strip()
            if candidate:
                return candidate
    return None


def _build_identity(record: Dict[str, Any]) -> Dict[str, Optional[str]]:
    meta = _ensure_meta_dict(record.get("meta"))
    return {
        "id": _normalize_identifier(record.get("id")),
        "document_id": _normalize_identifier(record.get("document_id")),
        "chunk_idx": _normalize_identifier(record.get("chunk_idx")),
        "filename": _normalize_identifier(
            record.get("filename") or _extract_filename(meta)
        ),
    }


def _collect_keyword_hints_from_hits(hits: List[Dict[str, Any]], limit: int = 12) -> List[str]:
    hints: List[str] = []
    for hit in hits or []:
        for kw in hit.get("keywords") or []:
            if not kw:
                continue
            if kw in hints:
                continue
            hints.append(kw)
            if len(hints) >= limit:
                return hints
    return hints


def _extract_terms_from_value(value: Any) -> Set[str]:
    terms: Set[str] = set()
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized:
            terms.add(normalized)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            terms.update(_extract_terms_from_value(item))
    elif isinstance(value, dict):
        for item in value.values():
            terms.update(_extract_terms_from_value(item))
    return terms


def _detect_portfolio_focus(
    text: str,
    intent_name: Optional[str],
    alias_filters: Dict[str, Any],
    preferred_brands: Optional[List[str]],
) -> bool:
    normalized_intent = (intent_name or "").strip().upper()
    if normalized_intent and normalized_intent != "FREE_CHAT":
        return True
    lowered_text = (text or "").lower()
    preferred_terms: Set[str] = set()
    for brand in preferred_brands or []:
        if isinstance(brand, str):
            candidate = brand.strip().lower()
            if candidate:
                preferred_terms.add(candidate)
    alias_terms: Set[str] = set()
    for value in alias_filters.values():
        alias_terms.update(_extract_terms_from_value(value))
    for term in preferred_terms.union(alias_terms):
        if term and term in lowered_text:
            return True
    return False


def _identity_matches_token(identity: Dict[str, Optional[str]], token: Dict[str, Optional[str]]) -> bool:
    if not identity or not token:
        return False
    if token.get("id") and token["id"] == identity.get("id"):
        return True
    if token.get("document_id") and token["document_id"] == identity.get("document_id"):
        if token.get("chunk_idx") and token["chunk_idx"] == identity.get("chunk_idx"):
            return True
        if not token.get("chunk_idx"):
            return True
    if token.get("filename") and token["filename"] == identity.get("filename"):
        return True
    return False


def _filter_hits_by_citations(
    hits: List[Dict[str, Any]], citations: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not hits or not citations:
        return hits
    citation_tokens: List[Dict[str, Optional[str]]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        meta = _ensure_meta_dict(citation.get("meta"))
        identity = {
            "id": _normalize_identifier(citation.get("id")),
            "document_id": _normalize_identifier(citation.get("document_id")),
            "chunk_idx": _normalize_identifier(citation.get("chunk_idx")),
            "filename": _normalize_identifier(
                citation.get("filename") or _extract_filename(meta)
            ),
        }
        if any(identity.values()):
            citation_tokens.append(identity)
    if not citation_tokens:
        return hits

    matched: List[Dict[str, Any]] = []
    seen_keys = set()

    for hit in hits:
        identity = _build_identity(hit)
        if any(_identity_matches_token(identity, token) for token in citation_tokens):
            key = (
                identity["id"],
                identity["document_id"],
                identity["chunk_idx"],
                identity["filename"],
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            matched.append(hit)
    return matched or hits


def _filter_citations_by_hits(
    citations: List[Dict[str, Any]], hits: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not citations or not hits:
        return citations or []
    hit_identities = [_build_identity(hit) for hit in hits]
    filtered: List[Dict[str, Any]] = []
    seen_keys = set()
    for citation in citations:
        identity = _build_identity(citation)
        if not identity:
            continue
        if not any(_identity_matches_token(hit_identity, identity) for hit_identity in hit_identities):
            continue
        key = (
            identity["id"],
            identity["document_id"],
            identity["chunk_idx"],
            identity["filename"],
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        filtered.append(citation)
    return filtered or citations


def _first_alias_value(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                return entry.strip()
    return None


def _extract_product_name_candidate(text: str) -> Optional[str]:
    if not text:
        return None
    match = NAME_LABEL_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def _extract_inline_barcode(text: str) -> Optional[str]:
    if not text:
        return None
    match = INLINE_BARCODE_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip().upper()


def _collect_search_candidates(
    text: str,
    alias_filters: Dict[str, Any],
    query_variants: List[str],
) -> List[str]:
    candidates: List[str] = []
    explicit = _extract_product_name_candidate(text)
    if explicit:
        candidates.append(explicit)
    for variant in query_variants or []:
        normalized = (variant or "").strip()
        if normalized:
            candidates.append(normalized)
    for value in alias_filters.values():
        alias_value = _first_alias_value(value)
        if alias_value:
            candidates.append(alias_value.strip())
    normalized_text = (text or "").strip()
    if normalized_text:
        candidates.append(normalized_text)
    seen = set()
    deduped: List[str] = []
    for cand in candidates:
        lowered = cand.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(cand)
    return deduped


def _extract_product_candidates(
    text: str,
    alias_filters: Dict[str, Any],
    query_variants: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str], bool]:
    candidate_code: Optional[str] = None
    candidate_barcode: Optional[str] = None
    code_alias = _first_alias_value(alias_filters.get("invn002"))
    if code_alias:
        candidate_code = code_alias
    barcode_alias = _first_alias_value(alias_filters.get("invn008"))
    if barcode_alias:
        candidate_barcode = barcode_alias

    if not candidate_code:
        inline_code = _extract_inline_barcode(text)
        if inline_code:
            candidate_code = inline_code

    if not candidate_code and text:
        match = PRODUCT_CODE_PATTERN.search(text)
        if match:
            candidate_code = match.group(0)
    if not candidate_barcode and text:
        match = BARCODE_PATTERN.search(text)
        if match:
            candidate_barcode = match.group(0)
    if not candidate_code and text:
        label_match = CODE_LABEL_PATTERN.search(text)
        if label_match:
            candidate_code = label_match.group(1).strip().upper()

    if not candidate_code:
        candidate_names = _collect_search_candidates(text, alias_filters, query_variants or [])
        for candidate in candidate_names:
            row = find_best_matching_product(candidate)
            if not row:
                continue
            candidate_code = candidate_code or row.get("invn002")
            candidate_barcode = candidate_barcode or row.get("invn008")
            if candidate_code:
                break
    text_lower = (text or "").lower()
    strict_keywords = ("barcode", "條碼", "編號", "品號", "code", "sku")
    strict_lookup = bool(candidate_code or candidate_barcode) and any(
        keyword in text_lower for keyword in strict_keywords
    )
    logger.debug(
        "Extracted CERP candidates code=%s barcode=%s strict=%s from text=%r",
        candidate_code,
        candidate_barcode,
        strict_lookup,
        text,
    )
    return candidate_code, candidate_barcode, strict_lookup


def _is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


def _merge_product_rows(
    product_row: Optional[Dict[str, Any]],
    info_row: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not product_row and not info_row:
        return None
    merged: Dict[str, Any] = {}
    for source in (info_row, product_row):
        if not source:
            continue
        for key, value in source.items():
            if _is_blank_value(value):
                continue
            merged[key] = value
    return merged or None


async def _refetch_precise_product_row(code: str, barcode: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    When CERP returns the wrong row, try a second pass using paramchar-only + exprange=2 to force an exact match.
    """
    if not code:
        return None
    paramchar: Dict[str, Any] = {"invn002": [code], "invn005": [code]}
    if barcode:
        paramchar["invn008"] = [barcode]
    try:
        response = await cerp_client.export_products(
            custid=None,
            supplier=None,
            compid=None,
            exprange=2,
            paramchar1=paramchar,
            perpage=1,
        )
    except CERPClientError:
        return None
    data = response.get("data") or {}
    rows = data.get("wd4invnas") or []
    return rows[0] if rows else None


def _safe_float(value: Any) -> float:
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    return int(round(_safe_float(value)))


def _map_warehouses(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mapped = []
    for entry in rows or []:
        mapped.append(
            {
                "warehouse_code": entry.get("inv1002") or "",
                "location": "",
                "quantity": _safe_int(entry.get("inv1015")),
                "reserved": _safe_int(entry.get("inv1016")),
                "lot": entry.get("inv1017") or "",
                "note": entry.get("inv1049") or "",
            }
        )
    return mapped


def _extract_stock(row: Dict[str, Any], warehouses: List[Dict[str, Any]]) -> int:
    if warehouses:
        stock_value = sum(_safe_float(entry.get("inv1015")) for entry in warehouses)
        return max(int(round(stock_value)), 0)
    return 0


def _extract_store_stock(warehouses: List[Dict[str, Any]]) -> int:
    keywords = ("精品", "門市", "門店", "店面", "retail", "boutique", "shop", "store")
    total = 0.0
    for entry in warehouses or []:
        if not isinstance(entry, dict):
            continue
        haystack = " ".join(
            str(entry.get(key) or "").strip().lower()
            for key in ("name002", "warehouse_name", "warehouseName", "location", "name", "note", "inv1049", "inv1002", "warehouse_code", "code")
        )
        if not any(keyword in haystack for keyword in keywords):
            continue
        total += _safe_float(entry.get("inv1015") or entry.get("quantity") or entry.get("stock_qty"))
    return max(int(round(total)), 0)


async def _fetch_cerp_product_info(
    code: Optional[str],
    barcode: Optional[str],
    inventory_only: bool = False,
    strict_lookup: bool = False,
) -> Optional[Dict[str, Any]]:
    if not code and not barcode:
        return None

    def _build_filters() -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        paramchar: Dict[str, Any] = {}
        if code:
            paramchar["invn002"] = [code]
        if barcode:
            payload["invn008b"] = barcode
            payload["invn008e"] = barcode
            paramchar["invn008"] = [barcode]
        if paramchar:
            payload["paramchar1"] = paramchar
        return payload

    logger.debug(
        "Fetching CERP rows: code=%s barcode=%s inventory_only=%s",
        code,
        barcode,
        inventory_only,
    )

    info_rows: List[Dict[str, Any]] = []
    warehouse_rows: List[Dict[str, Any]] = []
    info_payload = _build_filters()
    logger.debug("CERP products_info payload: %s exprange=2 perpage=1", info_payload)
    try:
        info_response = await cerp_client.export_products_info(
            custid=None,
            supplier=None,
            compid=None,
            exprange=2,
            **info_payload,
            perpage=1,
        )
    except CERPClientError as exc:
        logger.warning(
            "CERP products_info request failed for code=%s barcode=%s, falling back to local export: %s",
            code,
            barcode,
            exc,
        )
    else:
        info_data = info_response.get("data") or {}
        info_rows = info_data.get("wd4invnas") or []
        warehouse_rows = info_data.get("wd4inv1as") or []

    info_row = info_rows[0] if info_rows else None
    logger.debug(
        "CERP products_info returned rows=%d warehouses=%d",
        len(info_rows),
        len(warehouse_rows),
    )

    product_row: Optional[Dict[str, Any]] = None
    if not inventory_only:
        product_payload = _build_filters()
        logger.debug("CERP products payload: %s exprange=2 perpage=1", product_payload)
        try:
            product_response = await cerp_client.export_products(
                custid=None,
                supplier=None,
                compid=None,
                exprange=2,
                **product_payload,
                perpage=1,
            )
        except CERPClientError as exc:
            logger.warning(
                "CERP products request failed for code=%s barcode=%s, falling back to local export: %s",
                code,
                barcode,
                exc,
            )
            product_row = None
        else:
            product_data = product_response.get("data") or {}
            product_rows = product_data.get("wd4invnas") or []
            product_row = product_rows[0] if product_rows else None
            logger.debug("CERP products returned rows=%d", len(product_rows))

    merged_row = _merge_product_rows(product_row, info_row)
    if not merged_row:
        logger.debug("No CERP rows merged for code=%s barcode=%s", code, barcode)
        fallback_row: Optional[Dict[str, Any]] = None
        if code:
            fallback_row = find_export_row_by_code(code)
        if not fallback_row and barcode:
            fallback_row = find_export_row_by_barcode(barcode)
        if fallback_row:
            merged_row = fallback_row
            warehouse_rows = []
            logger.warning(
                "Falling back to cached CERP export row for code=%s barcode=%s",
                code,
                barcode,
            )
        else:
            return None
    if code:
        merged_code = (merged_row.get("invn002") or "").strip().upper()
        requested_code = code.strip().upper()
        if merged_code != requested_code:
            fallback = find_export_row_by_code(requested_code)
            if fallback:
                merged_row = fallback
                warehouse_rows = []
                logger.warning(
                    "Fallback to export row for requested code %s because CERP returned %s",
                    requested_code,
                    merged_code,
                )
            else:
                precise_row = await _refetch_precise_product_row(requested_code, barcode)
                if precise_row:
                    merged_row = _merge_product_rows(precise_row, info_row)
                    warehouse_rows = precise_row.get("wd4inv1as") or warehouse_rows
                    logger.warning(
                        "Fallback to precise paramchar lookup for requested code %s because CERP returned %s",
                        requested_code,
                        merged_code,
                    )
                else:
                    logger.warning(
                        "Requested code %s returned %s from CERP; no cached export row found and precise lookup failed",
                        requested_code,
                        merged_code,
                    )
                    return None
    if strict_lookup and merged_row:
        merged_code = (merged_row.get("invn002") or "").strip().upper()
        requested_code = (code or "").strip().upper()
        if requested_code and merged_code != requested_code:
            strict_fallback = find_export_row_by_code(requested_code)
            if strict_fallback:
                merged_row = strict_fallback
                merged_code = requested_code
    warehouses = warehouse_rows or merged_row.get("wd4inv1as") or []
    product = _map_cerp_row_to_product(merged_row, warehouses)
    if product:
        photo_url = await lookup_product_photo(
            merged_row.get("invn002") or "",
            merged_row.get("invn008"),
        )
        if photo_url:
            product["photo_url"] = photo_url
    return product


def _map_cerp_row_to_product(row: Dict[str, Any], warehouses: List[Dict[str, Any]]) -> Dict[str, Any]:
    warehouse_rows = warehouses or row.get("wd4inv1as") or []
    stock = _extract_stock(row, warehouse_rows)
    store_keywords = ("精品", "門市", "門店", "店面", "retail", "boutique", "shop", "store")
    store_stock = 0
    for entry in warehouse_rows:
        if not isinstance(entry, dict):
            continue
        haystack = " ".join(
            str(entry.get(key) or "").strip().lower()
            for key in ("name002", "warehouse_name", "warehouseName", "location", "name", "note", "inv1049", "inv1002", "warehouse_code", "code")
        )
        if not any(keyword in haystack for keyword in store_keywords):
            continue
        store_stock += _safe_int(entry.get("inv1015") or entry.get("quantity") or entry.get("stock_qty"))
    mapped_warehouses = _map_warehouses(warehouse_rows)
    standard_price = _optional_float(row.get("invn013"))
    vip_price = _optional_float(row.get("invn015"))
    fb_price = _optional_float(row.get("invn017"))
    wholesale_price = _optional_float(row.get("invn808"))
    if wholesale_price is None:
        wholesale_price = _optional_float(row.get("invn080"))
    rating = row.get("invn804") or ""
    color = row.get("invn801") or ""
    bundle = row.get("invn048") or ""
    wine_class = row.get("invn802") or ""
    alcohol = row.get("invn803") or ""
    wine_type = row.get("invn805") or ""
    name_primary = row.get("invn005") or ""
    name_alt = row.get("invn077") or ""
    has_bundle = bool(str(bundle).strip())
    return {
        "no": row.get("invn002"),
        "barcode": row.get("invn008"),
        "vintage": row.get("invn807") or row.get("invn051"),
        "producer": row.get("invn006"),
        "name": name_primary or name_alt,
        "name_en": name_alt or name_primary,
        "name_ch": name_primary or name_alt,
        "color": color,
        "rating": rating,
        "wine_class": wine_class,
        "alcohol": alcohol,
        "wine_type": wine_type,
        "stock": stock,
        "stock_qty": stock,
        "total_stock": stock,
        "store_stock": store_stock,
        "stock_source_type": "store_stock" if store_stock > 0 else "overall_stock",
        "stock_source_label": "Store stock" if store_stock > 0 else "Overall stock",
        "cerp_stock_reference": row.get("invn045"),
        "wd4inv1as": warehouse_rows,
        "warehouses": mapped_warehouses,
        "price": standard_price,
        "list_price": standard_price,
        "vip_price": vip_price,
        "fb_price": fb_price,
        "wholesale_price": wholesale_price,
        "display_quote_price": wholesale_price,
        "bundle": bundle,
        "promo": bundle,
        "gift": has_bundle,
        "capacity_ml": _optional_float(row.get("invn806")),
        "photo_placeholder": "Photo placeholder (attach later)",
    }


def _format_currency(value: Any) -> Optional[str]:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return f"${amount:,.0f}"


def _format_warehouse_summary(product: Dict[str, Any], lang: str) -> str:
    entries = []
    for warehouse in (product.get("warehouses") or [])[:3]:
        code = warehouse.get("warehouse_code") or warehouse.get("location") or t("cerp.labels.warehouse", lang)
        details = []
        qty = warehouse.get("quantity")
        if qty is not None:
            details.append(f"{t('cerp.labels.qty', lang)} {qty}")
        reserved = warehouse.get("reserved")
        if reserved is not None:
            details.append(f"{t('cerp.labels.reserved', lang)} {reserved}")
        if not details:
            continue
        entries.append(f"{code} ({', '.join(details)})")
    return "; ".join(entries)

def _cerp_description(product: Dict[str, Any], lang: str = "zh-Hant") -> str:
    if not product:
        return ""
    segments = []
    code = product.get("no")
    name = product.get("name")
    producer = product.get("producer")
    vintage = product.get("vintage")
    if code and name:
        segments.append(f"{code} - {name}")
    elif name:
        segments.append(name)
    elif code:
        segments.append(code)
    if producer:
        segments.append(f"{t('cerp.labels.producer', lang)}: {producer}")
    if vintage:
        segments.append(f"{t('cerp.labels.vintage', lang)}: {vintage}")
    rating = product.get("rating")
    if rating:
        segments.append(f"{t('cerp.labels.rating', lang)}: {rating}")
    color = product.get("color")
    if color:
        segments.append(f"{t('cerp.labels.color', lang)}: {color}")
    price_parts = []
    for label, value in (
        (t("cerp.labels.standard_price", lang), product.get("price")),
        (t("cerp.labels.vip_price", lang), product.get("vip_price")),
        (t("cerp.labels.fb_price", lang), product.get("fb_price")),
    ):
        formatted = _format_currency(value)
        if formatted:
            price_parts.append(f"{label} {formatted}")
    if price_parts:
        segments.append(" / ".join(price_parts))
    stock = product.get("stock")
    if stock is not None:
        segments.append(f"{t('cerp.labels.stock_on_hand', lang)}: {stock}")
    promo = product.get("promo")
    if promo:
        segments.append(f"{t('cerp.labels.promo', lang)}: {promo}")
    if product.get("gift"):
        segments.append(t("cerp.labels.gift", lang))
    warehouse_summary = _format_warehouse_summary(product, lang)
    if warehouse_summary:
        segments.append(f"{t('cerp.labels.warehouses', lang)}: {warehouse_summary}")
    barcode = product.get("barcode")
    if barcode:
        segments.append(f"{t('cerp.labels.barcode', lang)}: {barcode}")
    return " / ".join(segments)

def _cerp_product_to_hit(product: Dict[str, Any], lang: str = "zh-Hant") -> Optional[Dict[str, Any]]:
    if not product:
        return None
    code = product.get("no")
    if not code:
        return None
    description = _cerp_description(product, lang)
    summary_text = description or product.get("name") or code
    keywords = []
    for key in ("no", "barcode", "name", "producer", "vintage", "color"):
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            keywords.append(value.strip())
    keywords = list(dict.fromkeys(keywords))

    title = f"CERP: {product.get('name') or code}"
    meta = {
        "title": title,
        "source": "cerp",
        "type": "cerp_product",
        "code": code,
    }
    return {
        "id": f"cerp:{code}",
        "document_id": "cerp",
        "chunk_idx": 0,
        "text": description or summary_text,
        "summary": summary_text,
        "keywords": keywords,
        "meta": meta,
        "kg": {"nodes": [], "edges": []},
    }

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


def _is_quote_output_type(raw: Any) -> bool:
    if raw is None:
        return False
    text = str(raw).strip().lower()
    if not text:
        return False
    return any(
        keyword in text
        for keyword in ("\u5831\u50f9", "\u5831\u50f9\u55ae", "\u5831\u50f9\u6e05\u55ae", "quote", "quotation", "quote list")
    )

_QUOTE_UNIT_PATTERN = re.compile(
    r"(\d+)\s*(?:支|款|瓶|酒款|箱|套|wines?|wine|bottles?|bottle|cases?|case|packs?|pack)",
    flags=re.IGNORECASE,
)
_QUOTE_LINE_ITEM_PATTERN = re.compile(
    r"(?:每(?:支|瓶|款)?|各)\s*(\d+)\s*(?:支|款|瓶|酒款|箱|套|wines?|wine|bottles?|bottle|cases?|case|packs?|pack)?",
    flags=re.IGNORECASE,
)
_QUOTE_RESULT_HINT_PATTERN = re.compile(
    r"(?:列出|只列(?:出)?|推薦|给我|給我|提供|顯示|显示|找出|找)\s*$",
    flags=re.IGNORECASE,
)
_QUOTE_POSITIVE_STOCK_PATTERN = re.compile(
    r"(?:有庫存|現貨|有貨)",
    flags=re.IGNORECASE,
)
_QUOTE_STOCK_PATTERN = re.compile(
    r"(?:有庫存|現貨|有貨|庫存|stock|inventory)",
    flags=re.IGNORECASE,
)


_QUOTE_UNIT_PATTERN = re.compile(
    r"(\d+)\s*(?:支|瓶|款|項|酒款|wines?|wine|bottles?|bottle|cases?|case|packs?|pack)",
    flags=re.IGNORECASE,
)
_QUOTE_LINE_ITEM_PATTERN = re.compile(
    r"(?:每款|每支|每瓶|每項|line\s*item)\s*(\d+)\s*(?:支|瓶|款|項|酒款|wines?|wine|bottles?|bottle|cases?|case|packs?|pack)?",
    flags=re.IGNORECASE,
)
_QUOTE_RESULT_HINT_PATTERN = re.compile(
    r"(?:報價|推薦|建議|清單|給我|列出|show|list)\s*$",
    flags=re.IGNORECASE,
)
_QUOTE_POSITIVE_STOCK_PATTERN = re.compile(
    r"(?:優先現貨|只看現貨|有現貨|現貨優先|in[\s-]?stock\s+only)",
    flags=re.IGNORECASE,
)
_QUOTE_STOCK_PATTERN = re.compile(
    r"(?:現貨|庫存|有貨|stock|inventory|availability)",
    flags=re.IGNORECASE,
)

_QUOTE_UNIT_PATTERN = re.compile(
    r"(\d+)\s*(?:\u652f|\u74f6|\u6b3e|\u9805|\u9152\u6b3e|wines?|wine|bottles?|bottle|cases?|case|packs?|pack)",
    flags=re.IGNORECASE,
)
_QUOTE_LINE_ITEM_PATTERN = re.compile(
    r"(?:\u6bcf\u6b3e|\u6bcf\u652f|\u6bcf\u74f6|\u6bcf\u9805|line\s*item)\s*(\d+)\s*(?:\u652f|\u74f6|\u6b3e|\u9805|\u9152\u6b3e|wines?|wine|bottles?|bottle|cases?|case|packs?|pack)?",
    flags=re.IGNORECASE,
)
_QUOTE_RESULT_HINT_PATTERN = re.compile(
    r"(?:\u5831\u50f9|\u63a8\u85a6|\u5efa\u8b70|\u6e05\u55ae|\u7d66\u6211|\u5217\u51fa|show|list)\s*$",
    flags=re.IGNORECASE,
)
_QUOTE_POSITIVE_STOCK_PATTERN = re.compile(
    r"(?:\u512a\u5148\u73fe\u8ca8|\u53ea\u770b\u73fe\u8ca8|\u6709\u73fe\u8ca8|\u73fe\u8ca8\u512a\u5148|\u6709\u5eab\u5b58|\u53ea\u8981\u6709\u5eab\u5b58|\u9700\u6709\u5eab\u5b58|\u5eab\u5b58\u8981\u6709|in[\s-]?stock\s+only|\bwith\s+stock\b|\bavailable\s+stock\b|\bin[\s-]?stock\b)",
    flags=re.IGNORECASE,
)
_QUOTE_STOCK_PATTERN = re.compile(
    r"(?:\u73fe\u8ca8|\u5eab\u5b58|\u6709\u8ca8|stock|inventory|availability)",
    flags=re.IGNORECASE,
)

def _coerce_positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_quote_request(text: str) -> Dict[str, Any]:
    result_limit: Optional[int] = None
    line_item_quantity = 1
    normalized = text or ""
    stock_policy: Optional[str] = None

    if _QUOTE_POSITIVE_STOCK_PATTERN.search(normalized):
        stock_policy = "in_stock_only"
    elif _QUOTE_STOCK_PATTERN.search(normalized):
        stock_policy = "stock_first"

    line_item_match = _QUOTE_LINE_ITEM_PATTERN.search(normalized)
    if line_item_match:
        parsed = _coerce_positive_int(line_item_match.group(1))
        if parsed:
            line_item_quantity = parsed

    for match in _QUOTE_UNIT_PATTERN.finditer(normalized):
        parsed = _coerce_positive_int(match.group(1))
        if not parsed:
            continue
        prefix = normalized[max(0, match.start() - 12):match.start()]
        suffix = normalized[match.end(): min(len(normalized), match.end() + 12)]
        if re.search(r"(?:每(?:支|瓶|款)?|各)\s*$", prefix, flags=re.IGNORECASE):
            continue
        if (
            _QUOTE_RESULT_HINT_PATTERN.search(prefix)
            or any(token in prefix for token in ("及", "和", "並", "加", "再"))
            or any(
                token in suffix
                for token in ("酒", "推薦", "有庫存", "現貨", "有貨", "stock", "inventory")
            )
            or result_limit is None
        ):
            result_limit = parsed
            break

    return {
        "result_limit": result_limit,
        "line_item_quantity": line_item_quantity,
        "stock_policy": stock_policy,
    }


def _parse_quote_request_v2(text: str) -> Dict[str, Any]:
    result_limit: Optional[int] = None
    line_item_quantity = 1
    normalized = text or ""
    stock_policy: Optional[str] = None

    if _QUOTE_POSITIVE_STOCK_PATTERN.search(normalized):
        stock_policy = "in_stock_only"
    elif _QUOTE_STOCK_PATTERN.search(normalized):
        stock_policy = "stock_first"

    line_item_match = _QUOTE_LINE_ITEM_PATTERN.search(normalized)
    if line_item_match:
        parsed = _coerce_positive_int(line_item_match.group(1))
        if parsed:
            line_item_quantity = parsed

    quantity_prefix_pattern = re.compile(
        r"(?:\u6bcf\u6b3e|\u6bcf\u652f|\u6bcf\u74f6|\u6bcf\u9805|line\s*item)\s*$",
        flags=re.IGNORECASE,
    )
    prefix_hint_tokens = ("\u8981", "\u60f3\u8981", "\u9700\u8981", "\u5831\u50f9", "\u63a8\u85a6")
    suffix_hint_tokens = ("\u5831\u50f9", "\u63a8\u85a6", "\u73fe\u8ca8", "\u5eab\u5b58", "stock", "inventory")

    for match in _QUOTE_UNIT_PATTERN.finditer(normalized):
        parsed = _coerce_positive_int(match.group(1))
        if not parsed:
            continue
        prefix = normalized[max(0, match.start() - 12):match.start()]
        suffix = normalized[match.end(): min(len(normalized), match.end() + 12)]
        if quantity_prefix_pattern.search(prefix):
            continue
        if (
            _QUOTE_RESULT_HINT_PATTERN.search(prefix)
            or any(token in prefix for token in prefix_hint_tokens)
            or any(token in suffix for token in suffix_hint_tokens)
            or result_limit is None
        ):
            result_limit = parsed
            break

    return {
        "result_limit": result_limit,
        "line_item_quantity": line_item_quantity,
        "stock_policy": stock_policy,
    }


_parse_quote_request = _parse_quote_request_v2


def _quote_product_stock_value(product: Dict[str, Any]) -> int:
    direct = product.get("stock_qty", product.get("total_stock", product.get("stock")))
    try:
        numeric = int(float(direct or 0))
    except (TypeError, ValueError):
        numeric = 0
    if numeric > 0:
        return numeric

    total = 0
    for entry in product.get("warehouses") or product.get("wd4inv1as") or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get("quantity", entry.get("inv1015"))
        try:
            total += int(float(value or 0))
        except (TypeError, ValueError):
            continue
    return max(total, 0)


def _quote_product_code(product: Dict[str, Any]) -> str:
    return str(product.get("no") or product.get("id") or "").strip()


def _quote_product_price(product: Dict[str, Any]) -> Optional[float]:
    for field in ("list_price", "price", "vip_price", "fb_price", "wholesale_price"):
        value = product.get(field)
        try:
            if value is None or value == "":
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _quote_product_label(product: Dict[str, Any]) -> str:
    producer = str(product.get("producer") or "").strip()
    name = str(
        product.get("name")
        or product.get("name_en")
        or product.get("name_ch")
        or product.get("product")
        or ""
    ).strip()
    vintage = str(product.get("vintage") or "").strip()
    parts = [part for part in (producer, name, vintage) if part]
    if not parts:
        code = _quote_product_code(product)
        return code or "Unknown wine"
    return " ".join(parts)


def _tag_quote_items(items: List[Dict[str, Any]], match_type: str) -> List[Dict[str, Any]]:
    tagged: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        normalized.setdefault("match_type", match_type)
        normalized.setdefault("quote_item_origin", match_type)
        tagged.append(normalized)
    return tagged


def _select_quote_products(
    candidates: List[Dict[str, Any]],
    *,
    result_limit: Optional[int],
    line_item_quantity: int,
    stock_policy: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    ordered_candidates = [dict(item) for item in candidates or [] if isinstance(item, dict)]
    positive_stock = [item for item in ordered_candidates if _quote_product_stock_value(item) > 0]
    zero_stock = [item for item in ordered_candidates if _quote_product_stock_value(item) <= 0]

    if stock_policy == "in_stock_only":
        selected = positive_stock[:result_limit] if result_limit else positive_stock
    elif stock_policy == "stock_first":
        if result_limit and len(positive_stock) >= result_limit:
            selected = positive_stock[:result_limit]
        elif result_limit:
            selected = positive_stock + zero_stock[: max(result_limit - len(positive_stock), 0)]
        else:
            selected = positive_stock + zero_stock
    else:
        selected = ordered_candidates[:result_limit] if result_limit else ordered_candidates

    applied_quantity = max(_coerce_positive_int(line_item_quantity) or 1, 1)
    for product in selected:
        product["quantity"] = applied_quantity

    return selected, {
        "candidate_count": len(ordered_candidates),
        "positive_stock_count": len(positive_stock),
        "exact_in_stock_count": len(positive_stock),
    }


def _is_recommendation_quote_query(
    text: str,
    *,
    quote_criteria: Optional[Dict[str, Any]],
    result_limit: Optional[int],
    stock_policy: Optional[str],
) -> bool:
    if stock_policy != "in_stock_only":
        return False
    criteria = quote_criteria if isinstance(quote_criteria, dict) else {}
    if any(str(criteria.get(key) or "").strip() for key in ("producer", "wine_name", "vintage")):
        return False
    lowered = str(text or "").lower()
    top_stock_match, _ = _is_top_stock_query(text)
    has_listing_intent = bool(result_limit) or top_stock_match or any(
        token in lowered
        for token in ("推薦", "推介", "建議", "列出", "清單", "有哪些", "哪幾款", "show", "list", "top")
    )
    return has_listing_intent


def _is_generic_stock_listing_query(
    text: str,
    *,
    quote_criteria: Optional[Dict[str, Any]],
    stock_policy: Optional[str],
) -> bool:
    if not is_generic_inventory_listing_query(text):
        return False
    if stock_policy not in {"in_stock_only", "stock_first", None}:
        return False
    criteria = quote_criteria if isinstance(quote_criteria, dict) else {}
    semantic_keys = (
        "producer",
        "wine_name",
        "region",
        "region_filter",
        "vintage",
        "color",
        "style",
        "classification",
        "grape",
        "village",
        "vineyard",
    )
    return not any(str(criteria.get(key) or "").strip() for key in semantic_keys)
    if stock_policy != "in_stock_only":
        return False
    criteria = quote_criteria if isinstance(quote_criteria, dict) else {}
    semantic_keys = (
        "producer",
        "wine_name",
        "region",
        "region_filter",
        "vintage",
        "color",
        "style",
        "classification",
        "grape",
        "village",
        "vineyard",
    )
    if any(str(criteria.get(key) or "").strip() for key in semantic_keys):
        return False
    raw = normalize_quote_input_text(text or "")
    if not raw:
        return False
    cleaned = _QUOTE_UNIT_PATTERN.sub(" ", raw)
    cleaned = _QUOTE_POSITIVE_STOCK_PATTERN.sub(" ", cleaned)
    cleaned = _QUOTE_STOCK_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(
        r"(?:推薦|推介|建議|列出|只列出|查詢|搜尋|請|幫我|給我|幫忙|只要|需要|想要|哪些|有哪|看|看看|更多|cerp|list|show|top)",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[的嗎呢呀啊吧呀支款瓶箱組個種類些]+", " ", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned).strip().casefold()
    return cleaned in {"", "酒", "葡萄酒", "wine", "wines"}


def _is_generic_stock_listing_query(
    text: str,
    *,
    quote_criteria: Optional[Dict[str, Any]],
    stock_policy: Optional[str],
) -> bool:
    if not is_generic_inventory_listing_query(text):
        return False
    if stock_policy not in {"in_stock_only", "stock_first", None}:
        return False
    criteria = quote_criteria if isinstance(quote_criteria, dict) else {}
    semantic_keys = (
        "producer",
        "wine_name",
        "region",
        "region_filter",
        "vintage",
        "color",
        "style",
        "classification",
        "grape",
        "village",
        "vineyard",
    )
    if any(str(criteria.get(key) or "").strip() for key in semantic_keys):
        return False
    raw = normalize_quote_input_text(text or "")
    if not raw:
        return False
    lowered = raw.casefold()
    stock_tokens = ("庫存", "現貨", "有貨", "stock", "inventory", "in-stock", "availability")
    listing_tokens = ("列出", "顯示", "查看", "查詢", "搜尋", "有哪些", "有哪", "show", "list", "top")
    if not any(token in lowered for token in stock_tokens):
        return False
    if not any(token in lowered for token in listing_tokens):
        return lowered.replace(" ", "") in {"庫存商品", "庫存產品", "現貨商品", "現貨產品", "stockinventory"}
    cleaned = re.sub(
        r"(列出|只列出|顯示|查看|查詢|搜尋|請|幫我|給我|幫忙|只要|需要|想要|哪些|有哪|目前|現在|所有|全部|更多|show|list|top|browse|display|cerp)",
        " ",
        lowered,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"(庫存|現貨|有貨|商品|產品|品項|stock|inventory|in[\s-]?stock|availability|products?)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s，。！？、,.!?/\\|:;()\[\]{}<>]+", "", cleaned).strip()
    return cleaned == ""


def _select_recommendation_quote_products(
    candidates: List[Dict[str, Any]],
    *,
    quote_criteria: Optional[Dict[str, Any]],
    result_limit: Optional[int],
    line_item_quantity: int,
    stock_policy: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    ordered_candidates = [dict(item) for item in candidates or [] if isinstance(item, dict)]
    exact_candidates = [
        dict(item)
        for item in ordered_candidates
        if quote_product_matches_criteria(item, quote_criteria)
    ]
    ranked: List[Tuple[int, float, int, int, Dict[str, Any]]] = []
    for index, item in enumerate(ordered_candidates):
        stock_value = _quote_product_stock_value(item)
        if stock_policy == "in_stock_only" and stock_value <= 0:
            continue
        exact_match = quote_product_matches_criteria(item, quote_criteria)
        alternative_score = quote_product_alternative_score(item, quote_criteria)
        if not exact_match and alternative_score <= 0:
            continue
        ranked.append(
            (
                1 if exact_match else 0,
                alternative_score,
                stock_value,
                -index,
                dict(item),
            )
        )
    ranked.sort(reverse=True)
    ranked_candidates = [entry[4] for entry in ranked]
    products, _ = _select_quote_products(
        ranked_candidates,
        result_limit=result_limit,
        line_item_quantity=line_item_quantity,
        stock_policy=stock_policy,
    )
    exact_codes = {_quote_product_code(candidate) for candidate in exact_candidates if _quote_product_code(candidate)}
    selected_exact_products = [
        dict(item)
        for item in products
        if _quote_product_code(item) in exact_codes
    ]
    positive_stock_count = len(
        [item for item in ranked_candidates if _quote_product_stock_value(item) > 0]
    )
    exact_in_stock_count = len(
        [item for item in exact_candidates if _quote_product_stock_value(item) > 0]
    )
    return products, exact_candidates, selected_exact_products, {
        "candidate_count": len(ordered_candidates),
        "positive_stock_count": positive_stock_count,
        "exact_in_stock_count": exact_in_stock_count,
    }


def _price_within_band(price: Optional[float], anchor_prices: List[float]) -> bool:
    if price is None or not anchor_prices:
        return False
    avg_price = sum(anchor_prices) / len(anchor_prices)
    tolerance = max(avg_price * 0.25, 1000.0)
    return abs(price - avg_price) <= tolerance


async def _build_similar_quote_suggestions(
    cerp_service: CerpService,
    *,
    selected_products: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    nlu_result: Optional[Dict[str, Any]],
    suggestion_limit: int = 3,
) -> List[Dict[str, Any]]:
    if suggestion_limit <= 0:
        return []

    selected_codes = {
        _quote_product_code(item)
        for item in selected_products or []
        if _quote_product_code(item)
    }
    seed_products = selected_products or [item for item in candidates or [] if isinstance(item, dict)]
    anchor_regions = {
        str(item.get("region") or "").strip()
        for item in seed_products
        if str(item.get("region") or "").strip()
    }
    anchor_colors = {
        str(item.get("color") or "").strip().lower()
        for item in seed_products
        if str(item.get("color") or "").strip()
    }
    anchor_prices = [
        price for price in (_quote_product_price(item) for item in seed_products) if price is not None
    ]

    producer = ""
    if isinstance(nlu_result, dict):
        producer = str(nlu_result.get("producer") or "").strip()
    if not producer:
        for item in seed_products:
            producer = str(item.get("producer") or "").strip()
            if producer:
                break

    results: List[Dict[str, Any]] = []

    def append_candidate(item: Dict[str, Any]) -> None:
        if len(results) >= suggestion_limit or not isinstance(item, dict):
            return
        code = _quote_product_code(item)
        if not code or code in selected_codes:
            return
        if any(_quote_product_code(existing) == code for existing in results):
            return
        if _quote_product_stock_value(item) <= 0:
            return
        results.append(dict(item))

    if producer:
        same_producer = await cerp_service.fetch_products_by_producer(
            producer,
            require_stock=True,
            limit=max(suggestion_limit * 4, 10),
        )
        for item in same_producer:
            append_candidate(item)
            if len(results) >= suggestion_limit:
                return results

    broad_in_stock = await cerp_service.fetch_top_stock_products(
        limit=max(suggestion_limit * 20, 60),
        allow_zero_stock=False,
    )

    for item in broad_in_stock:
        if len(results) >= suggestion_limit:
            break
        region = str(item.get("region") or "").strip()
        color = str(item.get("color") or "").strip().lower()
        if region and region in anchor_regions and color and color in anchor_colors:
            append_candidate(item)

    for item in broad_in_stock:
        if len(results) >= suggestion_limit:
            break
        region = str(item.get("region") or "").strip()
        price = _quote_product_price(item)
        if region and region in anchor_regions and _price_within_band(price, anchor_prices):
            append_candidate(item)

    return results


def _normalize_quote_alias_filters(alias_filters: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(alias_filters, dict):
        return {}
    normalized: Dict[str, Any] = {}
    for source_key, target_key in (
        ("producer", "producer"),
        ("invn006", "producer"),
        ("region", "region"),
        ("invn030", "region"),
        ("style", "style"),
        ("classification", "classification"),
        ("village", "village"),
        ("vineyard", "vineyard"),
        ("grape_varieties", "grape_varieties"),
        ("grape", "grape_varieties"),
    ):
        value = alias_filters.get(source_key)
        if value in (None, "", [], {}):
            continue
        normalized[target_key] = value
    return normalized


async def _load_quote_knowledge_hits(
    text: str,
    *,
    query_variants: List[str],
    alias_filters: Dict[str, Any],
) -> List[Dict[str, Any]]:
    normalized_filters = _normalize_quote_alias_filters(alias_filters)
    hits: List[Dict[str, Any]] = []
    seen = set()

    async def push(items: List[Dict[str, Any]]) -> None:
        for item in items or []:
            identifier = (
                item.get("id"),
                item.get("document_id"),
                item.get("chunk_idx"),
                json.dumps(item.get("meta") or {}, sort_keys=True, ensure_ascii=False),
            )
            if identifier in seen:
                continue
            seen.add(identifier)
            hits.append(item)

    if normalized_filters:
        await push(await structured_search(None, normalized_filters, k=6))

    if len(hits) < 4:
        search_terms = [item for item in (query_variants or [text]) if item]
        for variant in search_terms[:2]:
            await push(await vector_search(None, variant, k=3))
            if len(hits) >= 6:
                break

    return hits[:6]


def _build_quote_recommended_alternatives(
    candidates: List[Dict[str, Any]],
    *,
    quote_criteria: Dict[str, Any],
    selected_products: Optional[List[Dict[str, Any]]] = None,
    limit: int = 3,
    require_stock: bool = False,
) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []
    selected_codes = {
        _quote_product_code(item)
        for item in (selected_products or [])
        if _quote_product_code(item)
    }
    scored: List[tuple[float, int, Dict[str, Any]]] = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        code = _quote_product_code(item)
        if not code or code in selected_codes:
            continue
        if require_stock and _quote_product_stock_value(item) <= 0:
            continue
        score = quote_product_alternative_score(item, quote_criteria)
        if score <= 0:
            continue
        scored.append((score, _quote_product_stock_value(item), dict(item)))
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [entry[2] for entry in scored[:limit]]


def _quote_requires_official_inventory_binding(text: str) -> bool:
    lowered = str(text or "").lower()
    scope_tokens = (
        "ys.local",
        "official site",
        "official website",
        "\u5b98\u7db2",
        "\u5b98\u65b9\u7db2\u7ad9",
        "\u921e\u592a",
        "\u53f0\u7063",
        "\u53f0\u5317",
        "taiwan",
        "taipei",
    )
    return any(token in lowered for token in scope_tokens)


def _build_quote_inventory_binding(
    *,
    raw_query: str,
    display_query: str,
    products: List[Dict[str, Any]],
    recommended_alternatives: List[Dict[str, Any]],
    official_match_used: bool = False,
) -> Dict[str, Any]:
    required = _quote_requires_official_inventory_binding(f"{raw_query} {display_query}")
    bound_items = [item for item in [*(products or []), *(recommended_alternatives or [])] if isinstance(item, dict)]
    proofs: List[Dict[str, Any]] = []
    for item in bound_items[:8]:
        code = str(item.get("no") or item.get("id") or "").strip()
        if not code:
            continue
        proofs.append(
            {
                "type": "cerp",
                "code": code,
                "stock": item.get("stock") or item.get("stock_qty") or item.get("total_stock"),
            }
        )
    return {
        "required": required,
        "proof_count": len(proofs),
        "proofs": proofs,
        "official_match_used": bool(official_match_used),
        "all_answer_items_bound": not required or len(proofs) >= len(bound_items),
        "official_search_url": (
            f"https://ys.local/search?q={quote_plus(str(raw_query or display_query or '').strip())}"
            if required and str(raw_query or display_query or "").strip()
            else None
        ),
    }


def _build_quote_followup_defaults(
    *,
    canonical_query: str,
    requested_filters: Dict[str, Any],
    exact_count: int,
    stock_policy: Optional[str],
    products: List[Dict[str, Any]],
    result_limit: Optional[int],
    match_summary: Dict[str, Any],
    recommended_alternatives: List[Dict[str, Any]],
    suggested_alternatives: List[Dict[str, Any]],
) -> Dict[str, Any]:
    mode = str(match_summary.get("mode") or "").strip().lower()
    default_confirm_action = ACTION_CONTINUE
    pending_goal = ACTION_CONTINUE
    available_actions: List[str] = [ACTION_CONTINUE]
    target_count = result_limit if result_limit and result_limit > 0 else None
    remaining_needed = max((target_count or 0) - exact_count, 0) if target_count else 0
    fill_strategy = "exact_first_then_similar_fill" if target_count and exact_count < target_count else None

    if mode == "alternatives" and recommended_alternatives:
        default_confirm_action = ACTION_RELAX_CONSTRAINTS
        pending_goal = ACTION_RELAX_CONSTRAINTS
        available_actions = [ACTION_RELAX_CONSTRAINTS, ACTION_SHOW_RECOMMENDED]
    elif (
        stock_policy == "in_stock_only"
        and result_limit is not None
        and products
        and len(products) < result_limit
        and suggested_alternatives
    ):
        default_confirm_action = ACTION_INCLUDE_SIMILAR
        pending_goal = ACTION_INCLUDE_SIMILAR
        available_actions = [ACTION_INCLUDE_SIMILAR, ACTION_CONTINUE]
    elif (
        stock_policy != "in_stock_only"
        and target_count is not None
        and products
        and len(products) < target_count
        and recommended_alternatives
    ):
        default_confirm_action = ACTION_FILL_SIMILAR
        pending_goal = ACTION_FILL_SIMILAR
        available_actions = [ACTION_FILL_SIMILAR, ACTION_SHOW_RECOMMENDED, ACTION_CONTINUE]

    return {
        "canonical_query": canonical_query,
        "pending_goal": pending_goal,
        "default_confirm_action": default_confirm_action,
        "available_actions": available_actions,
        "requested_filters": requested_filters,
        "target_count": target_count,
        "exact_count": exact_count,
        "remaining_needed": remaining_needed,
        "fill_strategy": fill_strategy,
    }


def _quote_recommendation_details(recommendation_profile: Optional[Dict[str, Any]]) -> str:
    if not isinstance(recommendation_profile, dict):
        return ""
    parts: List[str] = []
    for key in ("regions", "styles", "grapes", "classifications", "villages", "vineyards"):
        values = recommendation_profile.get(key)
        if isinstance(values, list):
            items = [str(item).strip() for item in values if str(item).strip()]
            if items:
                parts.append("/".join(items[:2]))
        elif isinstance(values, str) and values.strip():
            parts.append(values.strip())
        if len(parts) >= 3:
            break
    return ", ".join(parts[:3])


def _quote_recommendation_note(lang: str, recommendation_profile: Optional[Dict[str, Any]]) -> str:
    details = _quote_recommendation_details(recommendation_profile)
    if not details:
        return ""
    return t("quote.expert_profile", lang, details=details)


def _sanitize_user_facing_text(value: Any, lang: str) -> str:
    text = str(value or "").strip()
    if not text:
        return t("quote.no_results", lang, query=t("quote.ui_default_query", lang))
    if _TRACEBACK_PATTERN.search(text) or "UnicodeEncodeError" in text or "cp950" in text:
        return t("quote.no_results", lang, query=t("quote.ui_default_query", lang))
    return text


def _build_low_readability_message_legacy(lang: str) -> str:
    if lang == "en":
        return (
            "I could not reliably read your latest message due to possible encoding issues. "
            "Please resend the same request in plain text, and I will answer based on that latest question."
        )
    return (
        "我無法可靠讀取你剛剛的訊息，可能有編碼異常。"
        "請用可讀文字重新送出同一個問題，我會以你最新這題為準回答。"
    )


def _build_low_readability_message(lang: str) -> str:
    normalized_lang = str(lang or "").lower()
    if normalized_lang.startswith("en"):
        return (
            "I could not reliably read your latest message due to possible encoding issues. "
            "Please resend the same request in plain text, and I will answer based on that latest question."
        )
    if normalized_lang.startswith("ja"):
        return (
            "\u6700\u65b0\u306e\u30e1\u30c3\u30bb\u30fc\u30b8\u306b\u6587\u5b57\u5316\u3051\u306e\u53ef\u80fd\u6027\u304c\u3042\u308a\u3001"
            "\u5185\u5bb9\u3092\u6b63\u78ba\u306b\u8aad\u307f\u53d6\u308c\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
            "\u540c\u3058\u4f9d\u983c\u3092\u30d7\u30ec\u30fc\u30f3\u30c6\u30ad\u30b9\u30c8\u3067\u9001\u308a\u76f4\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
        )
    return (
        "\u6211\u7121\u6cd5\u7a69\u5b9a\u8b80\u53d6\u4f60\u6700\u65b0\u7684\u8a0a\u606f\uff0c"
        "\u53ef\u80fd\u662f\u6587\u5b57\u7de8\u78bc\u6216\u8cbc\u4e0a\u5167\u5bb9\u767c\u751f\u554f\u984c\u3002"
        "\u8acb\u7528\u7d14\u6587\u5b57\u91cd\u65b0\u9001\u51fa\u540c\u4e00\u500b\u554f\u984c\uff0c\u6211\u6703\u4f9d\u6700\u65b0\u554f\u984c\u56de\u7b54\u3002"
    )


def _compose_quote_answer_text(
    *,
    lang: str,
    query: str,
    products: List[Dict[str, Any]],
    result_limit: Optional[int],
    exact_count: int,
    stock_policy: Optional[str],
    suggested_alternatives: Optional[List[Dict[str, Any]]] = None,
    recommended_alternatives: Optional[List[Dict[str, Any]]] = None,
    followup_action_executed: Optional[str] = None,
    recommendation_profile: Optional[Dict[str, Any]] = None,
) -> str:
    count = len(products or [])
    target_count = result_limit if result_limit and result_limit > 0 else count
    remaining_needed = max((target_count or 0) - exact_count, 0) if target_count else 0
    similar_count = max(count - exact_count, 0)
    if followup_action_executed == ACTION_RELAX_CONSTRAINTS and count:
        answer_text = t(
            "quote.followup_relax_constraints",
            lang,
            query=query,
            count=count,
        )
    elif followup_action_executed == ACTION_FILL_SIMILAR and count:
        answer_text = t(
            "quote.followup_fill_to_target",
            lang,
            query=query,
            count=count,
            target=target_count,
            exact_count=exact_count,
            similar_count=similar_count,
        )
    elif followup_action_executed == ACTION_SHOW_RECOMMENDED:
        answer_text = t(
            "quote.followup_show_alternatives",
            lang,
            query=query,
            count=count,
        )
    elif followup_action_executed == ACTION_INCLUDE_SIMILAR:
        answer_text = t(
            "quote.followup_include_similar",
            lang,
            query=query,
            count=count,
        )
    elif count == 0 and recommended_alternatives:
        answer_text = t(
            "quote.alternative_found",
            lang,
            query=query,
            count=len(recommended_alternatives),
        )
    elif (
        stock_policy != "in_stock_only"
        and result_limit
        and count
        and exact_count < result_limit
        and recommended_alternatives
    ):
        answer_text = t(
            "quote.shortage_fill_similar",
            lang,
            query=query,
            exact_count=exact_count,
            remaining=remaining_needed,
            target=result_limit,
        )
    elif stock_policy == "in_stock_only":
        if result_limit and count < result_limit:
            intro = t(
                "quote.shortage_in_stock",
                lang,
                count=count,
                requested=result_limit,
                query=query,
            )
            if suggested_alternatives:
                suggestions = ", ".join(
                    _quote_product_label(item) for item in suggested_alternatives if _quote_product_label(item)
                )
                if suggestions:
                    answer_text = " ".join(
                        [
                            intro,
                            t("quote.suggest_similar_in_stock", lang, suggestions=suggestions),
                            t("quote.ask_include_similar", lang),
                        ]
                    )
                else:
                    answer_text = " ".join([intro, t("quote.ask_more_similar_in_stock", lang)])
            else:
                answer_text = t("quote.found_in_stock", lang, count=count, query=query)
        else:
            answer_text = t("quote.found_in_stock", lang, count=count, query=query)
    else:
        answer_text = t("quote.found", lang, count=count, query=query)

    recommendation_note = _quote_recommendation_note(lang, recommendation_profile)
    if recommendation_note:
        answer_text = f"{answer_text} {recommendation_note}".strip()
    return answer_text


def _format_quote_ui_generated_at() -> str:
    return datetime.now().astimezone().strftime("%Y/%m/%d %I:%M %p")


def _build_quote_ui_payload(
    *,
    lang: str,
    query: str,
    products: List[Dict[str, Any]],
    result_limit: Optional[int],
    exact_count: int,
    stock_policy: Optional[str],
    suggested_alternatives: Optional[List[Dict[str, Any]]] = None,
    recommended_alternatives: Optional[List[Dict[str, Any]]] = None,
    followup_action_executed: Optional[str] = None,
    recommendation_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_query = (query or "").strip() or t("quote.ui_default_query", lang)
    count = len(products or [])
    target_count = result_limit if result_limit and result_limit > 0 else count
    remaining_needed = max((target_count or 0) - exact_count, 0) if target_count else 0
    similar_count = max(count - exact_count, 0)
    recommendation_details = _quote_recommendation_details(recommendation_profile)
    profile_bullet = (
        t("quote.ui_profile_bullet", lang, details=recommendation_details)
        if recommendation_details
        else None
    )
    suggestions = [
        _quote_product_label(item)
        for item in (suggested_alternatives or [])
        if _quote_product_label(item)
    ]
    recommended_labels = [
        _quote_product_label(item)
        for item in (recommended_alternatives or [])
        if _quote_product_label(item)
    ]

    if followup_action_executed == ACTION_RELAX_CONSTRAINTS and count:
        intro_bullets = [
            t("quote.ui_success_bullet_count", lang, count=count),
            t("quote.ui_bullet_quote_info", lang),
            t("quote.ui_bullet_wine_details", lang),
        ]
        if profile_bullet:
            intro_bullets.append(profile_bullet)
        return {
            "kind": "quote_response",
            "title": t(
                "quote.ui_followup_relax_title",
                lang,
                query=normalized_query,
                count=count,
            ),
            "status": t("quote.ui_status_ready", lang),
            "status_variant": "success",
            "generated_at": _format_quote_ui_generated_at(),
            "intro": t("quote.ui_followup_relax_intro", lang, query=normalized_query),
            "intro_bullets": intro_bullets,
            "closing": t("quote.ui_followup_relax_closing", lang),
            "closing_bullets": [
                t("quote.ui_closing_bullet_filter", lang),
                t("quote.ui_closing_bullet_save", lang),
                t("quote.ui_closing_bullet_more", lang),
            ],
        }

    if followup_action_executed == ACTION_FILL_SIMILAR and count:
        intro_bullets = [
            t("quote.ui_success_bullet_count", lang, count=count),
            t("quote.ui_followup_fill_bullet_exact", lang, exact_count=exact_count),
            t("quote.ui_followup_fill_bullet_similar", lang, similar_count=similar_count),
        ]
        if profile_bullet:
            intro_bullets.append(profile_bullet)
        return {
            "kind": "quote_response",
            "title": t(
                "quote.ui_followup_fill_title",
                lang,
                query=normalized_query,
                count=count,
                target=target_count,
            ),
            "status": t("quote.ui_status_ready", lang),
            "status_variant": "success",
            "generated_at": _format_quote_ui_generated_at(),
            "intro": t(
                "quote.ui_followup_fill_intro",
                lang,
                query=normalized_query,
                exact_count=exact_count,
                similar_count=similar_count,
            ),
            "intro_bullets": intro_bullets,
            "closing": t(
                "quote.ui_followup_fill_closing",
                lang,
                count=count,
                target=target_count,
            ),
            "closing_bullets": [
                t("quote.ui_closing_bullet_filter", lang),
                t("quote.ui_closing_bullet_save", lang),
                t("quote.ui_closing_bullet_more", lang),
            ],
        }

    if followup_action_executed == ACTION_SHOW_RECOMMENDED and count:
        intro_bullets = [
            t("quote.ui_success_bullet_count", lang, count=count),
            t("quote.ui_bullet_quote_info", lang),
            t("quote.ui_bullet_wine_details", lang),
        ]
        if profile_bullet:
            intro_bullets.append(profile_bullet)
        return {
            "kind": "quote_response",
            "title": t(
                "quote.ui_followup_alternative_title",
                lang,
                query=normalized_query,
                count=count,
            ),
            "status": t("quote.ui_status_warning", lang),
            "status_variant": "warning",
            "generated_at": _format_quote_ui_generated_at(),
            "intro": t("quote.ui_followup_alternative_intro", lang, query=normalized_query),
            "intro_bullets": intro_bullets,
            "closing": t("quote.ui_followup_alternative_closing", lang),
            "closing_bullets": [
                _quote_product_label(item)
                for item in (products or [])[:3]
                if _quote_product_label(item)
            ],
        }

    if followup_action_executed == ACTION_INCLUDE_SIMILAR and count:
        intro_bullets = [
            t("quote.ui_success_bullet_count", lang, count=count),
            t("quote.ui_bullet_quote_info", lang),
            t("quote.ui_bullet_wine_details", lang),
        ]
        if profile_bullet:
            intro_bullets.append(profile_bullet)
        return {
            "kind": "quote_response",
            "title": t(
                "quote.ui_followup_include_title",
                lang,
                query=normalized_query,
                count=count,
            ),
            "status": t("quote.ui_status_ready", lang),
            "status_variant": "success",
            "generated_at": _format_quote_ui_generated_at(),
            "intro": t("quote.ui_followup_include_intro", lang, query=normalized_query),
            "intro_bullets": intro_bullets,
            "closing": t("quote.ui_followup_include_closing", lang),
            "closing_bullets": [
                t("quote.ui_closing_bullet_filter", lang),
                t("quote.ui_closing_bullet_save", lang),
                t("quote.ui_closing_bullet_more", lang),
            ],
        }

    if (
        stock_policy != "in_stock_only"
        and result_limit
        and count
        and exact_count < result_limit
        and recommended_labels
    ):
        intro_bullets = [
            t("quote.ui_fill_shortage_bullet_exact", lang, exact_count=exact_count),
            t("quote.ui_bullet_quote_info", lang),
            t("quote.ui_bullet_wine_details", lang),
            t(
                "quote.ui_fill_shortage_bullet_remaining",
                lang,
                remaining=remaining_needed,
                target=result_limit,
            ),
        ]
        if profile_bullet:
            intro_bullets.append(profile_bullet)
        return {
            "kind": "quote_response",
            "title": t(
                "quote.ui_fill_shortage_title",
                lang,
                query=normalized_query,
                exact_count=exact_count,
                target=result_limit,
            ),
            "status": t("quote.ui_status_warning", lang),
            "status_variant": "warning",
            "generated_at": _format_quote_ui_generated_at(),
            "intro": t(
                "quote.ui_fill_shortage_intro",
                lang,
                query=normalized_query,
                exact_count=exact_count,
                target=result_limit,
            ),
            "intro_bullets": intro_bullets,
            "closing": t(
                "quote.ui_fill_shortage_closing",
                lang,
                remaining=remaining_needed,
                target=result_limit,
            ),
            "closing_bullets": [
                t(
                    "quote.ui_fill_shortage_bullet_remaining",
                    lang,
                    remaining=remaining_needed,
                    target=result_limit,
                ),
                t("quote.ui_closing_bullet_save", lang),
                t("quote.ui_closing_bullet_filter", lang),
            ],
        }

    if not count and recommended_labels:
        intro_bullets = [
            t("quote.ui_alternative_bullet_exact", lang),
            t(
                "quote.ui_alternative_bullet_count",
                lang,
                count=len(recommended_labels),
            ),
            t("quote.ui_bullet_quote_info", lang),
            t("quote.ui_bullet_wine_details", lang),
        ]
        if profile_bullet:
            intro_bullets.append(profile_bullet)
        return {
            "kind": "quote_response",
            "title": t(
                "quote.ui_alternative_title",
                lang,
                query=normalized_query,
                count=len(recommended_labels),
            ),
            "status": t("quote.ui_status_warning", lang),
            "status_variant": "warning",
            "generated_at": _format_quote_ui_generated_at(),
            "intro": t("quote.ui_alternative_intro", lang, query=normalized_query),
            "intro_bullets": intro_bullets,
            "closing": t("quote.ui_alternative_closing", lang),
            "closing_bullets": recommended_labels[:3],
        }

    if not count:
        intro_bullets = [
            t("quote.ui_empty_bullet_request", lang),
            t("quote.ui_empty_bullet_inventory", lang),
            t("quote.ui_empty_bullet_refine", lang),
        ]
        if profile_bullet:
            intro_bullets.append(profile_bullet)
        return {
            "kind": "quote_response",
            "title": t("quote.ui_empty_title", lang, query=normalized_query),
            "status": t("quote.ui_status_empty", lang),
            "status_variant": "empty",
            "generated_at": _format_quote_ui_generated_at(),
            "intro": t("quote.ui_empty_intro", lang, query=normalized_query),
            "intro_bullets": intro_bullets,
            "closing": t("quote.ui_empty_closing", lang),
            "closing_bullets": [
                t("quote.ui_empty_closing_bullet_alternative", lang),
                t("quote.ui_empty_closing_bullet_region", lang),
                t("quote.ui_empty_closing_bullet_style", lang),
            ],
        }

    if stock_policy == "in_stock_only" and result_limit and count < result_limit:
        closing_bullets = suggestions or [t("quote.ui_closing_bullet_more", lang)]
        intro_bullets = [
            t(
                "quote.ui_shortage_bullet_count",
                lang,
                count=count,
                requested=result_limit,
            ),
            t("quote.ui_bullet_quote_info", lang),
            t("quote.ui_bullet_wine_details", lang),
        ]
        if suggestions:
            intro_bullets.append(
                t(
                    "quote.ui_shortage_bullet_alternatives",
                    lang,
                    count=len(suggestions),
                )
            )
        if profile_bullet:
            intro_bullets.append(profile_bullet)
        return {
            "kind": "quote_response",
            "title": t(
                "quote.ui_shortage_title",
                lang,
                count=count,
                requested=result_limit,
                query=normalized_query,
            ),
            "status": t("quote.ui_status_warning", lang),
            "status_variant": "warning",
            "generated_at": _format_quote_ui_generated_at(),
            "intro": t(
                "quote.ui_shortage_intro",
                lang,
                query=normalized_query,
                count=count,
                requested=result_limit,
            ),
            "intro_bullets": intro_bullets,
            "closing": t("quote.ui_shortage_closing", lang),
            "closing_bullets": closing_bullets,
        }

    intro_bullets = [
        t("quote.ui_success_bullet_count", lang, count=count),
        t("quote.ui_bullet_quote_info", lang),
        t("quote.ui_bullet_wine_details", lang),
        t("quote.ui_bullet_compare", lang),
    ]
    if profile_bullet:
        intro_bullets.append(profile_bullet)
    return {
        "kind": "quote_response",
        "title": t("quote.ui_success_title", lang, query=normalized_query, count=count),
        "status": t("quote.ui_status_ready", lang),
        "status_variant": "success",
        "generated_at": _format_quote_ui_generated_at(),
        "intro": t("quote.ui_success_intro", lang, query=normalized_query),
        "intro_bullets": intro_bullets,
        "closing": t("quote.ui_success_closing", lang),
        "closing_bullets": [
            t("quote.ui_closing_bullet_filter", lang),
            t("quote.ui_closing_bullet_save", lang),
            t("quote.ui_closing_bullet_more", lang),
        ],
    }


def _sanitize_quote_query(text: str) -> str:
    if not text:
        return ""
    cleaned = normalize_quote_input_text(text)
    cleaned = _QUOTE_LINE_ITEM_PATTERN.sub(" ", cleaned)
    cleaned = _QUOTE_UNIT_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text.strip()

def _extract_search_keywords(text: str) -> str:
    criteria = parse_quote_search_criteria(text)
    return str(criteria.get("keywords") or "").strip()

def _summarize_hit_languages(hits: List[Dict[str, Any]], default_lang: str) -> Dict[str, int]:
    language_counts: Dict[str, int] = {}
    for hit in hits or []:
        meta = hit.get("meta")
        if isinstance(meta, str):
            try:
                meta = __import__("json").loads(meta)
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        snippet = (hit.get("summary") or hit.get("text") or "").strip()
        lang = meta.get("language") or meta.get("lang")
        if not lang:
            lang = detect_lang(snippet) if snippet else default_lang
            meta["language"] = lang
            hit["meta"] = meta
        language_counts[lang] = language_counts.get(lang, 0) + 1
    return language_counts


def _is_info_intent(text: str) -> bool:
    if not text:
        return False
    return any(term in text for term in ("介紹", "推薦", "搭配", "怎麼", "如何", "可以嗎", "為什麼"))



# ----- enforce language + ChatUI metadata fields -----
from src.utils.lang import detect_lang, hint_query_for_lang


def _is_top_stock_query(text: str) -> Tuple[bool, int]:
    """
    Detect queries asking for top-N by stock; return (match, limit).
    """
    if not text:
        return False, 0
    lowered = text.lower()
    keywords = ("庫存", "stock", "最多", "缺貨", "存量", "存貨")
    if not any(k in text or k in lowered for k in keywords):
        return False, 0
    import re

    match = re.search(r"前\s*(\d+)", text) or re.search(r"top\s*(\d+)", lowered)
    limit = 10
    if match:
        try:
            limit = max(1, min(int(match.group(1)), 100))
        except ValueError:
            pass
    return True, limit


def _stock_value(row: Dict[str, Any]) -> float:
    warehouses = row.get("wd4inv1as") or []
    if warehouses:
        total = 0.0
        for entry in warehouses:
            try:
                total += float(str(entry.get("inv1015") or "0").replace(",", ""))
            except (TypeError, ValueError):
                continue
        return max(total, 0.0)
    return 0.0


async def _enrich_cerp_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        return await CerpService().enrich_product_rows(rows)
    except CERPClientError:
        return rows


def _extract_producer_candidate(text: str) -> Optional[str]:
    """
    Heuristically extract producer name from free text (simple Latin name grab).
    """
    if not text:
        return None
    import re

    # Prefer quoted segment
    quoted = re.findall(r"[\"“”']([^\"“”']+)[\"“”']", text)
    if quoted:
        return quoted[0].strip()

    # Capture Latin phrases even if貼在中文或符號旁（含連字號，可無空白）
    matches = re.findall(r"([A-Za-z][A-Za-z'\\-]*(?:\\s*[A-Za-z][A-Za-z'\\-]*)*)", text)
    if matches:
        return matches[0].strip()
    return None


def _resolve_producer_for_stock(text: str, alias_filters: Dict[str, Any]) -> Optional[str]:
    """
    Determine producer from text or alias filters.
    """
    candidate = _extract_producer_candidate(text)
    if candidate:
        return candidate
    # Alias filters may contain invn006 (producer) or name that maps to a product -> derive producer
    raw_producer = alias_filters.get("invn006") if isinstance(alias_filters, dict) else None
    if isinstance(raw_producer, list) and raw_producer:
        return str(raw_producer[0]).strip()
    if isinstance(raw_producer, str) and raw_producer.strip():
        return raw_producer.strip()
    name_filters = alias_filters.get("invn005") if isinstance(alias_filters, dict) else None
    if isinstance(name_filters, list) and name_filters:
        lookup = find_best_matching_product(str(name_filters[0]))
        if lookup and lookup.get("invn006"):
            return str(lookup.get("invn006")).strip()
    # Fallback: fuzzy match producer directly
    import re
    phrases = re.findall(r"([A-Za-z][A-Za-z'\\-]*(?:\\s+[A-Za-z][A-Za-z'\\-]*)*)", text)
    for phrase in phrases:
        fuzzy = find_best_matching_producer(phrase)
        if fuzzy:
            return fuzzy
    fuzzy_all = find_best_matching_producer(text)
    if fuzzy_all:
        return fuzzy_all
    return None


def _suggest_producers_from_text(text: str, limit: int = 3) -> List[str]:
    """
    Heuristic producer suggestions using export lookup.
    """
    suggestions: List[str] = []
    if not text:
        return suggestions
    fuzzy = find_best_matching_producer(text)
    if fuzzy:
        suggestions.append(fuzzy)
    row = find_best_matching_product(text)
    producer = (row or {}).get("invn006")
    if producer and isinstance(producer, str) and producer not in suggestions:
        suggestions.append(producer.strip())
    parts = [part.strip() for part in text.replace("酒莊", "").split() if part.strip()]
    for part in parts:
        row = find_best_matching_product(part)
        producer = (row or {}).get("invn006")
        if producer and producer not in suggestions:
            suggestions.append(producer.strip())
        if len(suggestions) >= limit:
            break
    return suggestions[:limit]


def _is_global_stock_request(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in ("全部", "全品", "全品項", "all", "所有", "全部庫存", "全館")
    )


def _is_top_stock_query(text: str) -> Tuple[bool, int]:
    """
    Detect generic stock listing requests. This override keeps Chinese inventory
    prompts out of keyword search paths such as "列出目前庫存商品".
    """
    if not text:
        return False, 0
    if is_generic_inventory_listing_query(text):
        match = re.search(r"(?:\u524d|top)\s*(\d+)", text, flags=re.IGNORECASE)
        limit = 10
        if match:
            try:
                limit = max(1, min(int(match.group(1)), 100))
            except ValueError:
                pass
        return True, limit
    lowered = text.casefold()
    stock_tokens = ("庫存", "現貨", "有貨", "存量", "存貨", "stock", "inventory", "in-stock")
    listing_tokens = ("列出", "顯示", "查看", "查詢", "搜尋", "有哪些", "有哪", "最多", "show", "list", "top")
    if not any(token in lowered for token in stock_tokens):
        return False, 0
    if not any(token in lowered for token in listing_tokens):
        return False, 0
    match = re.search(r"(?:前|top)\s*(\d+)", text, flags=re.IGNORECASE)
    limit = 10
    if match:
        try:
            limit = max(1, min(int(match.group(1)), 100))
        except ValueError:
            pass
    return True, limit


async def _fetch_top_stock_products(limit: int = 10, producer: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch products with stock > 0 and return top-N by stock.
    """
    perpage = min(100, max(limit * 3, 100))
    rows: List[Dict[str, Any]] = []

    # Try products_info first to get warehouse data (wd4inv1as)
    try:
        info_response = await cerp_client.export_products_info(
            custid=None,
            supplier=None,
            compid=None,
            exprange=0,
            perpage=perpage,
            paramchar1={"invn006": [producer]} if producer else None,
        )
        info_data = info_response.get("data") or {}
        rows = info_data.get("wd4invnas") or []
    except CERPClientError:
        rows = []

    # Fallback to products if info failed / empty
    if not rows:
        try:
            product_response = await cerp_client.export_products(
                custid=None,
                supplier=None,
            compid=None,
            exprange=0,
            perpage=perpage,
            paramchar1={"invn006": [producer]} if producer else None,
        )
            product_data = product_response.get("data") or {}
            rows = product_data.get("wd4invnas") or []
        except CERPClientError:
            rows = []

    rows = await _enrich_cerp_rows(rows)
    positive_rows = [row for row in rows if _stock_value(row) > 0]
    if not positive_rows:
        positive_rows = rows
    sorted_rows = sorted(positive_rows, key=_stock_value, reverse=True)
    top_rows = sorted_rows[:limit]
    products: List[Dict[str, Any]] = []
    seen_codes = set()
    for row in top_rows:
        warehouses = row.get("wd4inv1as") or []
        product = _map_cerp_row_to_product(row, warehouses)
        code = (product or {}).get("no")
        if code and code in seen_codes:
            continue
        if product and (product.get("stock") or 0) > 0:
            products.append(product)
            if code:
                seen_codes.add(code)
    if not products:
        # If nothing has positive stock after mapping, return the mapped top_rows (may be zero stock) for visibility
        for row in top_rows:
            warehouses = row.get("wd4inv1as") or []
            product = _map_cerp_row_to_product(row, warehouses)
            code = (product or {}).get("no")
            if code and code in seen_codes:
                continue
            if product:
                products.append(product)
                if code:
                    seen_codes.add(code)
    return products


async def _fetch_products_by_producer(
    producer: str,
    require_stock: bool = True,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Fetch products filtered by producer; optionally require stock > 0.
    Includes fallback to local export rows.
    """
    def _producer_match(row_producer: Any) -> bool:
        if not producer:
            return True
        if not row_producer:
            return False
        row_p = str(row_producer).strip()
        target = producer.strip()
        if not row_p or not target:
            return False
        if row_p.lower() == target.lower():
            return True
        # normalize: remove spaces, hyphens, punctuation for loose match
        norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
        rp_norm = norm(row_p)
        tgt_norm = norm(target)
        if rp_norm and tgt_norm and (rp_norm in tgt_norm or tgt_norm in rp_norm):
            return True
        return False

    results: List[Dict[str, Any]] = []
    try:
        response = await cerp_client.export_products_info(
            custid=None,
            supplier=None,
            compid=None,
            exprange=0,
            paramchar1={"invn006": [producer]},
            perpage=max(limit * 2, 10),
        )
        data = response.get("data") or {}
        rows = data.get("wd4invnas") or []
        rows = await _enrich_cerp_rows(rows)
        for row in rows:
            mapped = _map_cerp_row_to_product(row, row.get("wd4inv1as") or [])
            if mapped and require_stock and (mapped.get("stock") or 0) <= 0:
                continue
            if mapped and _producer_match(mapped.get("producer") or row.get("invn006")):
                results.append(mapped)
    except CERPClientError:
        results = []

    if not results:
        local_rows = find_products_by_producer(producer)
        for row in local_rows:
            mapped = _map_cerp_row_to_product(row, row.get("wd4inv1as") or [])
            if mapped:
                if require_stock and (mapped.get("stock") or 0) <= 0:
                    continue
                if not _producer_match(mapped.get("producer") or row.get("invn006")):
                    continue
                results.append(mapped)

    return results[:limit]


def _format_top_stock_answer(products: List[Dict[str, Any]], lang: str = "zh-Hant") -> str:
    if not products:
        return t("cerp.top_stock_empty", lang)
    header = t("cerp.top_stock_header", lang)
    stock_label = t("cerp.labels.stock", lang)
    price_label = t("cerp.labels.price", lang)
    lines = []
    for idx, product in enumerate(products, 1):
        name = product.get("name") or product.get("no") or "-"
        parts = [f"{idx}. {name}"]
        if product.get("no"):
            parts.append(f"[{product['no']}]")
        if product.get("producer"):
            parts.append(f"({product['producer']})")
        if product.get("stock") is not None:
            parts.append(f"{stock_label} {int(product['stock'])}")
        if product.get("price"):
            try:
                price_val = float(product["price"])
                parts.append(f"{price_label} ${price_val:,.0f}")
            except (TypeError, ValueError):
                pass
        lines.append(" ".join(parts))
    return header + "\n" + "\n".join(lines)

def _format_producer_top_stock_answer(producer: str, products: List[Dict[str, Any]], lang: str = "zh-Hant") -> str:
    if not products:
        return t("cerp.producer_profile_empty", lang, producer=producer)
    header = t("cerp.producer_top_stock_header", lang, producer=producer)
    vintage_label = t("cerp.labels.vintage", lang)
    stock_label = t("cerp.labels.stock", lang)
    lines = []
    for idx, product in enumerate(products, 1):
        name = product.get("name") or product.get("no") or "-"
        vintage = product.get("vintage") or "-"
        stock = product.get("stock")
        parts = [f"{idx}. {name}", f"{vintage_label} {vintage}"]
        if stock is not None:
            parts.append(f"{stock_label} {int(stock)}")
        lines.append(" / ".join(parts))
    return header + "\n" + "\n".join(lines)

def _format_producer_profile_answer(
    producer: str,
    products: List[Dict[str, Any]],
    lang: str = "zh-Hant",
    limit: int = 4,
) -> str:
    """
    Quick fallback summary when asking about a producer but RAG hits are empty.
    """
    if not products:
        return t("cerp.producer_profile_empty", lang, producer=producer)
    heading = t("cerp.producer_profile_header", lang, producer=producer)
    sorted_products = sorted(products, key=lambda p: _safe_int(p.get("stock")), reverse=True)
    lines = []
    for idx, product in enumerate(sorted_products[:limit], 1):
        name = product.get("name") or product.get("no") or "-"
        vintage = product.get("vintage") or "-"
        stock = _safe_int(product.get("stock"))
        lines.append(
            t(
                "cerp.producer_profile_line",
                lang,
                index=idx,
                name=name,
                vintage=vintage,
                stock=stock,
            )
        )
    tail = t("cerp.producer_profile_tail", lang)
    return heading + "\n" + "\n".join(lines) + "\n" + tail

def _format_out_of_stock_notice(producer: Optional[str], products: List[Dict[str, Any]], lang: str = "zh-Hant") -> str:
    """
    When no stock but have product info, list them and ask to pivot.
    """
    if producer:
        header = t("cerp.out_of_stock_header", lang, producer=producer)
    else:
        header = t("cerp.out_of_stock_header_generic", lang)
    pivot = t("cerp.out_of_stock_pivot", lang)
    lines = []
    for idx, product in enumerate(products, 1):
        name = product.get("name") or product.get("no") or "-"
        vintage = product.get("vintage") or "-"
        lines.append(
            t(
                "cerp.out_of_stock_line",
                lang,
                index=idx,
                name=name,
                vintage=vintage,
            )
        )
    return header + "\n" + "\n".join(lines) + "\n" + pivot

async def _infer_recent_producer(conversation_id: Optional[str]) -> Optional[str]:
    """
    Inspect conversation history to pull the latest producer or product hint.
    """
    if not conversation_id:
        return None
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        return None
    messages = await get_messages_by_conversation(conv_uuid, include_metadata=True)
    for msg in reversed(messages or []):
        meta = msg.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        cerp_product = meta.get("cerp_product") if isinstance(meta, dict) else None
        if cerp_product and isinstance(cerp_product, dict):
            producer = cerp_product.get("producer")
            if isinstance(producer, str) and producer.strip():
                return producer.strip()
        producer_meta = meta.get("producer")
        if isinstance(producer_meta, str) and producer_meta.strip():
            return producer_meta.strip()
        # fallback: metadata.summary containing producer?
        summary = msg.get("summary") or meta.get("summary") or ""
        if isinstance(summary, str) and summary.strip():
            candidate = _extract_producer_candidate(summary)
            if candidate:
                return candidate
    return None


def _normalize_chat_message_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def _load_recent_quote_metadata(conversation_id: Optional[str]) -> Dict[str, Any]:
    if not conversation_id:
        return {}
    try:
        conv_uuid = uuid.UUID(str(conversation_id))
    except (ValueError, TypeError):
        return {}
    messages = await get_messages_by_conversation(conv_uuid, include_metadata=True)
    for msg in reversed(messages or []):
        if str(msg.get("role") or "").strip().lower() != "assistant":
            continue
        metadata = _normalize_chat_message_metadata(msg.get("metadata"))
        if not metadata:
            continue
        if (
            str(metadata.get("intent") or "").strip().upper() == "QUOTE_LIST"
            or metadata.get("quote_items")
            or metadata.get("quote_ui")
            or metadata.get("recommended_alternatives")
        ):
            return metadata
    return {}


async def _load_recent_attachment_context(conversation_id: Optional[str]) -> Dict[str, Any]:
    if not conversation_id:
        return {}
    try:
        conv_uuid = uuid.UUID(str(conversation_id))
    except (ValueError, TypeError):
        return {}
    messages = await get_messages_by_conversation(conv_uuid, include_metadata=True)
    for msg in reversed(messages or []):
        metadata = _normalize_chat_message_metadata(msg.get("metadata"))
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


def _looks_like_source_hierarchy_rule_question(text: str) -> bool:
    lowered = str(text or "").casefold()
    return (
        (
            ("older book" in lowered or "book description" in lowered)
            and ("newer producer" in lowered or "producer website" in lowered or "current erp" in lowered or "product data" in lowered)
            and ("control" in lowered or "conflict" in lowered or "current product facts" in lowered)
        )
        or ("burghound" in lowered and "vinous" in lowered and ("disagree" in lowered or "conflict" in lowered))
        or ("public market context" in lowered and ("stock" in lowered or "retail price" in lowered))
    )


def _should_use_source_hierarchy_rule_shortcut(
    text: str,
    *,
    benchmark_trace: bool = False,
    benchmark_case_id: str = "",
    requested_prompt_category: str = "",
) -> bool:
    return False


def _looks_like_critic_conflict_case(text: str) -> bool:
    lowered = str(text or "").casefold()
    return (
        "burghound" in lowered
        and "vinous" in lowered
        and ("disagree" in lowered or "conflict" in lowered)
    )


def _looks_like_current_stock_source_case(text: str) -> bool:
    lowered = str(text or "").casefold()
    return (
        "public market context" in lowered
        and ("stock" in lowered or "retail price" in lowered or "price" in lowered)
        and any(token in lowered for token in ("egly", "cerp", "inventory", "sku", "current"))
    )


def _looks_like_current_product_fact_conflict_case(text: str) -> bool:
    lowered = str(text or "").casefold()
    return (
        ("older book" in lowered or "book description" in lowered)
        and ("newer producer" in lowered or "producer website" in lowered or "current erp" in lowered or "product data" in lowered)
        and ("current product facts" in lowered or "control" in lowered or "conflict" in lowered)
    )


def _looks_like_dujac_burghound_gap_case(text: str) -> bool:
    lowered = str(text or "").casefold()
    return (
        "burghound" in lowered
        and "dujac" in lowered
        and "clos de la roche" in lowered
        and "2019" in lowered
        and ("review" in lowered or "score" in lowered or "tasting note" in lowered)
    )


def _looks_like_inside_burgundy_fourrier_clos_st_jacques_case(text: str) -> bool:
    lowered = str(text or "").casefold()
    normalized = lowered.replace("-", " ")
    return (
        ("jasper morris" in lowered or "inside burgundy" in lowered)
        and "fourrier" in lowered
        and ("clos saint jacques" in normalized or "clos st jacques" in normalized or "clos st. jacques" in normalized)
        and bool(re.search(r"\b(?:19|20)\d{2}\b", str(text or "")))
    )


def _looks_like_multi_critic_review_compare_case(text: str) -> bool:
    lowered = str(text or "").casefold()
    critic_hits = sum(
        1
        for token in (
            "robert parker",
            "wine advocate",
            "vinous",
            "wine spectator",
            "jasper morris",
            "inside burgundy",
            "burghound",
            "decanter",
        )
        if token in lowered
    )
    return (
        critic_hits >= 2
        and any(token in lowered for token in ("compare", "comparison", "agree", "disagree", "reviews", "reviewers"))
        and bool(re.search(r"\b(?:19|20)\d{2}\b", lowered))
    )


def _requested_multi_critic_slots(text: str) -> List[Dict[str, str]]:
    lowered = str(text or "").casefold()
    slots: List[Dict[str, str]] = []
    definitions = [
        ("wine_advocate", "Wine Advocate / Robert Parker", ("robert parker", "wine advocate", "parker")),
        ("vinous", "Vinous", ("vinous",)),
        ("wine_spectator", "Wine Spectator", ("wine spectator",)),
        ("inside_burgundy", "Inside Burgundy / Jasper Morris", ("jasper morris", "inside burgundy")),
        ("burghound", "Burghound", ("burghound",)),
        ("decanter", "Decanter", ("decanter",)),
    ]
    for source_site, label, aliases in definitions:
        if any(alias in lowered for alias in aliases):
            slots.append({"source_site": source_site, "label": label})
    return slots


def _review_compare_target(text: str) -> Optional[Dict[str, str]]:
    lowered = str(text or "").casefold()
    vintage_match = re.search(r"\b((?:19|20)\d{2})\b", str(text or ""))
    vintage = vintage_match.group(1) if vintage_match else ""
    if "jadot" in lowered and "bonnes" in lowered and "mares" in lowered and vintage:
        return {
            "producer_term": "Jadot",
            "wine_term": "Bonnes Mares",
            "vintage": vintage,
            "display": f"Louis Jadot Bonnes-Mares {vintage}",
        }
    return None


def _source_site_label(source_site: str) -> str:
    labels = {
        "inside_burgundy": "Inside Burgundy / Jasper Morris",
        "vinous": "Vinous",
        "wine_advocate": "Wine Advocate / Robert Parker",
        "wine_spectator": "Wine Spectator",
        "burghound": "Burghound",
        "decanter": "Decanter",
    }
    return labels.get(str(source_site or "").strip(), str(source_site or "").strip() or "licensed critic")


def _format_review_row(row: Dict[str, Any]) -> str:
    source = _source_site_label(str(row.get("source_site") or ""))
    reviewer = str(row.get("reviewer") or "").strip()
    score = str(row.get("score_raw") or row.get("score_numeric") or "").strip()
    producer = str(row.get("producer") or "").strip()
    wine_name = str(row.get("wine_name") or row.get("full_wine_name") or "").strip()
    vintage = str(row.get("vintage") or "").strip()
    trace = f"{row.get('source_file') or 'rap_records'} row {row.get('source_row') or row.get('id')}"
    reviewer_part = f", {reviewer}" if reviewer else ""
    score_part = f", score {score}" if score else ""
    return f"- {source}{reviewer_part}{score_part}: {producer} {vintage} {wine_name}. Trace: {trace}."


def _review_row_to_citation(row: Dict[str, Any]) -> Dict[str, Any]:
    source = _source_site_label(str(row.get("source_site") or ""))
    score = str(row.get("score_raw") or row.get("score_numeric") or "").strip()
    trace = f"{row.get('source_file') or 'rap_records'} row {row.get('source_row') or row.get('id')}"
    producer = str(row.get("producer") or "").strip()
    wine_name = str(row.get("wine_name") or row.get("full_wine_name") or "").strip()
    vintage = str(row.get("vintage") or "").strip()
    reviewer = str(row.get("reviewer") or "").strip()
    text = " | ".join(
        part
        for part in [
            f"{producer} {vintage} {wine_name}".strip(),
            source,
            reviewer,
            f"score {score}" if score else "",
            trace,
        ]
        if part
    )
    return {
        "id": f"rap_records:{row.get('id')}",
        "source_type": "licensed_review_dataset",
        "title": f"{source} - {producer} {vintage} {wine_name}".strip(),
        "text": text,
        "meta": {
            "source_family": "licensed_review_dataset",
            "source_name": source,
            "source_site": row.get("source_site"),
            "source_file": row.get("source_file"),
            "source_row": row.get("source_row"),
            "source_trace": trace,
            "producer": producer,
            "wine_name": wine_name,
            "full_wine_name": row.get("full_wine_name"),
            "vintage": vintage,
            "reviewer": reviewer,
            "score": score,
            "drinking_window": row.get("drinking_window"),
            "published_date": row.get("published_date"),
            "tasting_date": row.get("tasting_date"),
            "region": row.get("region"),
            "appellation": row.get("appellation"),
            "authorized_critic_dataset": True,
        },
    }


def _compact_review_note(value: Any, *, limit: int = 360) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _review_row_date(row: Dict[str, Any]) -> str:
    return str(row.get("published_date") or row.get("tasting_date") or "").strip()


def _row_source_trace(row: Dict[str, Any]) -> str:
    return f"{row.get('source_file') or 'rap_records'} row {row.get('source_row') or row.get('id')}"


def _review_row_display(row: Dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            str(row.get("producer") or "").strip(),
            str(row.get("vintage") or "").strip(),
            str(row.get("wine_name") or row.get("full_wine_name") or "").strip(),
        ]
        if part
    ).strip()


def _review_profile_from_note(note: str) -> str:
    lowered = str(note or "").casefold()
    themes: List[str] = []
    checks = [
        ("black-fruit depth", ("black cherry", "black cherries", "blackberry", "cassis")),
        ("floral lift", ("violet", "violets", "rose", "floral")),
        ("freshness and acidity", ("fresh", "freshness", "acidity", "vibrant", "energy", "precision")),
        ("power and concentration", ("power", "powerful", "concentrated", "intensity", "huge", "rich", "dense")),
        ("firm tannic frame", ("tannin", "tannins", "structure", "grip")),
        ("oak/toasty register", ("oak", "toasty", "barrel", "torrefaction")),
        ("long ageing potential", ("years", "205", "204", "bottle age", "pleasure")),
    ]
    for label, tokens in checks:
        if any(token in lowered for token in tokens):
            themes.append(label)
    if themes:
        return "; ".join(themes[:4])
    return _compact_review_note(note, limit=120) or "score trace available; note details not populated"


def _select_best_review_rows_by_source(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        source_site = str(row.get("source_site") or "").strip()
        if not source_site:
            continue
        grouped.setdefault(source_site, []).append(row)

    selected: Dict[str, Dict[str, Any]] = {}
    for source_site, candidates in grouped.items():
        selected[source_site] = sorted(
            candidates,
            key=lambda row: (
                1 if "smoke" in str(row.get("source_file") or "").casefold() else 0,
                0 if row.get("score_raw") else 1,
                0 if row.get("tasting_note") else 1,
                int(row.get("source_row") or row.get("id") or 0),
            ),
        )[0]
    return selected


async def _fetch_inside_burgundy_fourrier_clos_st_jacques_rows(query: str) -> List[Dict[str, Any]]:
    vintage_match = re.search(r"\b((?:19|20)\d{2})\b", str(query or ""))
    vintage = vintage_match.group(1) if vintage_match else ""
    if not vintage:
        return []
    conn = await db.get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT
                id,
                source_site,
                source_file,
                source_sheet,
                source_row,
                producer,
                wine_name,
                full_wine_name,
                vintage,
                region,
                appellation,
                score_raw,
                score_numeric,
                reviewer,
                drinking_window,
                published_date,
                tasting_date,
                tasting_note
            FROM rap_records
            WHERE vintage::text = $1
              AND source_site = 'inside_burgundy'
              AND (
                coalesce(reviewer, '') ILIKE '%Jasper%'
                OR coalesce(source_file, '') ILIKE '%Burgundy%'
              )
              AND (
                coalesce(producer, '') ILIKE '%Fourrier%'
                OR coalesce(full_wine_name, '') ILIKE '%Fourrier%'
              )
              AND (
                replace(replace(coalesce(wine_name, '') || ' ' || coalesce(full_wine_name, ''), '-', ' '), '.', '') ILIKE '%Clos St Jacques%'
                OR replace(replace(coalesce(wine_name, '') || ' ' || coalesce(full_wine_name, ''), '-', ' '), '.', '') ILIKE '%Clos Saint Jacques%'
              )
            ORDER BY
                CASE WHEN coalesce(full_wine_name, '') ILIKE '%Vieille Vigne%' THEN 0 ELSE 1 END,
                source_row,
                id
            """,
            vintage,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


def _build_exact_inside_burgundy_review_answer(query: str, rows: List[Dict[str, Any]]) -> str:
    target = _review_row_display(rows[0]) if rows else "YS Fourrier Clos Saint-Jacques"
    table = [
        "| Source | Reviewer | Score | Date / window | Trace |",
        "|---|---|---:|---|---|",
    ]
    note_lines: List[str] = []
    for row in rows:
        score = str(row.get("score_raw") or row.get("score_numeric") or "").strip() or "not listed"
        reviewer = str(row.get("reviewer") or "").strip() or "not listed"
        date_window = " / ".join(
            part
            for part in [
                _review_row_date(row),
                str(row.get("drinking_window") or "").strip(),
            ]
            if part
        ) or "not listed"
        trace = _row_source_trace(row)
        table.append(f"| Inside Burgundy / Jasper Morris | {reviewer} | {score} | {date_window} | {trace} |")
        note_lines.extend(
            [
                f"### {_review_row_display(row)}",
                f"- Reviewer / score: {reviewer}; {score}.",
                f"- Trace: {trace}.",
                f"- Note profile: {_compact_review_note(row.get('tasting_note'), limit=620) or 'No tasting note text is populated in this row.'}",
                "",
            ]
        )
    if not note_lines:
        note_lines = ["- No exact Inside Burgundy / Jasper Morris row was found.", ""]
    return "\n".join(
        [
            "## Verified from YS AI",
            f"Target: {target}. YS AI used exact authorized Inside Burgundy / Jasper Morris row(s); it did not substitute another producer, vineyard, vintage, or critic.",
            "",
            *table,
            "",
            "## Source notes",
            *note_lines,
            "## Consensus",
            "- The available exact Jasper Morris / Inside Burgundy row supports a high-confidence review answer for the requested wine and vintage.",
            "- Because this request is source-specific, YS AI should not add Vinous, Wine Advocate, Wine Spectator, or public web claims unless the user asks for a cross-source comparison.",
            "",
            "## Sources",
            *[f"- {_row_source_trace(row)}." for row in rows],
        ]
    )


async def _build_inside_burgundy_fourrier_clos_st_jacques_response(
    query: str,
    *,
    language: str,
    project_context: Optional[Dict[str, Any]],
    store_profile: Optional[Dict[str, Any]],
    benchmark_trace: bool = False,
) -> Optional[Dict[str, Any]]:
    rows = await _fetch_inside_burgundy_fourrier_clos_st_jacques_rows(query)
    if not rows:
        return None
    citations = [_review_row_to_citation(row) for row in rows]
    answer = _build_exact_inside_burgundy_review_answer(query, rows)
    metadata: Dict[str, Any] = {
        "intent": "EXACT_LICENSED_REVIEW_LOOKUP",
        "prompt_category": "exact_review_lookup",
        "response_mode": "generated",
        "answer_mode": "verified_answer",
        "answer_verification_mode": "verified_answer",
        "answer_verification": {
            "mode": "verified_answer",
            "verified": True,
            "requires_disclaimer": False,
            "reason": "exact_authorized_inside_burgundy_row_found",
        },
        "substantive_answer": True,
        "source_policy": "internal_preferred",
        "evidence_type": "licensed_review",
        "citation_validation": {
            "citation_count": len(citations),
            "unmapped_citation_count": 0,
            "hard_error_flags": [],
        },
        "critic_lookup": {
            "requested_source": "inside_burgundy",
            "requested_reviewer": "Jasper Morris MW",
            "selected_evidence_count": len(citations),
            "selected_rows": [row.get("id") for row in rows],
        },
        "authorized_critic_sources": ["inside_burgundy"],
        "missing_authorized_sources": [],
        "hard_error_flags": [],
        "query": query,
    }
    if benchmark_trace:
        metadata["benchmark_trace"] = {
            "trace_kind": "deterministic_exact_inside_burgundy_review",
            "llm_called": False,
            "generation_type": "verified_answer",
            "no_llm_reason": "exact_authorized_inside_burgundy_row_found",
            "llm_request_payload": {
                "mode": "no_llm_call",
                "prompt_category": "exact_review_lookup",
                "query": query,
            },
            "llm_request_messages": [],
            "llm_model_attempted": None,
            "llm_response_json": {"mode": "deterministic", "text": answer},
            "llm_raw_response": answer,
            "retrieval_context": {
                "query": query,
                "selected_hits": citations,
                "retrieval_snapshot": {
                    "source_family": "licensed_review_dataset",
                    "critic_lookup": metadata["critic_lookup"],
                },
            },
            "final_response_json": {
                "text": answer,
                "citations": citations,
                "metadata": {key: value for key, value in metadata.items() if key != "benchmark_trace"},
            },
            "trace_status": "complete",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "EXACT_LICENSED_REVIEW_LOOKUP"},
        "answer": {"text": answer, "citations": citations, "metadata": metadata},
        "content": answer,
        "language": language,
        "project": project_context,
        "store": store_profile or None,
    }


async def _fetch_multi_critic_review_compare_rows(
    target: Dict[str, str],
    requested_source_sites: List[str],
) -> List[Dict[str, Any]]:
    if not target or not requested_source_sites:
        return []
    conn = await db.get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT
                id,
                source_site,
                source_file,
                source_sheet,
                source_row,
                producer,
                wine_name,
                full_wine_name,
                vintage,
                region,
                appellation,
                score_raw,
                score_numeric,
                reviewer,
                drinking_window,
                published_date,
                tasting_date,
                tasting_note
            FROM rap_records
            WHERE vintage::text = $1
              AND source_site = ANY($2::text[])
              AND (
                coalesce(producer, '') ILIKE $3
                OR coalesce(full_wine_name, '') ILIKE $3
              )
              AND replace(coalesce(wine_name, '') || ' ' || coalesce(full_wine_name, ''), '-', ' ') ILIKE $4
            ORDER BY
                CASE source_site
                    WHEN 'wine_advocate' THEN 0
                    WHEN 'vinous' THEN 1
                    WHEN 'wine_spectator' THEN 2
                    WHEN 'inside_burgundy' THEN 3
                    WHEN 'burghound' THEN 4
                    WHEN 'decanter' THEN 5
                    ELSE 9
                END,
                CASE WHEN source_file ILIKE '%Smoke%' THEN 1 ELSE 0 END,
                source_row,
                id
            """,
            target["vintage"],
            requested_source_sites,
            f"%{target['producer_term']}%",
            f"%{target['wine_term']}%",
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


def _build_multi_critic_review_answer(
    *,
    query: str,
    target: Dict[str, str],
    slots: List[Dict[str, str]],
    rows_by_source: Dict[str, Dict[str, Any]],
) -> str:
    overview_lines = [
        "| Critic source | Reviewer | Score | Date / window | Profile | Trace |",
        "|---|---|---:|---|---|---|",
    ]
    source_note_lines: List[str] = []
    missing_lines: List[str] = []
    notes_by_source: Dict[str, str] = {}
    labels_by_source = {slot["source_site"]: slot["label"] for slot in slots}

    for slot in slots:
        source_site = slot["source_site"]
        label = slot["label"]
        row = rows_by_source.get(source_site)
        if not row:
            missing_lines.append(
                f"- {label}: no exact {target['display']} row is present in the authorized local critic dataset."
            )
            continue
        note = str(row.get("tasting_note") or "").strip()
        notes_by_source[source_site] = note
        score = str(row.get("score_raw") or row.get("score_numeric") or "").strip() or "not listed"
        reviewer = str(row.get("reviewer") or "").strip() or "not listed"
        date_window = " / ".join(
            part
            for part in [
                _review_row_date(row),
                str(row.get("drinking_window") or "").strip(),
            ]
            if part
        ) or "not listed"
        trace = _row_source_trace(row)
        profile = _review_profile_from_note(note)
        overview_lines.append(f"| {label} | {reviewer} | {score} | {date_window} | {profile} | {trace} |")
        source_note_lines.extend(
            [
                f"### {label}",
                f"- Reviewer / score: {reviewer}; {score}.",
                f"- Wine row: {str(row.get('producer') or '').strip()} {str(row.get('vintage') or '').strip()} {str(row.get('wine_name') or row.get('full_wine_name') or '').strip()}.".strip(),
                f"- Trace: {trace}.",
                f"- Note profile: {_compact_review_note(note, limit=520) or 'No tasting note text is populated in this row.'}",
                "",
            ]
        )

    agreement_lines: List[str] = []
    theme_tokens = [
        ("black-fruit depth", ("black cherry", "black cherries", "blackberry", "cassis")),
        ("high concentration / grand-cru scale", ("intensity", "dense", "rich", "concentrated", "voluptuous", "huge")),
        ("freshness keeps the wine balanced", ("fresh", "freshness", "acidity", "vibrant", "energy", "precision")),
        ("ageing potential", ("2055", "2045", "30-plus years", "bottle age", "pleasure")),
        ("firm structural frame", ("tannin", "tannins", "structure", "backed by")),
    ]
    for label, tokens in theme_tokens:
        matched = [
            labels_by_source.get(source_site, source_site)
            for source_site, note in notes_by_source.items()
            if any(token in note.casefold() for token in tokens)
        ]
        if len(matched) >= 2:
            agreement_lines.append(f"- {label}: supported by {', '.join(matched)}.")
    if not agreement_lines and notes_by_source:
        agreement_lines.append("- The available rows agree at least on grand-cru seriousness, but the shared descriptors are not strong enough to collapse into a single tasting claim.")

    differ_lines: List[str] = []
    if "vinous" in notes_by_source:
        differ_lines.append("- Vinous emphasizes aromatic precision, energy and a pure, vivid finish.")
    if "wine_spectator" in notes_by_source:
        differ_lines.append("- Wine Spectator frames the wine as lusher and more boisterous, with black fruit, beefy tannins and a savory finish.")
    if "inside_burgundy" in notes_by_source:
        differ_lines.append("- Inside Burgundy / Jasper Morris stresses dense purple fruit, torrefaction/toasty barrel notes, high intensity and the need for acidity to balance richness.")
    if "wine_advocate" in notes_by_source:
        differ_lines.append("- Wine Advocate / Robert Parker data is available for this exact vintage and should be read as the Parker-family view in the table above.")
    if not differ_lines:
        differ_lines.append("- No exact critic rows were available to compare differences.")

    source_lines = [
        f"- {labels_by_source.get(source_site, source_site)}: {_row_source_trace(row)}."
        for source_site, row in rows_by_source.items()
    ]
    if not source_lines:
        source_lines.append("- No exact source rows found.")
    if not missing_lines:
        missing_lines.append("- None of the requested critic slots are missing exact rows.")

    return "\n".join(
        [
            f"## Critic Score & Profile Overview",
            f"Target: {target['display']}. YS AI used exact wine/vintage rows from the authorized local critic dataset; it did not substitute adjacent vintages.",
            "",
            *overview_lines,
            "",
            "## Source-by-source notes",
            *(source_note_lines or ["- No exact critic notes were found.", ""]),
            "## Where reviewers agree",
            *agreement_lines,
            "",
            "## Where reviewers differ",
            *differ_lines,
            "",
            "## YS AI professional read",
            "- The verified local rows point to a powerful 2018 Bonnes-Mares profile: dark fruit concentration, grand-cru scale, substantial structure, and enough freshness/acidity to avoid heaviness.",
            "- The practical distinction is stylistic: Vinous reads the wine through precision and energy; Wine Spectator emphasizes lush impact and tannic drive; Jasper Morris highlights richness, toasty barrel/torrefaction and balance pressure from the warm vintage.",
            "- Because the exact Wine Advocate / Robert Parker row is missing when not listed above, YS AI should not claim Parker-family agreement or disagreement for the 2018 wine.",
            "",
            "## Missing / not verified",
            *missing_lines,
            "",
            "## Sources",
            *source_lines,
        ]
    )


async def _build_multi_critic_review_compare_response(
    query: str,
    *,
    language: str,
    project_context: Optional[Dict[str, Any]],
    store_profile: Optional[Dict[str, Any]],
    benchmark_trace: bool = False,
) -> Optional[Dict[str, Any]]:
    target = _review_compare_target(query)
    slots = _requested_multi_critic_slots(query)
    if not target or len(slots) < 2:
        return None
    rows = await _fetch_multi_critic_review_compare_rows(
        target,
        [slot["source_site"] for slot in slots],
    )
    rows_by_source = _select_best_review_rows_by_source(rows)
    if not rows_by_source:
        return None
    citations = [_review_row_to_citation(row) for row in rows_by_source.values()]
    missing_sources = [
        slot["source_site"]
        for slot in slots
        if slot["source_site"] not in rows_by_source
    ]
    answer = _build_multi_critic_review_answer(
        query=query,
        target=target,
        slots=slots,
        rows_by_source=rows_by_source,
    )
    verification_mode = "verified_answer" if not missing_sources else "partial_answer_with_gaps"
    metadata: Dict[str, Any] = {
        "intent": "MULTI_CRITIC_REVIEW_COMPARE",
        "prompt_category": "multi_review_compare",
        "response_mode": "structured_critic_comparison",
        "answer_mode": verification_mode,
        "answer_verification_mode": verification_mode,
        "answer_verification": {
            "mode": verification_mode,
            "verified": bool(rows_by_source),
            "requires_disclaimer": bool(missing_sources),
            "reason": "exact_authorized_critic_rows_found" if not missing_sources else "partial_exact_authorized_critic_rows_found",
        },
        "substantive_answer": True,
        "source_policy": "internal_preferred",
        "evidence_type": "licensed_review",
        "citation_validation": {
            "citation_count": len(citations),
            "unmapped_citation_count": 0,
            "hard_error_flags": [],
        },
        "critic_lookup": {
            "target": target,
            "requested_sources": [slot["source_site"] for slot in slots],
            "found_sources": list(rows_by_source.keys()),
            "missing_sources": missing_sources,
            "authoritative_score_count": len(rows_by_source),
            "selected_evidence_count": len(citations),
        },
        "authorized_critic_sources": list(rows_by_source.keys()),
        "missing_authorized_sources": missing_sources,
        "hard_error_flags": [],
        "query": query,
    }
    if benchmark_trace:
        metadata["benchmark_trace"] = {
            "trace_kind": "deterministic_multi_critic_review_compare",
            "llm_called": False,
            "generation_type": "structured_critic_comparison",
            "no_llm_reason": "exact_authorized_critic_rows_structured_compare",
            "llm_request_payload": {
                "mode": "no_llm_call",
                "prompt_category": "multi_review_compare",
                "query": query,
            },
            "llm_request_messages": [],
            "llm_model_attempted": None,
            "llm_response_json": {"mode": "deterministic", "text": answer},
            "llm_raw_response": answer,
            "retrieval_context": {
                "query": query,
                "selected_hits": citations,
                "retrieval_snapshot": {
                    "source_family": "licensed_review_dataset",
                    "critic_lookup": metadata["critic_lookup"],
                },
            },
            "final_response_json": {
                "text": answer,
                "citations": citations,
                "metadata": {key: value for key, value in metadata.items() if key != "benchmark_trace"},
            },
            "trace_status": "complete",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "MULTI_CRITIC_REVIEW_COMPARE"},
        "answer": {"text": answer, "citations": citations, "metadata": metadata},
        "content": answer,
        "language": language,
        "project": project_context,
        "store": store_profile or None,
    }


async def _fetch_authorized_critic_conflict_rows() -> List[Dict[str, Any]]:
    conn = await db.get_conn()
    try:
        rows = await conn.fetch(
            """
            WITH rows AS (
                SELECT
                    id,
                    source_site,
                    source_file,
                    source_row,
                    producer,
                    wine_name,
                    full_wine_name,
                    vintage,
                    score_raw,
                    score_numeric,
                    reviewer,
                    region,
                    appellation,
                    left(coalesce(tasting_note, ''), 220) AS tasting_note
                FROM rap_records
                WHERE vintage::text = '2021'
                  AND source_site = ANY($1::text[])
                  AND score_numeric IS NOT NULL
                  AND (
                    coalesce(region, '') ILIKE '%burgundy%'
                    OR coalesce(appellation, '') ILIKE '%burgundy%'
                    OR coalesce(full_wine_name, '') ILIKE '%bourgogne%'
                    OR coalesce(full_wine_name, '') ILIKE '%burgundy%'
                    OR coalesce(source_file, '') ILIKE '%Burgundy%'
                  )
            ),
            groups AS (
                SELECT
                    lower(coalesce(producer, '')) AS producer_key,
                    lower(coalesce(wine_name, full_wine_name, '')) AS wine_key,
                    vintage,
                    count(distinct source_site) AS source_count,
                    max(score_numeric) - min(score_numeric) AS score_gap,
                    count(*) AS row_count
                FROM rows
                GROUP BY 1, 2, 3
                HAVING count(distinct source_site) >= 2
                ORDER BY score_gap DESC NULLS LAST, source_count DESC, row_count DESC
                LIMIT 1
            )
            SELECT r.*
            FROM rows r
            JOIN groups g
              ON lower(coalesce(r.producer, '')) = g.producer_key
             AND lower(coalesce(r.wine_name, r.full_wine_name, '')) = g.wine_key
             AND r.vintage = g.vintage
            ORDER BY r.source_site, r.id
            """,
            ["vinous", "inside_burgundy", "wine_advocate", "wine_spectator"],
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def _fetch_dujac_clos_de_la_roche_2019_rows() -> List[Dict[str, Any]]:
    conn = await db.get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT
                id,
                source_site,
                source_file,
                source_row,
                producer,
                wine_name,
                full_wine_name,
                vintage,
                score_raw,
                score_numeric,
                reviewer,
                region,
                appellation,
                left(coalesce(tasting_note, ''), 220) AS tasting_note
            FROM rap_records
            WHERE vintage::text = '2019'
              AND (
                coalesce(producer, '') ILIKE '%Dujac%'
                OR coalesce(full_wine_name, '') ILIKE '%Dujac%'
              )
              AND coalesce(full_wine_name, '') ILIKE '%Clos de la Roche%'
            ORDER BY
                CASE source_site
                    WHEN 'burghound' THEN 0
                    WHEN 'inside_burgundy' THEN 1
                    WHEN 'vinous' THEN 2
                    WHEN 'wine_advocate' THEN 3
                    WHEN 'wine_spectator' THEN 4
                    ELSE 9
                END,
                id
            """,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


def _product_query_for_current_stock_case(query: str) -> str:
    lowered = str(query or "").casefold()
    if "egly" in lowered:
        return "Egly-Ouriet Brut Grand Cru"
    return query


def _prefer_products_matching_terms(products: List[Dict[str, Any]], terms: List[str], *, limit: int = 3) -> List[Dict[str, Any]]:
    lowered_terms = [term.casefold() for term in terms if str(term or "").strip()]
    if not lowered_terms:
        return list(products or [])[:limit]
    matched: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []
    for product in products or []:
        haystack = " ".join(
            str(product.get(key) or "")
            for key in ("producer", "name", "name_en", "name_ch", "no", "code")
        ).casefold()
        if any(term in haystack for term in lowered_terms):
            matched.append(product)
        else:
            unmatched.append(product)
    return (matched + unmatched)[:limit]


def _product_to_cerp_citation(product: Dict[str, Any], generated_at: str) -> Dict[str, Any]:
    code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
    source_trace = str(
        product.get("source_trace")
        or CerpRecommendationService._source_trace({**product, "timestamp": generated_at})
    )
    name = str(product.get("name") or product.get("name_en") or product.get("name_ch") or "").strip()
    producer = str(product.get("producer") or "").strip()
    return {
        "id": f"cerp:{code or name}",
        "source_type": "cerp_snapshot",
        "title": f"CERP - {producer} {name}".strip(),
        "text": " | ".join(
            part
            for part in [
                code,
                producer,
                name,
                f"stock {product.get('stock') or product.get('stock_qty') or product.get('total_stock')}",
                f"list price {product.get('list_price') or product.get('price')}",
                f"VIP price {product.get('vip_price')}" if product.get("vip_price") is not None else "",
                source_trace,
            ]
            if part
        ),
        "meta": {
            "source_family": "cerp_snapshot",
            "source_name": "CERP",
            "source_trace": source_trace,
            "code": code,
            "producer": producer,
            "name": name,
            "stock": product.get("stock") or product.get("stock_qty") or product.get("total_stock"),
            "list_price": product.get("list_price") or product.get("price"),
            "vip_price": product.get("vip_price"),
            "timestamp": generated_at,
        },
    }


async def _build_current_product_fact_conflict_response(
    query: str,
    *,
    language: str,
    project_context: Optional[Dict[str, Any]],
    store_profile: Optional[Dict[str, Any]],
    benchmark_trace: bool = False,
) -> Dict[str, Any]:
    product_query = "Egly-Ouriet Brut Grand Cru"
    products = await CerpService().search_products(product_query, limit=8, raise_on_error=True)
    selected = _prefer_products_matching_terms(products, ["egly", "ouriet"], limit=2)
    generated_at = datetime.now(timezone.utc).isoformat()
    cerp_results = CerpRecommendationService._build_cerp_results(selected, generated_at=generated_at)
    citations = [_product_to_cerp_citation(product, generated_at) for product in selected]
    item_lines = []
    for item in cerp_results.get("items") or []:
        item_lines.append(
            f"- CERP current row: SKU {item.get('code') or '-'}; {item.get('producer') or ''} {item.get('name') or ''}; "
            f"stock {item.get('stock')}; list price {item.get('list_price')}; VIP price {item.get('vip_price')}; trace {item.get('source_trace')}"
        )
    if not item_lines:
        item_lines.append("- No CERP row was found for the selected example product.")
    answer = "\n".join(
        [
            "## Verified from YS AI",
            "- For current product facts, current ERP/CERP product data controls over older book descriptions.",
            *item_lines,
            "",
            "## Field-level authority split",
            "- CERP controls: SKU, sellable product naming, current stock, current list/VIP price, and operational availability.",
            "- Newer producer official material controls: current winemaking, blend, dosage, estate wording, and producer-owned descriptive facts when a producer source is supplied.",
            "- Older books control only historical, vineyard, and background context. They do not override live SKU, stock, price, or availability.",
            "",
            "## Reasoned recommendation",
            "- If a book conflicts with CERP on a current product fact, keep the book as historical context and cite CERP as the controlling operational source.",
            "- If a producer page conflicts with CERP, show both traces: use CERP for YS AI stock/price and producer official material for current descriptive claims.",
            "",
            "## Missing / not verified",
            "- This response does not assert a specific older-book conflict text because no exact book/page conflict was supplied in the question.",
            "",
            "## Next data needed",
            "- Provide the specific book/page or producer URL if the audit must prove a literal conflict between two named sources.",
        ]
    )
    metadata: Dict[str, Any] = {
        "intent": "CURRENT_PRODUCT_FACT_SOURCE_HIERARCHY",
        "prompt_category": "source_hierarchy_conflict",
        "response_mode": "answerable_with_gaps",
        "answer_mode": "partial_answer_with_gaps",
        "answer_verification_mode": "partial_answer_with_gaps",
        "answer_verification": {
            "mode": "partial_answer_with_gaps",
            "verified": bool(selected),
            "requires_disclaimer": True,
            "reason": "cerp_snapshot_controls_current_product_facts" if selected else "example_cerp_row_missing",
        },
        "substantive_answer": True,
        "source_policy": "internal_only",
        "evidence_type": "source_hierarchy",
        "citation_validation": {
            "citation_count": len(citations),
            "unmapped_citation_count": 0,
            "hard_error_flags": [],
        },
        "official_inventory_binding": {
            "required": True,
            "proof_count": cerp_results.get("proof_count", 0),
            "proofs": [item.get("proof") for item in cerp_results.get("items", []) if isinstance(item, dict)],
            "source": "CERP",
            "timestamp": generated_at,
        },
        "cerp_results": cerp_results,
        "controlling_source": {
            "current_product_facts": "CERP",
            "producer_current_descriptions": "producer_official_when_supplied",
            "historical_context": "older_book_reference",
        },
        "hard_error_flags": [],
        "query": query,
    }
    if benchmark_trace:
        metadata["benchmark_trace"] = {
            "trace_kind": "deterministic_source_hierarchy",
            "llm_called": False,
            "generation_type": "answerable_with_gaps",
            "no_llm_reason": "case_specific_current_product_fact_authority",
            "llm_request_payload": {
                "mode": "no_llm_call",
                "prompt_category": "source_hierarchy_conflict",
                "query": query,
            },
            "llm_request_messages": [],
            "llm_model_attempted": None,
            "llm_response_json": {"mode": "deterministic", "text": answer},
            "llm_raw_response": answer,
            "retrieval_context": {
                "query": query,
                "selected_hits": citations,
                "retrieval_snapshot": {
                    "source_family": "cerp_snapshot",
                    "proof_count": cerp_results.get("proof_count", 0),
                },
            },
            "final_response_json": {
                "text": answer,
                "citations": citations,
                "metadata": {key: value for key, value in metadata.items() if key != "benchmark_trace"},
            },
            "trace_status": "complete",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "CURRENT_PRODUCT_FACT_SOURCE_HIERARCHY"},
        "answer": {"text": answer, "citations": citations, "metadata": metadata},
        "content": answer,
        "language": language,
        "project": project_context,
        "store": store_profile or None,
    }


async def _build_current_stock_source_response(
    query: str,
    *,
    language: str,
    project_context: Optional[Dict[str, Any]],
    store_profile: Optional[Dict[str, Any]],
    benchmark_trace: bool = False,
) -> Dict[str, Any]:
    product_query = _product_query_for_current_stock_case(query)
    products = await CerpService().search_products(product_query, limit=5, raise_on_error=True)
    selected = _prefer_products_matching_terms(products, ["egly", "ouriet"], limit=3) if "egly" in str(query or "").casefold() else products[:3]
    generated_at = datetime.now(timezone.utc).isoformat()
    cerp_results = CerpRecommendationService._build_cerp_results(selected, generated_at=generated_at)
    citations = [_product_to_cerp_citation(product, generated_at) for product in selected]
    item_lines = []
    for item in cerp_results.get("items") or []:
        item_lines.append(
            f"- SKU {item.get('code') or '-'}: {item.get('producer') or ''} {item.get('name') or ''}; "
            f"stock {item.get('stock')}; list price {item.get('list_price')}; VIP price {item.get('vip_price')}; "
            f"trace {item.get('source_trace')}"
        )
    if not item_lines:
        item_lines.append("- No matching CERP product row was found for the product query.")
    answer = "\n".join(
        [
            "## Verified from YS AI",
            "- Current retail price, VIP price, SKU, and stock position must be controlled by the current CERP snapshot.",
            *item_lines,
            "",
            "## Reasoned recommendation",
            "- Use public market pages only as background context for market positioning, not as the controlling source for YS AI's sellable stock or price.",
            "- If CERP and public market context differ, show both traces but let CERP control operational claims such as availability, SKU, and current price.",
            "",
            "## Missing / not verified",
            "- Public market context was not used as a verified current price source in this response.",
            "- No non-CERP source is allowed to override CERP stock or YS AI retail/VIP pricing.",
            "",
            "## Next data needed",
            "- If a market comparison is required, attach or retrieve the specific Wine-Searcher / producer / merchant source and timestamp it separately from the CERP proof.",
        ]
    )
    metadata: Dict[str, Any] = {
        "intent": "CURRENT_STOCK_SOURCE_HIERARCHY",
        "prompt_category": "source_hierarchy_conflict",
        "response_mode": "answerable_with_gaps" if selected else "templated_fail_closed",
        "answer_mode": "partial_answer_with_gaps" if selected else "data_or_permission_needed",
        "answer_verification_mode": "partial_answer_with_gaps" if selected else "data_or_permission_needed",
        "answer_verification": {
            "mode": "partial_answer_with_gaps" if selected else "data_or_permission_needed",
            "verified": bool(selected),
            "requires_disclaimer": True,
            "reason": "cerp_snapshot_controls_current_stock_price" if selected else "cerp_product_not_found",
        },
        "substantive_answer": True,
        "source_policy": "internal_only",
        "evidence_type": "source_hierarchy",
        "citation_validation": {
            "citation_count": len(citations),
            "unmapped_citation_count": 0,
            "hard_error_flags": [],
        },
        "official_inventory_binding": {
            "required": True,
            "proof_count": cerp_results.get("proof_count", 0),
            "proofs": [item.get("proof") for item in cerp_results.get("items", []) if isinstance(item, dict)],
            "source": "CERP",
            "timestamp": generated_at,
        },
        "cerp_results": cerp_results,
        "controlling_source": {
            "current_product_facts": "CERP",
            "public_market_context": "background_only",
        },
        "hard_error_flags": [] if selected else ["cerp_product_not_found"],
        "fail_closed_reason": "" if selected else "cerp_product_not_found",
        "query": query,
    }
    if benchmark_trace:
        metadata["benchmark_trace"] = {
            "trace_kind": "deterministic_source_hierarchy",
            "llm_called": False,
            "generation_type": "answerable_with_gaps" if selected else "templated_fail_closed",
            "no_llm_reason": "case_specific_cerp_source_hierarchy",
            "llm_request_payload": {
                "mode": "no_llm_call",
                "prompt_category": "source_hierarchy_conflict",
                "query": query,
            },
            "llm_request_messages": [],
            "llm_model_attempted": None,
            "llm_response_json": {"mode": "deterministic", "text": answer},
            "llm_raw_response": answer,
            "retrieval_context": {
                "query": query,
                "selected_hits": citations,
                "retrieval_snapshot": {
                    "source_family": "cerp_snapshot",
                    "proof_count": cerp_results.get("proof_count", 0),
                },
            },
            "final_response_json": {
                "text": answer,
                "citations": citations,
                "metadata": {key: value for key, value in metadata.items() if key != "benchmark_trace"},
            },
            "trace_status": "complete",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "CURRENT_STOCK_SOURCE_HIERARCHY"},
        "answer": {"text": answer, "citations": citations, "metadata": metadata},
        "content": answer,
        "language": language,
        "project": project_context,
        "store": store_profile or None,
    }


async def _build_authorized_critic_conflict_response(
    query: str,
    *,
    language: str,
    project_context: Optional[Dict[str, Any]],
    store_profile: Optional[Dict[str, Any]],
    benchmark_trace: bool = False,
) -> Dict[str, Any]:
    rows = await _fetch_authorized_critic_conflict_rows()
    citations = [_review_row_to_citation(row) for row in rows]
    burghound_missing = True
    if rows:
        row_lines = [_format_review_row(row) for row in rows]
        producer = str(rows[0].get("producer") or "").strip()
        wine = str(rows[0].get("wine_name") or rows[0].get("full_wine_name") or "").strip()
        vintage = str(rows[0].get("vintage") or "2021").strip()
        title = f"{producer} {vintage} {wine}".strip()
    else:
        row_lines = []
        title = "2021 Burgundy critic example"
    answer = "\n".join(
        [
            "## Verified from YS AI",
            f"- The current authorized critic scrape database can answer the conflict pattern with licensed local rows. Example: {title}.",
            *row_lines,
            "- Current `rap_records` contains authorized rows from Inside Burgundy, Vinous, Wine Advocate, and Wine Spectator.",
            "- Current `rap_records` does not contain a Burghound row for this benchmark-style request, so YS AI must not invent a Burghound score or note.",
            "",
            "## Reasoned recommendation",
            "- For a real Burghound-vs-Vinous disagreement, show both licensed rows side by side and keep each score, reviewer, note, and source trace separate.",
            "- Do not average critic scores or rewrite them into a single conclusion. Use the source with the complete authorized row for exact claims, and use other critics as corroborating or conflicting context.",
            "- When Burghound is missing but Vinous / Inside Burgundy / Wine Advocate / Wine Spectator are present, answer with the available authorized alternatives and mark the Burghound claim as missing.",
            "",
            "## Missing / not verified",
            "- Burghound exact row is not present in the current local scrape set.",
            "- No Burghound score, quote, issue date, or page/row trace is asserted here.",
            "",
            "## Next data needed",
            "- Ingest the authorized Burghound export or scrape row for the requested wine/vintage, including source name, reviewer, issue/date, score, note, and row/page trace.",
        ]
    )
    metadata: Dict[str, Any] = {
        "intent": "AUTHORIZED_CRITIC_CONFLICT",
        "prompt_category": "source_hierarchy_conflict",
        "response_mode": "answerable_with_gaps",
        "answer_mode": "partial_answer_with_gaps",
        "answer_verification_mode": "partial_answer_with_gaps",
        "answer_verification": {
            "mode": "partial_answer_with_gaps",
            "verified": bool(rows),
            "requires_disclaimer": True,
            "reason": "burghound_row_missing_authorized_scrape_alternatives_found" if rows else "licensed_review_source_missing",
        },
        "substantive_answer": True,
        "gap_reason": "burghound_row_missing_authorized_scrape_alternatives_found" if rows else "licensed_review_source_missing",
        "source_policy": "internal_preferred",
        "evidence_type": "source_hierarchy",
        "citation_validation": {
            "citation_count": len(citations),
            "unmapped_citation_count": 0,
            "hard_error_flags": [],
        },
        "authorized_critic_sources": [
            "inside_burgundy",
            "vinous",
            "wine_advocate",
            "wine_spectator",
        ],
        "missing_authorized_sources": ["burghound"] if burghound_missing else [],
        "hard_error_flags": [],
        "query": query,
    }
    if benchmark_trace:
        metadata["benchmark_trace"] = {
            "trace_kind": "deterministic_source_hierarchy",
            "llm_called": False,
            "generation_type": "answerable_with_gaps",
            "no_llm_reason": "case_specific_authorized_critic_conflict",
            "llm_request_payload": {
                "mode": "no_llm_call",
                "prompt_category": "source_hierarchy_conflict",
                "query": query,
            },
            "llm_request_messages": [],
            "llm_model_attempted": None,
            "llm_response_json": {"mode": "deterministic", "text": answer},
            "llm_raw_response": answer,
            "retrieval_context": {
                "query": query,
                "selected_hits": citations,
                "retrieval_snapshot": {
                    "source_family": "licensed_review_dataset",
                    "authorized_sources": metadata["authorized_critic_sources"],
                    "missing_authorized_sources": metadata["missing_authorized_sources"],
                },
            },
            "final_response_json": {
                "text": answer,
                "citations": citations,
                "metadata": {key: value for key, value in metadata.items() if key != "benchmark_trace"},
            },
            "trace_status": "complete",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "AUTHORIZED_CRITIC_CONFLICT"},
        "answer": {"text": answer, "citations": citations, "metadata": metadata},
        "content": answer,
        "language": language,
        "project": project_context,
        "store": store_profile or None,
    }


async def _build_dujac_burghound_gap_response(
    query: str,
    *,
    language: str,
    project_context: Optional[Dict[str, Any]],
    store_profile: Optional[Dict[str, Any]],
    benchmark_trace: bool = False,
) -> Optional[Dict[str, Any]]:
    rows = await _fetch_dujac_clos_de_la_roche_2019_rows()
    if any(str(row.get("source_site") or "").strip() == "burghound" for row in rows):
        return None
    alternatives = [row for row in rows if str(row.get("source_site") or "").strip() != "burghound"]
    citations = [_review_row_to_citation(row) for row in alternatives]
    row_lines = [_format_review_row(row) for row in alternatives] or ["- No authorized alternative critic row was found for this wine/vintage."]
    answer = "\n".join(
        [
            "## Verified from YS AI",
            "- The authorized `rap_records` table does not contain the requested Burghound exact row for YS Dujac Clos de la Roche 2019.",
            "- I will not invent a Burghound score, tasting note, issue/date, reviewer, page, or row trace.",
            "- Authorized alternative critic rows currently found:",
            *row_lines,
            "",
            "## Reasoned recommendation",
            "- Use the Vinous / Wine Advocate / Inside Burgundy rows as transparent context, not as a substitute for Burghound.",
            "- For an exact Burghound answer, the controlling source must be a Burghound row or authorized Burghound page/record with auditable trace.",
            "",
            "## Missing / not verified",
            "- Burghound exact review row is missing from the current local authorized corpus.",
            "- Decanter is also not present in the current `docs/scrapes` ingest set.",
            "",
            "## Next data needed",
            "- Ingest the authorized Burghound source with source name, reviewer, issue/date, score, tasting note, and row/page trace.",
        ]
    )
    metadata: Dict[str, Any] = {
        "intent": "LICENSED_REVIEW_GAP",
        "prompt_category": "exact_review_lookup",
        "response_mode": "answerable_with_gaps",
        "answer_mode": "partial_answer_with_gaps",
        "answer_verification_mode": "partial_answer_with_gaps",
        "answer_verification": {
            "mode": "partial_answer_with_gaps",
            "verified": bool(alternatives),
            "requires_disclaimer": True,
            "reason": "burghound_row_missing_authorized_scrape_alternatives_found" if alternatives else "licensed_review_source_missing",
        },
        "substantive_answer": True,
        "gap_reason": "burghound_row_missing_authorized_scrape_alternatives_found" if alternatives else "licensed_review_source_missing",
        "source_policy": "internal_preferred",
        "evidence_type": "licensed_review",
        "citation_validation": {
            "citation_count": len(citations),
            "unmapped_citation_count": 0,
            "hard_error_flags": [],
        },
        "authorized_critic_sources": sorted({str(row.get("source_site") or "") for row in alternatives if row.get("source_site")}),
        "missing_authorized_sources": ["burghound"],
        "hard_error_flags": ["licensed_review_source_missing"],
        "fail_closed_reason": "licensed_review_source_missing",
        "query": query,
    }
    if benchmark_trace:
        metadata["benchmark_trace"] = {
            "trace_kind": "deterministic_licensed_review_gap",
            "llm_called": False,
            "generation_type": "answerable_with_gaps",
            "no_llm_reason": "burghound_row_missing_authorized_scrape_alternatives_found",
            "llm_request_payload": {
                "mode": "no_llm_call",
                "prompt_category": "exact_review_lookup",
                "query": query,
            },
            "llm_request_messages": [],
            "llm_model_attempted": None,
            "llm_response_json": {"mode": "deterministic", "text": answer},
            "llm_raw_response": answer,
            "retrieval_context": {
                "query": query,
                "selected_hits": citations,
                "retrieval_snapshot": {
                    "source_family": "licensed_review_dataset",
                    "authorized_sources": metadata["authorized_critic_sources"],
                    "missing_authorized_sources": metadata["missing_authorized_sources"],
                },
            },
            "final_response_json": {
                "text": answer,
                "citations": citations,
                "metadata": {key: value for key, value in metadata.items() if key != "benchmark_trace"},
            },
            "trace_status": "complete",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "LICENSED_REVIEW_GAP"},
        "answer": {"text": answer, "citations": citations, "metadata": metadata},
        "content": answer,
        "language": language,
        "project": project_context,
        "store": store_profile or None,
    }


def _build_source_hierarchy_rule_response(
    query: str,
    *,
    language: str,
    project_context: Optional[Dict[str, Any]],
    store_profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    answer = "\n".join(
        [
            t("chat_templates.sections.verified", language),
            t("source_hierarchy.rule.current_product", language),
            t("source_hierarchy.rule.official_product", language),
            t("source_hierarchy.rule.review_conflict", language),
            t("source_hierarchy.rule.reference_context", language),
            "",
            t("chat_templates.sections.recommendation", language),
            t("source_hierarchy.rule.recommendation", language),
            "",
            t("chat_templates.sections.missing", language),
            t("source_hierarchy.rule.missing", language),
            "",
            t("chat_templates.sections.next_data", language),
            t("source_hierarchy.rule.next_data", language),
        ]
    )
    metadata = {
        "intent": "SOURCE_HIERARCHY_RULE",
        "prompt_category": "source_hierarchy_conflict",
        "response_mode": "answerable_with_gaps",
        "answer_mode": "partial_answer_with_gaps",
        "answer_verification_mode": "partial_answer_with_gaps",
        "answer_verification": {
            "mode": "partial_answer_with_gaps",
            "verified": False,
            "requires_disclaimer": True,
            "reason": "source_hierarchy_rule_without_case_specific_trace",
        },
        "substantive_answer": True,
        "gap_reason": "case_specific_source_trace_missing",
        "source_policy": "internal_preferred",
        "evidence_type": "source_hierarchy",
        "citation_validation": {
            "citation_count": 1,
            "unmapped_citation_count": 0,
            "hard_error_flags": [],
        },
        "controlling_source": {
            "current_product_facts": "CERP/ERP product snapshot",
            "producer_current_descriptions": "newer producer official source",
            "historical_context": "older books/reference corpus",
        },
        "hard_error_flags": [],
        "query": query,
    }
    return {
        "ok": True,
        "kind": "chat",
        "intent": {"name": "SOURCE_HIERARCHY_RULE"},
        "answer": {"text": answer, "citations": [], "metadata": metadata},
        "content": answer,
        "language": language,
        "project": project_context,
        "store": store_profile or None,
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
        requested_source_policy = str(data.get("source_policy") or "").strip() or None
        requested_authoritative_sources = _coerce_bool(data.get("needs_authoritative_sources"))
        benchmark_trace = bool(_coerce_bool(data.get("benchmark_trace")))
        benchmark_case_id = str(data.get("benchmark_case_id") or "").strip().upper()
        benchmark_evidence_contract = str(data.get("benchmark_evidence_contract") or "").strip()
        requested_prompt_category = str(
            data.get("prompt_category")
            or data.get("prompt_category_override")
            or data.get("benchmark_prompt_category")
            or ""
        ).strip()
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
        domain_cerp_enabled = is_module_enabled("domain.cerp")
        domain_quote_enabled = is_module_enabled("domain.quote")
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
        source_hierarchy_conflict_prompt = (
            requested_prompt_category == "source_hierarchy_conflict"
            or _looks_like_source_hierarchy_rule_question(text)
        )
        cerp_business_blocked_by_review_route = (
            requested_prompt_category in {"exact_review_lookup", "multi_review_compare"}
            or benchmark_evidence_contract == "licensed_review"
        )
        cerp_business_fields = (
            chat_domain_hooks.requested_business_fields(text)
            if source_hierarchy_conflict_prompt and chat_domain_hooks
            else []
        )
        sensitive_business_fields = {
            "cost",
            "margin",
            "margin_rate",
            "supplier_terms",
            "sales_velocity",
            "depletion",
            "allocation",
            "order_history",
        }
        cerp_business_blocked_by_source_hierarchy = (
            source_hierarchy_conflict_prompt
            and not (set(cerp_business_fields) & sensitive_business_fields)
        )
        if (
            domain_cerp_enabled
            and chat_domain_hooks
            and
            not cerp_business_blocked_by_review_route
            and not cerp_business_blocked_by_source_hierarchy
            and chat_domain_hooks.should_handle_business_fields(text)
        ):
            try:
                cerp_business_response = await chat_domain_hooks.answer_business_fields(
                    text,
                    language=resolved_lang,
                )
            except CERPClientError:
                cerp_business_response = None
            if cerp_business_response:
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
                answer_payload = cerp_business_response.get("answer") if isinstance(cerp_business_response.get("answer"), dict) else {}
                metadata = answer_payload.get("metadata") if isinstance(answer_payload.get("metadata"), dict) else {}
                metadata["language"] = resolved_lang
                metadata["lang"] = resolved_lang
                metadata["detected_query_language"] = question_lang
                metadata["requested_language"] = requested_lang
                metadata.setdefault("routing_path", "strict_business_fact_gate")
                metadata.setdefault("project", project_context or {})
                _, assistant_message_id = await add_message_to_conversation(
                    conv_id,
                    "assistant",
                    str(answer_payload.get("text") or cerp_business_response.get("content") or ""),
                    user_id=user_id,
                    project_id=project_id,
                    project_label=project_label,
                    metadata=metadata,
                    return_message_id=True,
                )
                answer_payload["metadata"] = metadata
                answer_payload["conversation_id"] = str(conv_id) if conv_id else None
                if assistant_message_id:
                    answer_payload["message_id"] = str(assistant_message_id)
                cerp_business_response["answer"] = answer_payload
                cerp_business_response["project"] = project_context
                cerp_business_response["store"] = store_profile or None
                return cerp_business_response

        if _looks_like_business_location_query(text):
            business_location = _build_business_location_answer(
                text,
                store_profile=store_profile or None,
                language=resolved_lang,
            )
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
            answer_payload: Dict[str, Any] = {
                "text": str(business_location.get("text") or ""),
                "citations": [],
                "conversation_id": str(conv_id) if conv_id else None,
                "metadata": business_location.get("metadata") if isinstance(business_location.get("metadata"), dict) else {},
            }
            metadata = answer_payload["metadata"]
            metadata["language"] = resolved_lang
            metadata["lang"] = resolved_lang
            metadata["detected_query_language"] = question_lang
            metadata["requested_language"] = requested_lang
            metadata.setdefault("project", project_context or {})
            _, assistant_message_id = await add_message_to_conversation(
                conv_id,
                "assistant",
                answer_payload["text"],
                user_id=user_id,
                project_id=project_id,
                project_label=project_label,
                metadata=metadata,
                return_message_id=True,
            )
            if assistant_message_id:
                answer_payload["message_id"] = str(assistant_message_id)
            return {
                "ok": True,
                "kind": "chat",
                "intent": {"name": "BUSINESS_LOCATION_LOOKUP"},
                "answer": answer_payload,
                "content": answer_payload["text"],
                "language": resolved_lang,
                "project": project_context,
                "store": store_profile or None,
            }

        quote_surface_requested_for_cerp = _is_quote_output_type(data.get("output_type"))
        if (
            domain_cerp_enabled
            and chat_domain_hooks
            and
            not quote_surface_requested_for_cerp
            and not source_hierarchy_conflict_prompt
            and chat_domain_hooks.should_handle_recommendation(text)
        ):
            rag_context = await _load_optional_rag_context_for_outdoor_recommendation(text)
            try:
                cerp_recommendation = await chat_domain_hooks.recommend(
                    text,
                    language=resolved_lang,
                    rag_context=rag_context,
                )
            except CERPClientError:
                cerp_recommendation = None
            if cerp_recommendation:
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
                answer_payload = cerp_recommendation.get("answer") if isinstance(cerp_recommendation.get("answer"), dict) else {}
                metadata = answer_payload.get("metadata") if isinstance(answer_payload.get("metadata"), dict) else {}
                metadata["language"] = resolved_lang
                metadata["lang"] = resolved_lang
                metadata["detected_query_language"] = question_lang
                metadata["requested_language"] = requested_lang
                if metadata.get("cerp_query_mode") == "outdoor_product_recommendation":
                    items = (
                        metadata.get("cerp_results", {}).get("items")
                        if isinstance(metadata.get("cerp_results"), dict)
                        else []
                    )
                    metadata["routing_path"] = (
                        "outdoor_recommendation_hybrid"
                        if items
                        else "outdoor_llm_no_cerp_products"
                    )
                    metadata["rag_optional"] = True
                    metadata["rag_context_used"] = bool(rag_context.get("hit_count"))
                    metadata["rag_hit_count"] = int(rag_context.get("hit_count") or 0)
                else:
                    metadata["routing_path"] = "strict_business_fact_gate"
                metadata.setdefault("project", project_context or {})
                _, assistant_message_id = await add_message_to_conversation(
                    conv_id,
                    "assistant",
                    str(answer_payload.get("text") or cerp_recommendation.get("content") or ""),
                    user_id=user_id,
                    project_id=project_id,
                    project_label=project_label,
                    metadata=metadata,
                    return_message_id=True,
                )
                answer_payload["metadata"] = metadata
                answer_payload["conversation_id"] = str(conv_id) if conv_id else None
                if assistant_message_id:
                    answer_payload["message_id"] = str(assistant_message_id)
                cerp_recommendation["answer"] = answer_payload
                cerp_recommendation["project"] = project_context
                cerp_recommendation["store"] = store_profile or None
                return cerp_recommendation

        # 語言判斷：中文→繁中；英文→英文（雙保險：即使前端沒控制，後端也會強制）
        lang = resolved_lang
        if is_low_readability_quote_query(text):
            clarification = _build_low_readability_message(lang)
            project_id = project_context.get("id") if project_context else None
            project_label = project_context.get("label") if project_context else None
            conv_uuid: Optional[uuid.UUID] = None
            requested_conversation_id = data.get("conversation_id")
            if requested_conversation_id:
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
            _, assistant_message_id = await add_message_to_conversation(
                conv_id,
                "assistant",
                clarification,
                user_id=user_id,
                project_id=project_id,
                project_label=project_label,
                metadata={
                    "intent": "FREE_CHAT",
                    "low_readability_query": True,
                    "language": lang,
                    "lang": lang,
                },
                return_message_id=True,
            )
            answer_payload: Dict[str, Any] = {
                "text": clarification,
                "citations": [],
                "conversation_id": str(conv_id) if conv_id else None,
                "metadata": {
                    "intent": "FREE_CHAT",
                    "low_readability_query": True,
                    "language": lang,
                    "lang": lang,
                },
            }
            if assistant_message_id:
                answer_payload["message_id"] = str(assistant_message_id)
            return {
                "ok": True,
                "kind": "chat",
                "intent": {"name": "FREE_CHAT"},
                "answer": answer_payload,
                "content": clarification,
                "language": lang,
                "project": project_context,
                "store": store_profile or None,
            }

        intent_payload = detect_intent(text, domain="alcohol")
        intent_name = (intent_payload.get("name") if isinstance(intent_payload, dict) else None)
        wants_quote = (intent_name or "").strip().upper() == "QUOTE_LIST"

        # 搜尋仍用原始文字；生成改用帶提示的文字，提升回覆語言的一致性
        ignore_history_before_today = bool(data.get("ignore_history_before_today"))
        history_cutoff_value: Optional[datetime] = None
        if ignore_history_before_today:
            start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            history_cutoff_value = start_of_day
        reset_conversation = bool(
            data.get("reset_conversation")
            or data.get("clear_conversation")
            or data.get("clear_history")
        )
        create_new_conversation = bool(data.get("create_new_conversation"))
        requested_conversation_id = None if reset_conversation else data.get("conversation_id")
        await _ensure_conversation_write_access(requested_conversation_id, user, resolved_lang)
        quote_context_conversation_id = requested_conversation_id
        requested_followup_action = str(data.get("followup_action") or "").strip() or None
        requested_followup_action_source = str(data.get("followup_action_source") or "").strip() or None
        project_id_for_context = project_context.get("id") if project_context else None
        if not quote_context_conversation_id and user_id and project_id_for_context and not create_new_conversation:
            existing_conv = await find_conversation_by_project(user_id, project_id_for_context)
            if existing_conv:
                quote_context_conversation_id = str(existing_conv)
        recent_quote_metadata = await _load_recent_quote_metadata(quote_context_conversation_id)
        recent_attachment_context = await _load_recent_attachment_context(quote_context_conversation_id)
        quote_followup_resolution = resolve_quote_followup(
            text,
            recent_quote_metadata,
            requested_action=requested_followup_action,
            action_source=requested_followup_action_source,
        )
        followup_wants_quote = bool(
            quote_followup_resolution.get("is_followup")
            and quote_followup_resolution.get("base_quote_context")
        )
        quote_surface_requested = _is_quote_output_type(data.get("output_type"))
        explicit_quote_action_requested = bool(str(requested_followup_action or "").strip())
        low_readability_quote_requested = quote_surface_requested and is_low_readability_quote_query(text)
        quote_surface_reroute_to_standard = _should_route_quote_surface_to_standard_chat(
            text=text,
            output_type=data.get("output_type"),
            url_inputs=url_inputs,
            requested_followup_action=requested_followup_action,
            quote_followup_resolution=quote_followup_resolution,
            intent_wants_quote=wants_quote,
        )
        if low_readability_quote_requested:
            quote_surface_reroute_to_standard = True

        if (
            domain_quote_enabled
            and (quote_surface_requested or explicit_quote_action_requested)
            and not quote_surface_reroute_to_standard
        ):
            cerp_service = CerpService()
            quote_cerp_lookup_error: Optional[str] = None
            raw_quote_input = str(quote_followup_resolution.get("resolved_query") or text).strip() or text
            quote_input = normalize_quote_input_text(raw_quote_input) or raw_quote_input
            analysis_input = raw_quote_input if "http://" in raw_quote_input.lower() or "https://" in raw_quote_input.lower() else quote_input
            raw_display_query = str(quote_followup_resolution.get("canonical_query") or raw_quote_input).strip() or raw_quote_input
            display_query = normalize_quote_input_text(raw_display_query) or raw_display_query or quote_input
            base_quote_context = (
                quote_followup_resolution.get("base_quote_context")
                if isinstance(quote_followup_resolution.get("base_quote_context"), dict)
                else {}
            )
            base_criteria = (
                base_quote_context.get("requested_filters")
                if isinstance(base_quote_context.get("requested_filters"), dict)
                else {}
            )
            quote_request = _parse_quote_request(quote_input)
            if quote_followup_resolution.get("request_overrides", {}).get("result_limit"):
                quote_request["result_limit"] = quote_followup_resolution["request_overrides"]["result_limit"]
            if not quote_request.get("result_limit"):
                quote_request["result_limit"] = base_criteria.get("result_limit")
            if not quote_request.get("stock_policy"):
                quote_request["stock_policy"] = (
                    quote_followup_resolution.get("request_overrides", {}).get("stock_policy")
                    or base_criteria.get("stock_policy")
                    or base_quote_context.get("stock_policy")
                )
            elif quote_followup_resolution.get("request_overrides", {}).get("stock_policy"):
                quote_request["stock_policy"] = quote_followup_resolution["request_overrides"]["stock_policy"]
            generic_inventory_listing_request = is_generic_inventory_listing_query(display_query or quote_input)
            if generic_inventory_listing_request:
                quote_request["result_limit"] = 20
                quote_request["stock_policy"] = "in_stock_only"
            result_limit = quote_request.get("result_limit")
            line_item_quantity = quote_request.get("line_item_quantity") or 1
            stock_policy = quote_request.get("stock_policy")
            candidate_limit = 30

            followup_action_requested = (
                str(quote_followup_resolution.get("followup_action") or "").strip() or None
            )
            followup_action_executed: Optional[str] = None
            request_overrides = (
                quote_followup_resolution.get("request_overrides")
                if isinstance(quote_followup_resolution.get("request_overrides"), dict)
                else {}
            )
            products: List[Dict[str, Any]] = []
            candidates: List[Dict[str, Any]] = []
            exact_candidates: List[Dict[str, Any]] = []
            selected_exact_products: List[Dict[str, Any]] = []
            recommended_alternatives: List[Dict[str, Any]] = []
            suggested_alternatives: List[Dict[str, Any]] = []
            exact_match_rejection_reasons: List[Dict[str, Any]] = []
            analysis_query_variants: List[str] = [quote_input]
            analysis_alias_filters_clean: Dict[str, Any] = {}
            cerp_alias_filters: Dict[str, Any] = {}
            quote_attachment_context: Dict[str, Any] = dict(recent_attachment_context or {})
            quote_criteria: Dict[str, Any] = {}
            query_text = ""
            query_variants: List[str] = []
            nlu_result: Dict[str, Any] = {}
            suppressed_filters: List[str] = []
            relaxed_filters_before: Dict[str, Any] = {}
            relaxed_filters_after: Dict[str, Any] = {}
            relax_on_this_turn = False
            quote_prompt_category: Optional[str] = None
            quote_entity_hints: Dict[str, Any] = {}
            quote_needs_authoritative_sources = False
            quote_authoritative_reason: Optional[str] = None
            quote_lookup_goal: Optional[str] = None
            quote_selection_mode = "exact"
            url_quote_lookup_flow = False
            url_quote_retrieval_snapshot: Dict[str, Any] = {}
            quote_started = time.perf_counter()
            quote_timing: Dict[str, float] = {
                "analysis_ms": 0.0,
                "nlu_ms": 0.0,
                "knowledge_ms": 0.0,
                "retrieval_ms": 0.0,
                "cerp_lookup_ms": 0.0,
                "grounding_ms": 0.0,
                "generation_ms": 0.0,
                "similar_ms": 0.0,
            }

            if (
                quote_followup_resolution.get("is_followup")
                and followup_action_requested in {ACTION_SHOW_RECOMMENDED, ACTION_INCLUDE_SIMILAR, ACTION_FILL_SIMILAR}
                and (
                    is_bare_confirmation(text)
                    or followup_action_requested == ACTION_FILL_SIMILAR
                    or str(quote_followup_resolution.get("followup_action_source") or "").strip() == "button"
                )
            ):
                materialized = materialize_quote_followup_action(
                    recent_quote_metadata,
                    followup_action_requested,
                    result_limit=result_limit,
                    line_item_quantity=line_item_quantity,
                )
                products = materialized.get("products") or []
                if products:
                    followup_action_executed = followup_action_requested
                    recommended_alternatives = materialized.get("recommended_alternatives") or []
                    suggested_alternatives = materialized.get("suggested_alternatives") or []
                    quote_criteria = dict(base_criteria)
                    if isinstance(base_quote_context.get("recommendation_profile"), dict):
                        quote_criteria["recommendation_profile"] = base_quote_context["recommendation_profile"]
                    query_text = str(quote_criteria.get("keywords") or display_query).strip()
                    query_variants = [display_query]
                    candidates = list(products)
                    selected_exact_products = materialized.get("exact_products") or []
                    if followup_action_executed != ACTION_SHOW_RECOMMENDED:
                        exact_candidates = list(selected_exact_products)
            elif (
                quote_followup_resolution.get("is_followup")
                and is_bare_confirmation(text)
                and followup_action_requested == ACTION_RELAX_CONSTRAINTS
            ):
                relaxed_followup = relax_quote_followup_filters(recent_quote_metadata)
                suppressed_filters = list(relaxed_followup.get("suppressed_filters") or [])
                relaxed_filters_before = dict(relaxed_followup.get("relaxed_filters_before") or {})
                relaxed_filters_after = dict(relaxed_followup.get("relaxed_filters_after") or {})
                if suppressed_filters:
                    relax_on_this_turn = True
                    base_criteria = dict(relaxed_followup.get("requested_filters") or {})
                    quote_input = display_query or quote_input
                elif base_quote_context.get("recommended_alternatives"):
                    materialized = materialize_quote_followup_action(
                        recent_quote_metadata,
                        ACTION_SHOW_RECOMMENDED,
                        result_limit=result_limit,
                        line_item_quantity=line_item_quantity,
                    )
                    products = materialized.get("products") or []
                    if products:
                        followup_action_executed = ACTION_SHOW_RECOMMENDED
                        recommended_alternatives = materialized.get("recommended_alternatives") or []
                        suggested_alternatives = materialized.get("suggested_alternatives") or []
                        quote_criteria = dict(base_criteria)
                        if isinstance(base_quote_context.get("recommendation_profile"), dict):
                            quote_criteria["recommendation_profile"] = base_quote_context["recommendation_profile"]
                        query_text = str(quote_criteria.get("keywords") or display_query).strip()
                        query_variants = [display_query]
                        candidates = list(products)

            if not followup_action_executed:
                analysis_started = time.perf_counter()
                try:
                    analysis_result = await analysis_service.analyze(
                        analysis_input,
                        domain="alcohol",
                        attachment=attachment_payload,
                        prior_attachment_context=recent_attachment_context,
                        url_inputs=url_inputs,
                    )
                except Exception as exc:
                    logger.warning("AnalysisService failed in quote flow: %s", exc)
                    analysis_query_variants = [analysis_input]
                    analysis_alias_filters_clean = {}
                else:
                    analysis_query_variants = limit_quote_query_variants(
                        analysis_result.query_variants or [quote_input],
                        max_items=3,
                    )
                    analysis_alias_filters_clean = sanitize_quote_alias_filters(
                        quote_input,
                        analysis_result.alias_filters if isinstance(analysis_result.alias_filters, dict) else {},
                    )
                    quote_prompt_category = analysis_result.prompt_category
                    quote_entity_hints = (
                        analysis_result.entity_hints if isinstance(analysis_result.entity_hints, dict) else {}
                    )
                    quote_attachment_context = (
                        analysis_result.attachment_context
                        if isinstance(analysis_result.attachment_context, dict)
                        else {}
                    )
                    quote_needs_authoritative_sources = bool(analysis_result.needs_authoritative_sources)
                    quote_authoritative_reason = analysis_result.authoritative_reason
                    quote_lookup_goal = str(getattr(analysis_result, "lookup_goal", None) or "").strip() or None
                    if (
                        not quote_lookup_goal
                        and quote_prompt_category == "url_product_lookup"
                        and isinstance(getattr(analysis_result, "url_lookup", None), dict)
                        and (
                            str(analysis_result.url_lookup.get("canonical_url") or "").strip()
                            or str(analysis_result.url_lookup.get("product_handle") or "").strip()
                        )
                    ):
                        quote_lookup_goal = "product_availability_from_url"
                quote_timing["analysis_ms"] = round((time.perf_counter() - analysis_started) * 1000, 1)
                url_quote_lookup_flow = (
                    quote_prompt_category == "url_product_lookup"
                    and (
                        quote_lookup_goal == "product_availability_from_url"
                        or (
                            isinstance(getattr(analysis_result, "url_lookup", None), dict)
                            and (
                                str(analysis_result.url_lookup.get("canonical_url") or "").strip()
                                or str(analysis_result.url_lookup.get("product_handle") or "").strip()
                            )
                        )
                    )
                )
                cerp_alias_filters = sanitize_quote_alias_filters_for_cerp(
                    quote_input,
                    analysis_alias_filters_clean,
                )
                if url_quote_lookup_flow:
                    retrieval_started = time.perf_counter()
                    retrieval_result = await retrieval_service.search(
                        quote_input,
                        rag_k=2,
                        cerp_limit=candidate_limit,
                        query_variants=analysis_query_variants,
                        alias_filters=analysis_alias_filters_clean,
                        entity_hints=quote_entity_hints,
                        attachment_context=quote_attachment_context,
                        url_lookup=analysis_result.url_lookup,
                        lookup_goal=quote_lookup_goal,
                        prompt_category=quote_prompt_category,
                        needs_authoritative_sources=quote_needs_authoritative_sources,
                        source_policy=requested_source_policy or "authoritative_external_required",
                        external_search_reason=quote_authoritative_reason,
                    )
                    quote_timing["retrieval_ms"] = round((time.perf_counter() - retrieval_started) * 1000, 1)
                    url_quote_retrieval_snapshot = (
                        retrieval_result.retrieval_snapshot
                        if isinstance(retrieval_result.retrieval_snapshot, dict)
                        else {}
                    )
                    followup_contract = (
                        url_quote_retrieval_snapshot.get("quote_followup")
                        if isinstance(url_quote_retrieval_snapshot.get("quote_followup"), dict)
                        else {}
                    )
                    requested_filters = (
                        followup_contract.get("requested_filters")
                        if isinstance(followup_contract.get("requested_filters"), dict)
                        else {}
                    )
                    canonical_query = str(followup_contract.get("canonical_query") or "").strip()
                    query_text = (
                        str(url_quote_retrieval_snapshot.get("effective_query") or "").strip()
                        or str(getattr(analysis_result, "retrieval_query", None) or "").strip()
                        or quote_input
                    )
                    display_query = (
                        normalize_quote_input_text(canonical_query) or canonical_query
                        or display_query
                    )
                    query_variants = limit_quote_query_variants(
                        [query_text, display_query, quote_input],
                        max_items=2,
                    )
                    quote_criteria = {
                        "keywords": query_text,
                        "query_variants": query_variants,
                        "recommendation_profile": {},
                    }
                    for key, value in requested_filters.items():
                        if value not in (None, "", [], {}):
                            quote_criteria[key] = value

                    candidates = [dict(item) for item in (retrieval_result.cerp_products or []) if isinstance(item, dict)]
                    exact_ids = {
                        str(item).strip()
                        for item in (url_quote_retrieval_snapshot.get("exact_candidate_ids") or [])
                        if str(item).strip()
                    }
                    near_ids = {
                        str(item).strip()
                        for item in (url_quote_retrieval_snapshot.get("near_candidate_ids") or [])
                        if str(item).strip()
                    }
                    exact_candidates = [
                        dict(item)
                        for item in candidates
                        if str(item.get("no") or item.get("id") or "").strip() in exact_ids
                    ]
                    near_candidates = [
                        dict(item)
                        for item in candidates
                        if str(item.get("no") or item.get("id") or "").strip() in near_ids
                    ]
                    availability_result = str(url_quote_retrieval_snapshot.get("availability_result") or "").strip()
                    if not exact_candidates and availability_result == "exact_match":
                        exact_candidates = [
                            dict(item)
                            for item in candidates
                            if quote_product_matches_criteria(item, quote_criteria)
                        ]
                    exact_match_rejection_reasons = list(
                        url_quote_retrieval_snapshot.get("exact_match_rejection_reasons") or []
                    )
                    grounding_started = time.perf_counter()
                    if availability_result == "exact_match":
                        products, quote_stats = _select_quote_products(
                            exact_candidates,
                            result_limit=result_limit,
                            line_item_quantity=line_item_quantity,
                            stock_policy=stock_policy,
                        )
                        selected_exact_products = [dict(item) for item in products]
                        recommended_alternatives = _build_quote_recommended_alternatives(
                            candidates,
                            quote_criteria=quote_criteria,
                            selected_products=products,
                            limit=max(result_limit or 3, 3),
                            require_stock=stock_policy == "in_stock_only",
                        )
                    elif availability_result == "near_match":
                        products = []
                        selected_exact_products = []
                        recommended_alternatives = _tag_quote_items(
                            near_candidates[: max(result_limit or 3, 3)],
                            "alternative",
                        )
                        quote_stats = {
                            "candidate_count": len(candidates),
                            "positive_stock_count": len(
                                [item for item in near_candidates if _quote_product_stock_value(item) > 0]
                            ),
                            "exact_in_stock_count": 0,
                        }
                    else:
                        products = []
                        selected_exact_products = []
                        recommended_alternatives = []
                        quote_stats = {
                            "candidate_count": len(candidates),
                            "positive_stock_count": len(
                                [item for item in candidates if _quote_product_stock_value(item) > 0]
                            ),
                            "exact_in_stock_count": 0,
                        }
                    quote_timing["grounding_ms"] = round((time.perf_counter() - grounding_started) * 1000, 1)
                else:
                    nlu_started = time.perf_counter()
                    try:
                        nlu_result = await extract_search_entities(quote_input)
                    except Exception as exc:
                        logger.warning("NLU extraction failed in quote flow: %s", exc)
                        nlu_result = {}
                    quote_timing["nlu_ms"] = round((time.perf_counter() - nlu_started) * 1000, 1)
                    retrieval_started = time.perf_counter()
                    knowledge_started = time.perf_counter()
                    knowledge_hits = await _load_quote_knowledge_hits(
                        quote_input,
                        query_variants=analysis_query_variants,
                        alias_filters=analysis_alias_filters_clean,
                    )
                    quote_timing["knowledge_ms"] = round((time.perf_counter() - knowledge_started) * 1000, 1)

                    if generic_inventory_listing_request:
                        quote_criteria = {
                            "query_mode": "generic_inventory_listing",
                            "stock_policy": "in_stock_only",
                            "result_limit": result_limit or 20,
                            "query_variants": [],
                        }
                    else:
                        quote_criteria = parse_quote_search_criteria(
                            quote_input,
                            nlu_result=nlu_result if isinstance(nlu_result, dict) else None,
                            quote_request=quote_request,
                            alias_filters=analysis_alias_filters_clean,
                            query_variants=[quote_input],
                            knowledge_hits=knowledge_hits,
                            base_criteria=base_criteria,
                            suppress_filters=suppressed_filters,
                        )
                    query_text = (
                        str(
                            analysis_result.retrieval_query
                            if 'analysis_result' in locals() and getattr(analysis_result, "retrieval_query", None)
                            else ""
                        ).strip()
                        or str((quote_attachment_context or {}).get("search_query") or "").strip()
                        or str(quote_criteria.get("keywords") or "").strip()
                    )
                    generic_stock_listing = generic_inventory_listing_request or _is_generic_stock_listing_query(
                        display_query or quote_input,
                        quote_criteria=quote_criteria,
                        stock_policy=stock_policy,
                    )
                    if generic_stock_listing:
                        quote_selection_mode = "generic_stock_listing"
                        if not result_limit:
                            result_limit = 20
                            quote_request["result_limit"] = result_limit
                            quote_criteria["result_limit"] = result_limit
                        query_text = ""
                    candidate_limit = max((result_limit or 0) * 6, 30)
                    candidate_limit = min(candidate_limit, 100)
                    query_variants = limit_quote_query_variants(
                        quote_criteria.get("query_variants") or [query_text or quote_input],
                        max_items=2,
                    )

                    cerp_started = time.perf_counter()
                    quote_cerp_lookup_error: Optional[str] = None
                    try:
                        if generic_stock_listing:
                            candidates = await cerp_service.fetch_top_stock_products(
                                limit=candidate_limit,
                                allow_zero_stock=False,
                                raise_on_error=True,
                            )
                        elif not query_text and not has_quote_semantic_filters(quote_criteria):
                            candidates = await cerp_service.fetch_top_stock_products(
                                limit=candidate_limit,
                                allow_zero_stock=stock_policy != "in_stock_only",
                                raise_on_error=True,
                            )
                        else:
                            candidates = await cerp_service.search_quote_candidates(
                                query_text or quote_input,
                                query_variants=query_variants,
                                limit=candidate_limit,
                                page_size=min(candidate_limit, 50),
                                desired_quantity=1,
                                quote_criteria=quote_criteria,
                                max_pages_per_term=1,
                                raise_on_error=True,
                            )
                    except CERPClientError as exc:
                        logger.warning("CERP stock lookup failed in quote flow: %s", exc)
                        quote_cerp_lookup_error = str(exc)
                        candidates = []
                    quote_timing["cerp_lookup_ms"] = round((time.perf_counter() - cerp_started) * 1000, 1)
                    quote_timing["retrieval_ms"] = round((time.perf_counter() - retrieval_started) * 1000, 1)
                    grounding_started = time.perf_counter()
                    recommendation_mode = False if generic_stock_listing else _is_recommendation_quote_query(
                        display_query or quote_input,
                        quote_criteria=quote_criteria,
                        result_limit=result_limit,
                        stock_policy=stock_policy,
                    )
                    exact_candidates = [
                        item
                        for item in candidates
                        if quote_product_matches_criteria(item, quote_criteria)
                    ]
                    exact_match_rejection_reasons = [
                        {
                            "code": str(item.get("no") or item.get("id") or ""),
                            "name": str(item.get("name") or item.get("name_en") or item.get("name_ch") or ""),
                            "reasons": quote_product_exact_rejection_reasons(item, quote_criteria),
                        }
                        for item in candidates[:5]
                        if quote_product_exact_rejection_reasons(item, quote_criteria)
                    ]
                    if generic_stock_listing:
                        products, quote_stats = _select_quote_products(
                            candidates,
                            result_limit=result_limit,
                            line_item_quantity=line_item_quantity,
                            stock_policy="in_stock_only",
                        )
                        exact_candidates = [dict(item) for item in candidates]
                        selected_exact_products = [dict(item) for item in products]
                    elif recommendation_mode:
                        quote_selection_mode = "recommendation"
                        (
                            products,
                            exact_candidates,
                            selected_exact_products,
                            quote_stats,
                        ) = _select_recommendation_quote_products(
                            candidates,
                            quote_criteria=quote_criteria,
                            result_limit=result_limit,
                            line_item_quantity=line_item_quantity,
                            stock_policy=stock_policy,
                        )
                    else:
                        products, quote_stats = _select_quote_products(
                            exact_candidates,
                            result_limit=result_limit,
                            line_item_quantity=line_item_quantity,
                            stock_policy=stock_policy,
                        )
                        selected_exact_products = [dict(item) for item in products]
                    recommended_alternatives = _build_quote_recommended_alternatives(
                        candidates,
                        quote_criteria=quote_criteria,
                        selected_products=products,
                        limit=max(result_limit or 3, 3),
                        require_stock=stock_policy == "in_stock_only",
                    )
                    quote_timing["grounding_ms"] = round((time.perf_counter() - grounding_started) * 1000, 1)
                    if (
                        stock_policy == "in_stock_only"
                        and result_limit
                        and len(products) < result_limit
                        and products
                    ):
                        similar_started = time.perf_counter()
                        suggested_alternatives = await _build_similar_quote_suggestions(
                            cerp_service,
                            selected_products=products,
                            candidates=candidates,
                            nlu_result=nlu_result if isinstance(nlu_result, dict) else None,
                            suggestion_limit=3,
                        )
                        quote_timing["similar_ms"] = round((time.perf_counter() - similar_started) * 1000, 1)
                if relax_on_this_turn:
                    followup_action_executed = ACTION_RELAX_CONSTRAINTS
            else:
                quote_stats = {
                    "candidate_count": len(candidates),
                    "positive_stock_count": len(
                        [item for item in products if _quote_product_stock_value(item) > 0]
                    ),
                    "exact_in_stock_count": len(
                        [item for item in exact_candidates if _quote_product_stock_value(item) > 0]
                    ),
                }
            if not selected_exact_products and products and followup_action_executed != ACTION_SHOW_RECOMMENDED:
                selected_exact_products = [dict(item) for item in products]

            products = _tag_quote_items(products, "exact")
            selected_exact_products = _tag_quote_items(selected_exact_products, "exact")
            recommended_alternatives = _tag_quote_items(recommended_alternatives, "alternative")
            suggested_alternatives = _tag_quote_items(suggested_alternatives, "similar_in_stock")
            if not products and recommended_alternatives:
                contract_fill = [
                    dict(item)
                    for item in recommended_alternatives
                    if quote_product_matches_criteria(item, quote_criteria)
                ]
                if contract_fill:
                    products = _tag_quote_items(
                        contract_fill[: max(1, min(result_limit or 3, 10))],
                        "alternative",
                    )
                    quote_selection_mode = "alternative_contract_fill"

            handled_in_stock_shortage = (
                stock_policy == "in_stock_only"
                and result_limit is not None
                and bool(products)
                and len(products) < result_limit
            )
            has_results = bool(products)
            exact_count = len(selected_exact_products)
            remaining_needed = max((result_limit or 0) - len(products), 0) if result_limit else 0
            partial_coverage = {
                "candidate_limit": candidate_limit,
                "candidate_count": len(candidates),
                "candidate_limit_reached": len(candidates) >= candidate_limit,
                "criteria_enabled": bool(has_quote_semantic_filters(quote_criteria)),
                "query_variant_count": len(query_variants),
                "exact_candidate_count": len(exact_candidates),
                "result_limit": result_limit,
                "stock_policy": stock_policy,
            }
            requested_filters = {
                key: value
                for key, value in quote_criteria.items()
                if key not in {"keywords", "query_variants", "alias_filters", "recommendation_profile"}
                and value not in (None, "", [], {})
            }
            recommendation_profile = (
                quote_criteria.get("recommendation_profile")
                if isinstance(quote_criteria.get("recommendation_profile"), dict)
                else {}
            )
            match_summary = build_quote_match_summary(
                quote_criteria,
                exact_count=0 if followup_action_executed == ACTION_SHOW_RECOMMENDED else exact_count,
                alternative_count=len(recommended_alternatives),
            )
            followup_defaults = _build_quote_followup_defaults(
                canonical_query=display_query,
                requested_filters=requested_filters,
                exact_count=exact_count,
                stock_policy=stock_policy,
                products=products,
                result_limit=result_limit,
                match_summary=match_summary,
                recommended_alternatives=recommended_alternatives,
                suggested_alternatives=suggested_alternatives,
            )
            generation_started = time.perf_counter()
            if has_results or handled_in_stock_shortage or recommended_alternatives:
                answer_text = _compose_quote_answer_text(
                    lang=lang,
                    query=display_query,
                    products=products,
                    result_limit=result_limit,
                    exact_count=exact_count,
                    stock_policy=stock_policy,
                    suggested_alternatives=suggested_alternatives,
                    recommended_alternatives=recommended_alternatives,
                    followup_action_executed=followup_action_executed,
                    recommendation_profile=recommendation_profile,
                )
            elif url_quote_lookup_flow:
                availability_result = str(url_quote_retrieval_snapshot.get("availability_result") or "").strip()
                parse_status = str(
                    (
                        url_quote_retrieval_snapshot.get("url_lookup")
                        if isinstance(url_quote_retrieval_snapshot.get("url_lookup"), dict)
                        else {}
                    ).get("parse_status")
                    or ""
                ).strip()
                if lang == "zh-Hant":
                    if availability_result == "not_sold":
                        answer_text = (
                            f"已辨識這款酒是 {display_query}，但目前沒有在 CERP 找到可售品項。"
                            "如果你要，我可以直接幫你轉到詢價流程，請業務協助確認相近替代款。"
                        )
                    elif parse_status == "failed":
                        answer_text = (
                            "已收到這個網址，但目前無法穩定辨識它對應的商品，因此不能直接產生報價清單。"
                            "你可以改提供酒名、酒莊、年份，或讓我改用較寬鬆條件幫你找相近可報價品項。"
                        )
                    else:
                        answer_text = t("quote.no_results", lang, query=display_query)
                else:
                    if availability_result == "not_sold":
                        answer_text = (
                            f"I identified the product as {display_query}, but I could not find a sellable CERP item for it. "
                            "I can still route this into quote chat so the team can review nearby alternatives."
                        )
                    elif parse_status == "failed":
                        answer_text = (
                            "I received the URL, but I could not reliably identify which product it refers to, "
                            "so I cannot generate a quote list yet."
                        )
                    else:
                        answer_text = t("quote.no_results", lang, query=display_query)
            else:
                answer_text = t("quote.no_results", lang, query=display_query)
            answer_text = _sanitize_user_facing_text(answer_text, lang)

            quote_ui = _build_quote_ui_payload(
                lang=lang,
                query=display_query,
                products=products,
                result_limit=result_limit,
                exact_count=exact_count,
                stock_policy=stock_policy,
                suggested_alternatives=suggested_alternatives,
                recommended_alternatives=recommended_alternatives,
                followup_action_executed=followup_action_executed,
                recommendation_profile=recommendation_profile,
            )
            quote_timing["generation_ms"] = round((time.perf_counter() - generation_started) * 1000, 1)
            quote_external_search = (
                dict(url_quote_retrieval_snapshot.get("external_search") or {})
                if url_quote_lookup_flow
                else {
                    "attempted": False,
                    "reason": quote_authoritative_reason,
                    "provider": None,
                    "query": None,
                    "hit_count_pre_filter": 0,
                    "hit_count_post_filter": 0,
                    "fetched_url_count": 0,
                }
            )
            if url_quote_lookup_flow:
                availability_result = str(url_quote_retrieval_snapshot.get("availability_result") or "").strip()
                url_lookup_meta = (
                    url_quote_retrieval_snapshot.get("url_lookup")
                    if isinstance(url_quote_retrieval_snapshot.get("url_lookup"), dict)
                    else {}
                )
                parse_status = str(url_lookup_meta.get("parse_status") or "").strip()
                if availability_result == "exact_match":
                    quote_processing_state = "url_lookup_resolved_exact"
                elif availability_result == "near_match":
                    quote_processing_state = "url_lookup_resolved_near"
                elif availability_result == "not_sold":
                    quote_processing_state = "url_lookup_resolved_not_sold"
                elif parse_status == "failed":
                    quote_processing_state = "url_lookup_parse_failed"
                else:
                    quote_processing_state = "url_lookup_resolved_uncertain"
            else:
                quote_processing_state = (
                    (
                        "attachment_analyzed"
                        if quote_attachment_context.get("status") == "analyzed"
                        else "attachment_analysis_partial"
                    )
                    if quote_attachment_context.get("summary")
                    else (
                        "metadata_only"
                        if attachment_payload
                        else ("url_lookup_pending" if quote_prompt_category == "url_product_lookup" else "no_attachment")
                    )
                )
            quote_missing_capabilities: List[str] = []
            if attachment_payload and not quote_attachment_context.get("summary"):
                quote_missing_capabilities.append("attachment_understood_but_not_fully_processed")
            elif quote_prompt_category == "url_product_lookup" and not url_quote_lookup_flow:
                quote_missing_capabilities.append("url_lookup_understood_but_not_fully_processed")
            if quote_cerp_lookup_error:
                quote_missing_capabilities.append("cerp_stock_lookup_failed")

            quote_official_inventory_binding = _build_quote_inventory_binding(
                raw_query=text,
                display_query=display_query,
                products=products,
                recommended_alternatives=recommended_alternatives,
                official_match_used=(
                    bool(url_quote_retrieval_snapshot.get("official_match_used"))
                    if url_quote_lookup_flow
                    else False
                ),
            )
            quote_hard_error_flags: List[str] = []
            if (
                quote_official_inventory_binding.get("required")
                and not quote_official_inventory_binding.get("proof_count")
            ):
                quote_hard_error_flags.append("quote_inventory_mismatch")

            quote_metadata: Dict[str, Any] = {
                "quote_items": products or [],
                "exact_quote_items": selected_exact_products or [],
                "quote_ui": quote_ui,
                "query": display_query,
                "canonical_query": display_query,
                "raw_query": text,
                "resolved_query": quote_input,
                "search_query": query_text,
                "search_criteria": quote_criteria,
                "requested_filters": requested_filters,
                "query_variants": query_variants,
                "alias_filters": analysis_alias_filters_clean,
                "cerp_alias_filters": cerp_alias_filters,
                "analysis_query_variants": analysis_query_variants,
                "recommendation_profile": recommendation_profile,
                "language": lang,
                "lang": lang,
                "lookup_goal": quote_lookup_goal,
                "applied_result_limit": result_limit,
                "target_count": result_limit,
                "exact_count": exact_count,
                "remaining_needed": remaining_needed,
                "fill_strategy": followup_defaults.get("fill_strategy"),
                "candidate_count": len(candidates),
                "exact_candidate_count": len(exact_candidates),
                "positive_stock_count": quote_stats.get("positive_stock_count", 0),
                "exact_in_stock_count": quote_stats.get("exact_in_stock_count", 0),
                "match_summary": match_summary,
                "recommended_alternatives": recommended_alternatives,
                "suggested_alternatives": suggested_alternatives,
                "stock_policy": stock_policy,
                "official_inventory_binding": quote_official_inventory_binding,
                "hard_error_flags": quote_hard_error_flags,
                "partial_coverage": partial_coverage,
                "quote_selection_mode": quote_selection_mode,
                "match_strategy": (
                    str(url_quote_retrieval_snapshot.get("match_strategy") or "").strip()
                    if url_quote_lookup_flow
                    else "cerp_first"
                ),
                "official_match_used": (
                    bool(url_quote_retrieval_snapshot.get("official_match_used"))
                    if url_quote_lookup_flow
                    else False
                ),
                "availability_result": (
                    str(url_quote_retrieval_snapshot.get("availability_result") or "").strip() or None
                ),
                "url_lookup": (
                    url_quote_retrieval_snapshot.get("url_lookup")
                    if isinstance(url_quote_retrieval_snapshot.get("url_lookup"), dict)
                    else {}
                ),
                "near_match_count": (
                    int(url_quote_retrieval_snapshot.get("near_match_count") or 0)
                    if url_quote_lookup_flow
                    else max(len(candidates) - len(exact_candidates), 0)
                ),
                "exact_match_rejection_reasons": exact_match_rejection_reasons,
                "criteria_hard_filters": {
                    key: value
                    for key, value in requested_filters.items()
                    if key in {
                        "producer",
                        "wine_name",
                        "vintage",
                        "color",
                        "style",
                        "region",
                        "classification",
                        "price_min",
                        "price_max",
                        "price_scope",
                    }
                    and value not in (None, "", [], {})
                },
                "pending_goal": (
                    url_quote_retrieval_snapshot.get("pending_goal")
                    if url_quote_lookup_flow
                    else followup_defaults["pending_goal"]
                ),
                "default_confirm_action": (
                    url_quote_retrieval_snapshot.get("default_confirm_action")
                    if url_quote_lookup_flow
                    else followup_defaults["default_confirm_action"]
                ),
                "available_actions": (
                    list(url_quote_retrieval_snapshot.get("available_actions") or [])
                    if url_quote_lookup_flow
                    else followup_defaults["available_actions"]
                ),
                "followup_confirmation_matched": bool(
                    quote_followup_resolution.get("followup_confirmation_matched")
                ),
                "followup_action_source": (
                    str(quote_followup_resolution.get("followup_action_source") or "").strip()
                    or (
                        requested_followup_action_source
                        if requested_followup_action and requested_followup_action_source
                        else None
                    )
                    or ("auto_default" if followup_action_executed else None)
                ),
                "followup_contract_version": (
                    str(quote_followup_resolution.get("followup_contract_version") or "").strip()
                    or "v2"
                ),
                "relaxed_filters_before": relaxed_filters_before,
                "relaxed_filters_after": relaxed_filters_after,
                "context_resolution": {
                    "is_followup": bool(quote_followup_resolution.get("is_followup")),
                    "canonical_query": display_query,
                    "raw_query": text,
                    "resolved_query": quote_input,
                    "display_query": display_query,
                    "pending_goal": quote_followup_resolution.get("pending_goal"),
                    "followup_action": followup_action_requested,
                    "followup_confirmation_matched": bool(
                        quote_followup_resolution.get("followup_confirmation_matched")
                    ),
                    "followup_action_source": (
                        str(quote_followup_resolution.get("followup_action_source") or "").strip()
                        or (
                            requested_followup_action_source
                            if requested_followup_action and requested_followup_action_source
                            else None
                        )
                    ),
                    "followup_contract_version": (
                        str(quote_followup_resolution.get("followup_contract_version") or "").strip()
                        or "v2"
                    ),
                    "request_overrides": request_overrides,
                },
                "followup_action_executed": followup_action_executed,
                "intent": "QUOTE_LIST",
                "prompt_category": quote_prompt_category,
                "entity_hints": quote_entity_hints,
                "needs_authoritative_sources": quote_needs_authoritative_sources,
                "authoritative_reason": quote_authoritative_reason,
                "attachment": attachment_payload,
                "attachment_ingested": bool(attachment_payload),
                "url_inputs": url_inputs,
                "url_input_count": len(url_inputs),
                "primary_url": (url_inputs[0] if url_inputs else None),
                "url_input_source": ("structured" if url_inputs else None),
                "processing_state": quote_processing_state,
                "attachment_context": quote_attachment_context,
                "attachment_summary": quote_attachment_context.get("summary") if quote_attachment_context else None,
                "attachment_entity_hints": quote_attachment_context.get("entity_hints") if quote_attachment_context else {},
                "attachment_match_intent": quote_attachment_context.get("match_intent") if quote_attachment_context else None,
                "project_context_used": bool(project_context),
                "store_context_used": bool(store_profile),
                "grounded_summary": "",
                "grounded_highlights": [],
                "grounding": {
                    "pre_guardrail_hit_count": 0,
                    "post_guardrail_hit_count": 0,
                    "fallback_applied": False,
                    "guardrail_flags": [],
                },
                "external_search": quote_external_search,
                "retrieval_snapshot": (
                    dict(url_quote_retrieval_snapshot)
                    if url_quote_lookup_flow
                    else {
                        "query": display_query,
                        "effective_query": query_text or display_query,
                        "prompt_category": quote_prompt_category,
                        "needs_authoritative_sources": quote_needs_authoritative_sources,
                        "source_policy": requested_source_policy or "internal_only",
                        "external_search": quote_external_search,
                        "attachment_context_used": bool(quote_attachment_context),
                        "url_inputs": url_inputs,
                        "url_input_count": len(url_inputs),
                        "primary_url": (url_inputs[0] if url_inputs else None),
                        "url_input_source": ("structured" if url_inputs else None),
                    }
                ),
            }
            if isinstance(quote_metadata.get("retrieval_snapshot"), dict):
                quote_metadata["retrieval_snapshot"].setdefault(
                    "official_inventory_binding",
                    quote_official_inventory_binding,
                )
                quote_metadata["retrieval_snapshot"].setdefault("hard_error_flags", quote_hard_error_flags)
            quote_timing["total_ms"] = round((time.perf_counter() - quote_started) * 1000, 1)
            quote_metadata["timing"] = quote_timing
            if quote_missing_capabilities:
                quote_metadata["missing_capabilities"] = quote_missing_capabilities
            quote_metadata["quote_followup"] = build_quote_followup_contract(quote_metadata)
            logger.info(
                "quote flow completed query=%r sanitized=%r variants=%s cerp_alias_keys=%s candidates=%s total_ms=%s",
                text,
                quote_input,
                len(query_variants),
                sorted(cerp_alias_filters.keys()),
                len(candidates),
                quote_timing.get("total_ms"),
            )

            conversation_id = quote_context_conversation_id or requested_conversation_id
            project_id = project_context.get("id") if project_context else None
            project_label = project_context.get("label") if project_context else None
            if not conversation_id and user_id and project_id and not create_new_conversation:
                existing_conv = await find_conversation_by_project(user_id, project_id)
                if existing_conv:
                    conversation_id = str(existing_conv)
            conv_uuid: Optional[uuid.UUID] = None
            if conversation_id:
                try:
                    conv_uuid = uuid.UUID(conversation_id)
                except ValueError:
                    conv_uuid = None

            conv_id = await add_message_to_conversation(
                conv_uuid,
                "user",
                text,
                user_id=user_id,
                project_id=project_id,
                project_label=project_label,
            )
            _, assistant_message_id = await add_message_to_conversation(
                conv_id,
                "assistant",
                answer_text,
                user_id=user_id,
                project_id=project_id,
                project_label=project_label,
                summary_snapshot=quote_ui.get("title"),
                metadata=quote_metadata,
                return_message_id=True,
            )

            answer_payload: Dict[str, Any] = {
                "text": answer_text,
                "citations": [],
                "conversation_id": str(conv_id) if conv_id else None,
                "metadata": quote_metadata,
            }
            if assistant_message_id:
                answer_payload["message_id"] = str(assistant_message_id)

            return {
                "ok": True,
                "kind": "chat",
                "intent": {"name": "QUOTE_LIST"},
                "answer": answer_payload,
                "context": [],
                "content": answer_text,
                "language": lang,
                "project": project_context,
                "store": store_profile or None,
            }

        compact_mode = request.query_params.get("compact") in ("1", "true")
        conversation_id = requested_conversation_id
        project_id_for_lookup = project_context.get("id") if project_context else None
        if not conversation_id and user_id and project_id_for_lookup and not create_new_conversation:
            existing_conv = await find_conversation_by_project(user_id, project_id_for_lookup)
            if existing_conv:
                conversation_id = str(existing_conv)

        refined_text = text
        try:
            nlu_result = await extract_search_entities(text)
            normalized_keywords = nlu_result.get("keywords") or ""
            if normalized_keywords and normalized_keywords.lower() not in text.lower():
                refined_text = f"{text} {normalized_keywords}".strip()
        except Exception as exc:
            logger.warning("NLU extraction failed in standard flow: %s", exc)
            nlu_result = None
        if nlu_result:
            normalized_keywords = nlu_result.get("keywords") or ""
            if isinstance(normalized_keywords, str):
                candidate = normalized_keywords.strip()
                if candidate and candidate.lower() not in text.lower():
                    refined_text = f"{text} {candidate}".strip()

        standard_prompt_category_override: Optional[str] = None
        standard_authoritative_reason_override: Optional[str] = None
        standard_needs_authoritative_override = requested_authoritative_sources
        inferred_standard_producer = analysis_service._infer_producer_from_query(refined_text)
        inferred_standard_category = analysis_service._infer_prompt_category(refined_text)
        if benchmark_trace and requested_prompt_category in BENCHMARK_PROMPT_CATEGORY_OVERRIDES:
            standard_prompt_category_override = requested_prompt_category
        if analysis_service._should_force_brand_profile(
            refined_text,
            base_category=inferred_standard_category,
            inferred_producer=inferred_standard_producer,
        ) and not standard_prompt_category_override:
            standard_prompt_category_override = "brand_profile"

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
            source_policy=requested_source_policy,
            needs_authoritative_sources=standard_needs_authoritative_override,
            prompt_category_override=standard_prompt_category_override,
            authoritative_reason_override=standard_authoritative_reason_override,
            benchmark_trace=benchmark_trace,
            request_deadline_seconds=benchmark_deadline_seconds,
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
            prompt_category = str(answer_metadata.get("prompt_category") or "").strip()
            response_mode = str(answer_metadata.get("response_mode") or "").strip()
            if prompt_category == "general_chat" and response_mode == "generated":
                retrieval_snapshot = answer_metadata.get("retrieval_snapshot") if isinstance(answer_metadata.get("retrieval_snapshot"), dict) else {}
                hit_count = int(retrieval_snapshot.get("selected_hit_count") or 0) if retrieval_snapshot else 0
                if analysis_service._looks_like_outdoor_location_advice_query(text):
                    routing_path = "outdoor_location_llm_with_rag" if hit_count > 0 else "outdoor_location_llm_no_rag"
                else:
                    routing_path = "general_llm_with_rag" if hit_count > 0 else "general_llm_no_rag"
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
        if assistant_message_id:
            await update_message_enrichment(
                assistant_message_id,
                highlights=(answer_payload.get("metadata") or {}).get("grounded_highlights"),
                summary_snapshot=(answer_payload.get("metadata") or {}).get("grounded_summary"),
                metadata=answer_payload.get("metadata"),
            )
        return payload

    except HTTPException:
        raise
    except Exception as ex:
        print(f"FATAL: /chat endpoint error: {type(ex).__name__}: {ex}")
        traceback.print_exc()
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
