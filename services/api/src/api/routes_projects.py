from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from ..core.auth import get_current_user_optional
from ..core.database import SessionLocal
from ..services.project_service import (
    archive_project_and_conversations,
    create_conversation_invitation,
    create_project,
    create_project_invitation,
    get_project_or_404,
    list_pending_invitations,
    list_conversation_invitations,
    list_project_conversations,
    list_project_invitations,
    list_projects,
    search_invitable_users,
    respond_invitation,
    revoke_conversation_invitation,
    revoke_project_invitation,
    resolve_project_name_map,
    search_conversations_global,
    update_project,
)


router = APIRouter()


class CustomerProfilePayload(BaseModel):
    customer_type: Optional[str] = None
    trade_count: Optional[int] = None
    last_trade_at: Optional[str] = None
    avg_unit_price: Optional[int] = None
    preference_note: Optional[str] = None
    region: Optional[str] = None
    has_wine_cabinet: Optional[bool] = None


class ProjectCreatePayload(BaseModel):
    name: str
    visibility: str = "private"
    customer_profile: Optional[CustomerProfilePayload] = None


class ProjectUpdatePayload(BaseModel):
    name: Optional[str] = None
    visibility: Optional[str] = None
    customer_profile: Optional[CustomerProfilePayload] = None


class InvitationPayload(BaseModel):
    identifier: Optional[str] = Field(default=None, min_length=1)
    email: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _ensure_identifier(self):
        identifier = (self.identifier or self.email or "").strip()
        if not identifier:
            raise ValueError("identifier is required")
        self.identifier = identifier
        if self.email:
            self.email = self.email.strip()
        return self

    @property
    def invite_identifier(self) -> str:
        return (self.identifier or self.email or "").strip()


@router.get("/projects")
async def get_projects(
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size, 100))
    async with SessionLocal() as session:
        data = await list_projects(session, user, q, safe_page, safe_page_size)
    return {"ok": True, **data}


@router.get("/projects/conversations/search")
async def get_global_conversation_search(
    q: Optional[str] = None,
    scope: Optional[str] = "all",
    page: int = 1,
    page_size: int = 10,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size, 100))
    async with SessionLocal() as session:
        data = await search_conversations_global(session, user, q, safe_page, safe_page_size, scope=scope or "all")
    return {"ok": True, **data}


