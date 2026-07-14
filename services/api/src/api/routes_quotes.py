from __future__ import annotations

from datetime import datetime
from uuid import UUID
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import get_current_user_optional
from ..core.database import SessionLocal
from ..core.models import Conversation, EdmPreview, Quote

router = APIRouter(prefix="/quotes", tags=["Quotes"])


async def get_db():
    async with SessionLocal() as session:
        yield session


def _require_user(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if user:
        return user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


class QuoteCreate(BaseModel):
    conversation_id: Optional[str] = None
    customer_id: Optional[UUID] = None
    customer_name: str = ""
    sales_rep: str = ""
    quote_items: List[dict[str, Any]] = Field(default_factory=list)
    taxable_amount: Optional[int] = None
    tax_amount: Optional[int] = None
    total_amount: Optional[int] = None
    quote_date: datetime
    reply_date: Optional[datetime] = None


class QuoteOut(BaseModel):
    id: str
    quote_no: str
    customer_id: Optional[str] = None
    customer_name: str = ""
    sales_rep: str = ""
    quote_date: datetime
    reply_date: Optional[datetime] = None
    taxable_amount: Optional[int] = None
    tax_amount: Optional[int] = None
    total_amount: Optional[int] = None
    quote_items: List[dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class QuoteListItem(BaseModel):
    id: str
    quote_no: str
    customer_id: Optional[str] = None
    customer_name: str = ""
    sales_rep: str = ""
    quote_date: datetime
    reply_date: Optional[datetime] = None
    total_amount: Optional[int] = None
    quote_items: List[dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class QuoteListResponse(BaseModel):
    items: List[QuoteListItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10


def _normalize_quote_customer_name(value: Any) -> str:
    return str(value or "").strip()


def _resolve_quote_customer_name_from_conversation(
    conversation: Optional[Conversation],
    fallback_name: str = "",
) -> str:
    fallback = _normalize_quote_customer_name(fallback_name)
    if not conversation:
        return fallback

    project_label = _normalize_quote_customer_name(getattr(conversation, "project_label", ""))
    if project_label:
        return project_label

    title = _normalize_quote_customer_name(getattr(conversation, "title", ""))
    if title:
        return title

    return fallback


async def _resolve_quote_customer_name(
    session: AsyncSession,
    conversation_id: Optional[str],
    fallback_name: str = "",
) -> str:
    fallback = _normalize_quote_customer_name(fallback_name)
    normalized_conversation_id = _normalize_quote_customer_name(conversation_id)
    if not normalized_conversation_id:
        return fallback

    try:
        conversation_uuid = UUID(normalized_conversation_id)
    except (TypeError, ValueError, AttributeError):
        return fallback

    result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_uuid)
    )
    conversation = result.scalar_one_or_none()
    return _resolve_quote_customer_name_from_conversation(conversation, fallback)


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
    candidates = [
        quote_result.scalar_one_or_none(),
        preview_result.scalar_one_or_none(),
    ]
    last_seq = 0
    for value in candidates:
        if not value or not value.startswith(prefix):
            continue
        suffix = value.replace(prefix, "")
        if suffix.isdigit():
            last_seq = max(last_seq, int(suffix))
    return f"{prefix}{last_seq + 1:04d}"


def _build_pdf_bytes(quote_no: str) -> bytes:
    text = f"Quote: {quote_no}"
    content = f"BT /F1 18 Tf 50 740 Td ({text}) Tj ET"
    content_bytes = content.encode("utf-8")
    length = len(content_bytes)
    header = b"%PDF-1.4\n"
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n",
        f"4 0 obj << /Length {length} >> stream\n".encode("utf-8")
        + content_bytes
        + b"\nendstream endobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    offsets = []
    current = len(header)
    for obj in objects:
        offsets.append(current)
        current += len(obj)
    xref_start = current
    xref_lines = [b"xref\n0 6\n", b"0000000000 65535 f \n"]
    for offset in offsets:
        xref_lines.append(f"{offset:010d} 00000 n \n".encode("utf-8"))
    xref = b"".join(xref_lines)
    trailer = (
        b"trailer << /Size 6 /Root 1 0 R >>\n"
        b"startxref\n"
        + str(xref_start).encode("utf-8")
        + b"\n%%EOF"
    )
    return header + b"".join(objects) + xref + trailer


def _serialize_quote(quote: Quote) -> QuoteOut:
    return QuoteOut(
        id=str(quote.id),
        quote_no=quote.quote_no,
        customer_id=str(quote.customer_id) if quote.customer_id else None,
        customer_name=quote.customer_name or "",
        sales_rep=quote.sales_rep or "",
        quote_date=quote.quote_date,
        reply_date=quote.reply_date,
        taxable_amount=quote.taxable_amount,
        tax_amount=quote.tax_amount,
        total_amount=quote.total_amount,
        quote_items=quote.quote_items or [],
        created_at=quote.created_at,
    )


def _serialize_quote_list_item(quote: Quote) -> QuoteListItem:
    return QuoteListItem(
        id=str(quote.id),
        quote_no=quote.quote_no,
        customer_id=str(quote.customer_id) if quote.customer_id else None,
        customer_name=quote.customer_name or "",
        sales_rep=quote.sales_rep or "",
        quote_date=quote.quote_date,
        reply_date=quote.reply_date,
        total_amount=quote.total_amount,
        quote_items=quote.quote_items or [],
        created_at=quote.created_at,
    )


@router.post("", response_model=QuoteOut)
async def create_quote(
    payload: QuoteCreate,
    session: AsyncSession = Depends(get_db),
) -> QuoteOut:
    if not payload.quote_items:
        raise HTTPException(status_code=400, detail="quote_items is required")
    quote_no = await _next_quote_no(session, payload.quote_date)
    customer_name = await _resolve_quote_customer_name(
        session,
        payload.conversation_id,
        payload.customer_name,
    )
    quote = Quote(
        quote_no=quote_no,
        customer_id=payload.customer_id,
        customer_name=customer_name,
        sales_rep=payload.sales_rep,
        quote_date=payload.quote_date,
        reply_date=payload.reply_date,
        taxable_amount=payload.taxable_amount,
        tax_amount=payload.tax_amount,
        total_amount=payload.total_amount,
        quote_items=payload.quote_items,
    )
    session.add(quote)
    await session.commit()
    await session.refresh(quote)
    return _serialize_quote(quote)


@router.get("", response_model=QuoteListResponse)
async def list_quotes(
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_db),
) -> QuoteListResponse:
    _require_user(user)

    keyword = q.strip()
    filters = []
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(
            or_(
                Quote.quote_no.ilike(pattern),
                Quote.customer_name.ilike(pattern),
            )
        )

    stmt = select(Quote)
    count_stmt = select(func.count()).select_from(Quote)

    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    stmt = (
        stmt.order_by(
            Quote.reply_date.desc().nullslast(),
            Quote.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await session.execute(stmt)
    count_result = await session.execute(count_stmt)
    items = result.scalars().all()
    total = int(count_result.scalar() or 0)

    return QuoteListResponse(
        items=[_serialize_quote_list_item(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quote(
    quote_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_db),
):
    _require_user(user)

    stmt = select(Quote).where(Quote.id == quote_id)
    result = await session.execute(stmt)
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    await session.execute(delete(Quote).where(Quote.id == quote.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{quote_id}/pdf")
async def download_quote_pdf(
    quote_id: str,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Quote).where(Quote.id == quote_id)
    result = await session.execute(stmt)
    quote = result.scalar_one_or_none()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    pdf_bytes = _build_pdf_bytes(quote.quote_no)
    headers = {
        "Content-Disposition": f'attachment; filename=\"{quote.quote_no}.pdf\"'
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
