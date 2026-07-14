import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..core import db
from ..core.auth import get_current_active_admin_user, get_current_user_optional

router = APIRouter(tags=["Feedback"])

REVIEW_STATUSES = {"pending", "approved", "rejected", "needs_data", "holdout_only"}
DATASET_SPLITS = {"train", "validation", "holdout", "retrieval_eval", "excluded"}


class FeedbackRequest(BaseModel):
    query: str
    selected_key: Optional[str] = None
    feedback_type: str
    user_id: Optional[int] = None
    case_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    prompt_category: Optional[str] = None
    issue_tags: Optional[List[str]] = None
    primary_issue: Optional[str] = None
    correction_text: Optional[str] = None
    grounding: Optional[str] = None
    grounded: Optional[bool] = None
    source_quality: Optional[str] = None
    attachment_type: Optional[str] = None
    preferred_answer: Optional[str] = None
    retrieval_snapshot: Optional[Dict[str, Any]] = None
    answer_metadata_snapshot: Optional[Dict[str, Any]] = None
    entity_resolution: Optional[Dict[str, Any]] = None
    citation_validation: Optional[Dict[str, Any]] = None
    source_policy: Optional[str] = None
    official_inventory_binding: Optional[Dict[str, Any]] = None
    followup_context: Optional[Dict[str, Any]] = None
    hard_error_flags: Optional[List[str]] = None


class FeedbackReviewRequest(BaseModel):
    review_status: Optional[str] = None
    issue_tags: Optional[List[str]] = None
    correction_text: Optional[str] = None
    preferred_answer: Optional[str] = None
    dataset_split: Optional[str] = None
    review_note: Optional[str] = None


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        return parsed
    return value


def _row_to_dict(row: Any) -> Dict[str, Any]:
    payload = dict(row or {})
    for key in ("issue_tags", "retrieval_snapshot", "answer_metadata_snapshot"):
        if key in payload:
            payload[key] = _normalize_json(payload.get(key))
    for key in ("created_at", "reviewed_at"):
        value = payload.get(key)
        if hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
    return payload


def _normalize_review_status(value: Optional[str]) -> Optional[str]:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    if normalized not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"review_status must be one of: {', '.join(sorted(REVIEW_STATUSES))}",
        )
    return normalized


def _normalize_dataset_split(value: Optional[str]) -> Optional[str]:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    if normalized not in DATASET_SPLITS:
        raise HTTPException(
            status_code=422,
            detail=f"dataset_split must be one of: {', '.join(sorted(DATASET_SPLITS))}",
        )
    return normalized


def _reviewer_id(user: Optional[dict]) -> Optional[str]:
    if not isinstance(user, dict):
        return None
    for key in ("username", "email", "id"):
        value = user.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