@router.get("/projects/name-map")
async def get_project_name_map(
    ids: str = "",
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Login required")
    raw_ids = [part.strip() for part in str(ids).split(",") if part and part.strip()]
    async with SessionLocal() as session:
        mapping = await resolve_project_name_map(session, raw_ids)
    return {"ok": True, "items": mapping}


@router.get("/invitations/candidates")
async def get_invitation_candidates(
    q: str = "",
    scope: str = "conversation",
    target_id: str = "",
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        items = await search_invitable_users(session, user, q, scope, target_id)
    return {"ok": True, "items": items}


@router.post("/projects")
async def post_project(
    payload: ProjectCreatePayload,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    profile = payload.customer_profile.model_dump() if payload.customer_profile else {}
    async with SessionLocal() as session:
        project = await create_project(
            session,
            user,
            {
                "name": payload.name,
                "visibility": payload.visibility,
                "customer_profile": profile,
            },
        )

    return {
        "ok": True,
        "item": {
            "id": project.id,
            "name": project.name,
            "visibility": project.visibility,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "customer_profile": {
                "customer_type": project.customer_type,
                "trade_count": project.trade_count,
                "last_trade_at": project.last_trade_at.isoformat() if project.last_trade_at else None,
                "avg_unit_price": project.avg_unit_price,
                "preference_note": project.preference_note,
                "region": project.region,
                "has_wine_cabinet": project.has_wine_cabinet,
            },
        },
    }


@router.patch("/projects/{project_id}")
async def patch_project(
    project_id: str,
    payload: ProjectUpdatePayload,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    profile = payload.customer_profile.model_dump(exclude_unset=True) if payload.customer_profile else {}
    async with SessionLocal() as session:
        project = await get_project_or_404(session, project_id)
        updated = await update_project(
            session,
            user,
            project,
            {
                "name": payload.name,
                "visibility": payload.visibility,
                "customer_profile": profile,
            },
        )
    return {
        "ok": True,
        "item": {
            "id": updated.id,
            "name": updated.name,
            "visibility": updated.visibility,
            "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
            "customer_profile": {
                "customer_type": updated.customer_type,
                "trade_count": updated.trade_count,
                "last_trade_at": updated.last_trade_at.isoformat() if updated.last_trade_at else None,
                "avg_unit_price": updated.avg_unit_price,
                "preference_note": updated.preference_note,
                "region": updated.region,
                "has_wine_cabinet": updated.has_wine_cabinet,
            },
        },
    }


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        project = await get_project_or_404(session, project_id)
        await archive_project_and_conversations(session, user, project)
    return {"ok": True}


@router.get("/projects/{project_id}/conversations")
async def get_project_conversations(
    project_id: str,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size, 100))
    async with SessionLocal() as session:
        project = await get_project_or_404(session, project_id)
        data = await list_project_conversations(session, user, project, q, safe_page, safe_page_size)
    return {"ok": True, "project": {"id": project.id, "name": project.name}, **data}


@router.post("/projects/{project_id}/invitations")
async def post_project_invitation(
    project_id: str,
    payload: InvitationPayload,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        project = await get_project_or_404(session, project_id)
        invitation = await create_project_invitation(session, user, project, payload.invite_identifier)

    return {
        "ok": True,
        "item": {
            "id": str(invitation.id),
            "email": invitation.invited_email,
            "status": invitation.status,
            "invited_user_id": invitation.invited_user_id,
            "created_at": invitation.created_at.isoformat() if invitation.created_at else None,
        },
    }


@router.get("/projects/{project_id}/invitations")
async def get_project_invitations(
    project_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        project = await get_project_or_404(session, project_id)
        items = await list_project_invitations(session, user, project)
    return {"ok": True, "items": items}


@router.delete("/projects/{project_id}/invitations/{invitation_id}")
async def delete_project_invitation(
    project_id: str,
    invitation_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        project = await get_project_or_404(session, project_id)
        await revoke_project_invitation(session, user, project, invitation_id)
    return {"ok": True}


@router.post("/conversations/{conversation_id}/invitations")
async def post_conversation_invitation(
    conversation_id: str,
    payload: InvitationPayload,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        invitation = await create_conversation_invitation(session, user, conversation_id, payload.invite_identifier)

    return {
        "ok": True,
        "item": {
            "id": str(invitation.id),
            "email": invitation.invited_email,
            "status": invitation.status,
            "invited_user_id": invitation.invited_user_id,
            "created_at": invitation.created_at.isoformat() if invitation.created_at else None,
        },
    }


@router.get("/conversations/{conversation_id}/invitations")
async def get_conversation_invitation_list(
    conversation_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        items = await list_conversation_invitations(session, user, conversation_id)
    return {"ok": True, "items": items}


@router.delete("/conversations/{conversation_id}/invitations/{invitation_id}")
async def delete_conversation_invitation(
    conversation_id: str,
    invitation_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        await revoke_conversation_invitation(session, user, conversation_id, invitation_id)
    return {"ok": True}


@router.get("/projects/invitations/pending")
async def get_pending_invitations(
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        items = await list_pending_invitations(session, user)
    return {"ok": True, "items": items}


@router.post("/projects/invitations/{invitation_id}/accept")
async def accept_invitation(
    invitation_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        result = await respond_invitation(session, user, invitation_id, "accepted")
    return {"ok": True, **result}


@router.post("/projects/invitations/{invitation_id}/reject")
async def reject_invitation(
    invitation_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    async with SessionLocal() as session:
        result = await respond_invitation(session, user, invitation_id, "rejected")
    return {"ok": True, **result}
