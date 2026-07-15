from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import get_current_user_optional
from ..core.chat_history import add_message_to_conversation
from ..core.config import FRONTEND_PUBLIC_BASE_URL
from ..core.database import SessionLocal
from ..core.models import Conversation, EdmPreview, Quote
from ..models.customer import Customer


logger = logging.getLogger(__name__)
router = APIRouter()
SHARED_CONTEXT_KEY = "_edm_shared_context"


async def get_db():
    async with SessionLocal() as db:
        yield db


class EdmSendPayload(BaseModel):
    conversation_id: str
    customer_id: str
    quote_items: List[Dict[str, Any]] = Field(default_factory=list)
    template_id: Optional[str] = "default"


class EdmPreviewRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    no: str = ""
    specification: str = ""
    brand: str = ""
    product_name: str = ""
    color: str = ""
    feature: str = ""
    list_price: Optional[float] = None
    quote_price: Optional[float] = None
    vip_price: Optional[float] = None
    fb_price: Optional[float] = None
    wholesale_price: Optional[float] = None
    selected_quote_tier: str = "vip"
    display_quote_price: Optional[float] = None
    stock: Optional[float] = None
    bundle: str = ""
    bundle_discount_enabled: Optional[bool] = None
    bundle_discount_type: str = ""
    product_link: str = ""


class EdmTableColumn(BaseModel):
    key: str
    label: str = ""
    width: Optional[int] = None


class EdmPreviewCreatePayload(BaseModel):
    conversation_id: Optional[str] = None
    sales_rep: str = ""
    hero_text: str = ""
    project: Optional[Dict[str, Any]] = None
    quote_date: Optional[datetime] = None
    rows: List[EdmPreviewRow] = Field(default_factory=list)
    table_columns: List[EdmTableColumn] = Field(default_factory=list)


class EdmShareEmailPayload(BaseModel):
    recipients: List[str] = Field(default_factory=list)


class EdmPreviewUpdatePayload(BaseModel):
    rows: List[EdmPreviewRow] = Field(default_factory=list)