@router.post("/feedback")
async def create_feedback(
    payload: FeedbackRequest,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = payload.user_id
    if user and isinstance(user, dict):
        user_id = user.get("id") or user_id

    normalized_issue_tags = list(payload.issue_tags or [])
    if payload.primary_issue and payload.primary_issue not in normalized_issue_tags and payload.primary_issue != "OK":
        normalized_issue_tags.append(payload.primary_issue)
    for flag in payload.hard_error_flags or []:
        if flag and flag not in normalized_issue_tags:
            normalized_issue_tags.append(flag)

    retrieval_snapshot = dict(payload.retrieval_snapshot or {})
    if payload.entity_resolution is not None:
        retrieval_snapshot.setdefault("entity_resolution", payload.entity_resolution)
    if payload.source_policy:
        retrieval_snapshot.setdefault("source_policy", payload.source_policy)
    if payload.official_inventory_binding is not None:
        retrieval_snapshot.setdefault("official_inventory_binding", payload.official_inventory_binding)
    if payload.followup_context is not None:
        retrieval_snapshot.setdefault("followup_context", payload.followup_context)

    answer_metadata_snapshot = dict(payload.answer_metadata_snapshot or {})
    phase1_diagnostics = dict(answer_metadata_snapshot.get("phase1_diagnostics") or {})
    for key, value in {
        "grounded": payload.grounded,
        "entity_resolution": payload.entity_resolution,
        "citation_validation": payload.citation_validation,
        "source_policy": payload.source_policy,
        "official_inventory_binding": payload.official_inventory_binding,
        "followup_context": payload.followup_context,
        "hard_error_flags": payload.hard_error_flags,
    }.items():
        if value is not None:
            phase1_diagnostics[key] = value
    if phase1_diagnostics:
        answer_metadata_snapshot["phase1_diagnostics"] = phase1_diagnostics

    conn = await db.get_conn()
    try:
        row_id = await conn.fetchval(
            """
            INSERT INTO search_feedback (
                query,
                selected_key,
                feedback_type,
                user_id,
                case_id,
                conversation_id,
                message_id,
                prompt_category,
                issue_tags,
                correction_text,
                grounding,
                source_quality,
                attachment_type,
                preferred_answer,
                retrieval_snapshot,
                answer_metadata_snapshot,
                review_status
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13, $14, $15::jsonb, $16::jsonb, $17
            )
            RETURNING id
            """,
            payload.query,
            payload.selected_key,
            payload.feedback_type,
            user_id,
            _normalize_optional_text(payload.case_id),
            payload.conversation_id,
            payload.message_id,
            payload.prompt_category,
            json.dumps(normalized_issue_tags) if normalized_issue_tags else None,
            payload.correction_text,
            payload.grounding,
            payload.source_quality,
            payload.attachment_type,
            payload.preferred_answer,
            json.dumps(retrieval_snapshot) if retrieval_snapshot else None,
            json.dumps(answer_metadata_snapshot) if answer_metadata_snapshot else None,
            "pending",
        )
    finally:
        await conn.close()

    return {"ok": True, "id": row_id}


@router.get("/feedback/review-queue")
async def list_feedback_review_queue(
    status_filter: Optional[str] = Query(default="pending", alias="status"),
    case_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_active_admin_user),
):
    review_status = _normalize_review_status(status_filter)
    normalized_case_id = _normalize_optional_text(case_id)
    conn = await db.get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT
                id,
                query,
                selected_key,
                feedback_type,
                created_at,
                user_id,
                case_id,
                conversation_id,
                message_id,
                prompt_category,
                issue_tags,
                correction_text,
                grounding,
                source_quality,
                attachment_type,
                preferred_answer,
                retrieval_snapshot,
                answer_metadata_snapshot,
                review_status,
                reviewed_by,
                reviewed_at,
                review_note,
                dataset_split
            FROM search_feedback
            WHERE ($1::text IS NULL OR COALESCE(review_status, 'pending') = $1)
              AND ($2::text IS NULL OR case_id = $2)
            ORDER BY created_at DESC, id DESC
            LIMIT $3 OFFSET $4
            """,
            review_status,
            normalized_case_id,
            limit,
            offset,
        )
    finally:
        await conn.close()
    return {"ok": True, "items": [_row_to_dict(row) for row in rows], "count": len(rows)}


@router.patch("/feedback/{feedback_id}/review")
async def update_feedback_review(
    feedback_id: int,
    payload: FeedbackReviewRequest,
    user: dict = Depends(get_current_active_admin_user),
):
    review_status = _normalize_review_status(payload.review_status)
    dataset_split = _normalize_dataset_split(payload.dataset_split)
    reviewer = _reviewer_id(user)

    conn = await db.get_conn()
    try:
        current = await conn.fetchrow(
            """
            SELECT id, correction_text, preferred_answer
            FROM search_feedback
            WHERE id = $1
            """,
            feedback_id,
        )
        if not current:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

        current_payload = dict(current)
        final_correction = (
            payload.correction_text
            if payload.correction_text is not None
            else current_payload.get("correction_text")
        )
        final_preferred = (
            payload.preferred_answer
            if payload.preferred_answer is not None
            else current_payload.get("preferred_answer")
        )
        if review_status == "approved" and not (
            _normalize_optional_text(final_correction) or _normalize_optional_text(final_preferred)
        ):
            raise HTTPException(
                status_code=422,
                detail="approved feedback requires correction_text or preferred_answer",
            )

        updated = await conn.fetchrow(
            """
            UPDATE search_feedback
            SET
                review_status = COALESCE($2, review_status),
                issue_tags = COALESCE($3::jsonb, issue_tags),
                correction_text = COALESCE($4, correction_text),
                preferred_answer = COALESCE($5, preferred_answer),
                dataset_split = COALESCE($6, dataset_split),
                review_note = COALESCE($7, review_note),
                reviewed_by = $8,
                reviewed_at = NOW()
            WHERE id = $1
            RETURNING
                id,
                query,
                selected_key,
                feedback_type,
                created_at,
                user_id,
                case_id,
                conversation_id,
                message_id,
                prompt_category,
                issue_tags,
                correction_text,
                grounding,
                source_quality,
                attachment_type,
                preferred_answer,
                retrieval_snapshot,
                answer_metadata_snapshot,
                review_status,
                reviewed_by,
                reviewed_at,
                review_note,
                dataset_split
            """,
            feedback_id,
            review_status,
            json.dumps(payload.issue_tags) if payload.issue_tags is not None else None,
            payload.correction_text,
            payload.preferred_answer,
            dataset_split,
            payload.review_note,
            reviewer,
        )
    finally:
        await conn.close()

    return {"ok": True, "item": _row_to_dict(updated)}