def _normalize_preview_row(row: EdmPreviewRow) -> Dict[str, Any]:
    payload = row.model_dump()
    specification = ""
    for key in (
        "specification",
        "spec",
        "spec1",
        "model",
        "model_name",
        "model_year",
        "invn807",
        "invn051",
        "size",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            specification = value
            break
    payload["specification"] = specification
    payload.pop("spec", None)
    if not str(payload.get("product_name") or "").strip():
        payload["product_name"] = str(payload.get("product") or payload.get("name") or "").strip()
    return payload


def _require_user(user: Optional[dict]) -> dict:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def _parse_quote_suffix(value: Optional[str], prefix: str) -> int:
    if not value or not value.startswith(prefix):
        return 0
    suffix = value.replace(prefix, "", 1)
    return int(suffix) if suffix.isdigit() else 0


async def _next_quote_no(session: AsyncSession, quote_date: datetime) -> str:
    date_str = quote_date.strftime("%Y%m%d")
    prefix = f"SEQ{date_str}"

    quote_stmt = (
        select(Quote.quote_no)
        .where(Quote.quote_no.like(f"{prefix}%"))
        .order_by(Quote.quote_no.desc())
        .limit(1)
    )
    preview_stmt = (
        select(EdmPreview.quote_no)
        .where(EdmPreview.quote_no.like(f"{prefix}%"))
        .order_by(EdmPreview.quote_no.desc())
        .limit(1)
    )

    quote_result = await session.execute(quote_stmt)
    preview_result = await session.execute(preview_stmt)

    last_quote = quote_result.scalar_one_or_none()
    last_preview = preview_result.scalar_one_or_none()
    next_seq = max(
        _parse_quote_suffix(last_quote, prefix),
        _parse_quote_suffix(last_preview, prefix),
    ) + 1
    return f"{prefix}{next_seq:04d}"


def _build_share_token() -> str:
    return secrets.token_hex(5).upper()


def _resolve_frontend_origin(request: Request) -> str:
    explicit = (FRONTEND_PUBLIC_BASE_URL or "").strip().rstrip("/")
    if explicit:
        return explicit

    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if origin:
        return origin

    referer = (request.headers.get("referer") or "").strip()
    if referer:
        parsed = urlsplit(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

    return f"{request.url.scheme}://{request.url.netloc}"


def _build_share_url(request: Request, share_token: str) -> str:
    return f"{_resolve_frontend_origin(request)}/edm/share/{share_token}"


def _safe_object(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _serialize_customer_record(customer: Customer) -> Dict[str, Any]:
    return {
        "id": str(customer.id),
        "name": customer.name or "",
        "email": customer.email or "",
        "phone": customer.phone or "",
    }


def _serialize_customer_snapshot(snapshot: Any) -> Optional[Dict[str, Any]]:
    payload = _safe_object(snapshot)
    if not payload:
        return None
    customer_id = payload.get("id")
    return {
        "id": str(customer_id) if customer_id is not None else None,
        "name": payload.get("name") or "",
        "email": payload.get("email") or "",
        "phone": payload.get("phone") or "",
    }


async def _build_shared_context(
    session: AsyncSession,
    conversation_id: Optional[str],
) -> Dict[str, Any]:
    normalized_conversation_id = (conversation_id or "").strip() or None
    shared_context: Dict[str, Any] = {
        "conversation_id": normalized_conversation_id,
        "customer": None,
    }
    if not normalized_conversation_id:
        return shared_context

    try:
        conv_uuid = uuid.UUID(normalized_conversation_id)
    except ValueError:
        return shared_context

    result = await session.execute(
        select(Conversation).where(Conversation.id == conv_uuid)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        return shared_context

    customer_payload = _serialize_customer_snapshot(conversation.customer_snapshot)
    if conversation.customer_id:
        customer_result = await session.execute(
            select(Customer).where(Customer.id == conversation.customer_id)
        )
        customer = customer_result.scalar_one_or_none()
        if customer:
            customer_payload = _serialize_customer_record(customer)

    shared_context["customer"] = customer_payload
    return shared_context


def _merge_project_snapshot(
    project_snapshot: Optional[Dict[str, Any]],
    shared_context: Dict[str, Any],
) -> Dict[str, Any]:
    payload = dict(_safe_object(project_snapshot))
    payload[SHARED_CONTEXT_KEY] = {
        "conversation_id": shared_context.get("conversation_id"),
        "customer": shared_context.get("customer"),
    }
    return payload


def _extract_shared_context(preview: EdmPreview) -> Dict[str, Any]:
    project_snapshot = dict(_safe_object(preview.project_snapshot))
    shared_context = _safe_object(project_snapshot.pop(SHARED_CONTEXT_KEY, None))
    return {
        "project": project_snapshot,
        "conversation_id": shared_context.get("conversation_id") or preview.conversation_id,
        "customer": _serialize_customer_snapshot(shared_context.get("customer")),
    }


def _serialize_preview(preview: EdmPreview) -> Dict[str, Any]:
    shared_context = _extract_shared_context(preview)
    return {
        "share_token": preview.share_token,
        "share_url": preview.share_url,
        "quote_no": preview.quote_no,
        "quote_date": preview.quote_date.isoformat(),
        "sales_rep": preview.sales_rep or "",
        "hero_text": preview.hero_text or "",
        "banner": preview.banner_snapshot or {},
        "rows": preview.rows_snapshot or [],
        "table_columns": preview.table_columns_snapshot or [],
        "project": shared_context["project"],
        "conversation_id": shared_context["conversation_id"],
        "customer": shared_context["customer"],
        "read_only": False,
    }


@router.post("/edm/previews")
async def create_edm_preview(
    payload: EdmPreviewCreatePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[dict] = Depends(get_current_user_optional),
):
    auth_user = _require_user(user)

    rows = [_normalize_preview_row(row) for row in payload.rows if row.no or row.product_name or getattr(row, "product", "")]
    if not rows:
        raise HTTPException(status_code=400, detail="Preview rows are required")

    quote_date = payload.quote_date or datetime.now(timezone.utc)
    quote_no = await _next_quote_no(db, quote_date)

    while True:
        share_token = _build_share_token()
        token_result = await db.execute(
            select(EdmPreview.id).where(EdmPreview.share_token == share_token)
        )
        if not token_result.scalar_one_or_none():
            break

    banner_snapshot = {
        "sales": (payload.sales_rep or auth_user.get("username") or auth_user.get("email") or "").strip(),
        "quote_no": quote_no,
        "quote_date": quote_date.isoformat(),
    }
    share_url = _build_share_url(request, share_token)
    shared_context = await _build_shared_context(db, payload.conversation_id)

    preview = EdmPreview(
        share_token=share_token,
        conversation_id=(payload.conversation_id or "").strip() or None,
        created_by_username=auth_user.get("username") or auth_user.get("email"),
        quote_no=quote_no,
        quote_date=quote_date,
        sales_rep=banner_snapshot["sales"],
        hero_text=(payload.hero_text or "").strip(),
        banner_snapshot=banner_snapshot,
        rows_snapshot=rows,
        table_columns_snapshot=[column.model_dump() for column in payload.table_columns],
        project_snapshot=_merge_project_snapshot(payload.project, shared_context),
        share_url=share_url,
    )
    db.add(preview)
    await db.commit()
    await db.refresh(preview)
    return _serialize_preview(preview)


@router.get("/edm/previews/{share_token}")
async def get_edm_preview(share_token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EdmPreview).where(EdmPreview.share_token == share_token)
    )
    preview = result.scalar_one_or_none()
    if not preview:
        raise HTTPException(status_code=404, detail="Preview not found")

    payload = _serialize_preview(preview)
    payload["read_only"] = True
    return payload


@router.patch("/edm/previews/{share_token}")
async def update_edm_preview(
    share_token: str,
    payload: EdmPreviewUpdatePayload,
    db: AsyncSession = Depends(get_db),
    user: Optional[dict] = Depends(get_current_user_optional),
):
    _require_user(user)

    rows = [_normalize_preview_row(row) for row in payload.rows if row.no or row.product_name or getattr(row, "product", "")]
    if not rows:
        raise HTTPException(status_code=400, detail="Preview rows are required")

    result = await db.execute(
        select(EdmPreview).where(EdmPreview.share_token == share_token)
    )
    preview = result.scalar_one_or_none()
    if not preview:
        raise HTTPException(status_code=404, detail="Preview not found")

    preview.rows_snapshot = rows
    await db.commit()
    await db.refresh(preview)
    return _serialize_preview(preview)


@router.post("/edm/previews/{share_token}/share-email")
async def share_edm_preview_email(
    share_token: str,
    payload: EdmShareEmailPayload,
    db: AsyncSession = Depends(get_db),
    user: Optional[dict] = Depends(get_current_user_optional),
):
    auth_user = _require_user(user)

    recipients = [value.strip() for value in payload.recipients if value and value.strip()]
    if not recipients:
        raise HTTPException(status_code=400, detail="At least one recipient is required")

    result = await db.execute(
        select(EdmPreview).where(EdmPreview.share_token == share_token)
    )
    preview = result.scalar_one_or_none()
    if not preview:
        raise HTTPException(status_code=404, detail="Preview not found")

    logger.info(
        "Stub EDM share email: share_token=%s sender=%s recipients=%s share_url=%s",
        share_token,
        auth_user.get("username") or auth_user.get("email"),
        recipients,
        preview.share_url,
    )

    return {
        "ok": True,
        "message": "Share email queued.",
        "sent_count": len(recipients),
        "share_url": preview.share_url,
    }


@router.post("/edm/send")
async def send_edm(payload: EdmSendPayload, db: AsyncSession = Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(payload.conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation_id") from exc
    try:
        customer_uuid = uuid.UUID(str(payload.customer_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid customer_id") from exc

    conv_result = await db.execute(select(Conversation).where(Conversation.id == conv_uuid))
    conversation = conv_result.scalars().first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    cust_result = await db.execute(select(Customer).where(Customer.id == customer_uuid))
    customer = cust_result.scalars().first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not customer.email:
        raise HTTPException(status_code=400, detail="Customer email is required to send EDM")

    logger.info(
        "Mock EDM send: conversation=%s customer_id=%s items=%s template=%s",
        payload.conversation_id,
        payload.customer_id,
        len(payload.quote_items or []),
        payload.template_id,
    )

    message = f"EDM sent to {customer.name} ({customer.email})."
    await add_message_to_conversation(
        conv_uuid,
        "assistant",
        message,
        metadata={
            "edm": {
                "customer_id": str(customer_uuid),
                "quote_items": payload.quote_items,
                "template_id": payload.template_id,
            }
        },
    )

    return {"ok": True, "message": message}
