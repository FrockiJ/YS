import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import and_, desc, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.models import Conversation, Message, User
from ..models.project import Project, ProjectInvitation, ConversationInvitation


def _normalize_visibility(value: Optional[str]) -> str:
    normalized = (value or "private").strip().lower()
    return normalized if normalized in {"private", "public"} else "private"


def _normalize_invite_identifier(value: str) -> str:
    identifier = (value or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Account is required")
    return identifier.lower()


def _is_active_share_status(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() != "revoked"


def _display_share_status(value: Optional[str]) -> str:
    return "accepted" if _is_active_share_status(value) else "revoked"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has_custom_title(title: Optional[str]) -> bool:
    normalized = (title or "").strip()
    if not normalized:
        return False
    return normalized.lower() not in {"new conversation", "新對話"}


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            normalized = value.strip()
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            return datetime.fromisoformat(normalized)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid datetime format")
    raise HTTPException(status_code=400, detail="Invalid datetime format")


def _is_sadmin(user: Optional[Dict[str, Any]]) -> bool:
    role = str((user or {}).get("role") or "").strip().lower()
    return role == "sadmin"


def _user_identifier(user: Optional[Dict[str, Any]]) -> str:
    if not user:
        return ""
    return str(user.get("username") or user.get("email") or "").strip().lower()


async def _resolve_user_by_identifier(session: AsyncSession, identifier: str) -> Optional[User]:
    result = await session.execute(
        select(User).where(func.lower(User.username) == identifier)
    )
    return result.scalar_one_or_none()


async def _build_conversation_preview_map(
    session: AsyncSession,
    conversation_ids: List[Any],
) -> Dict[str, Dict[str, Optional[str]]]:
    normalized_ids = [cid for cid in conversation_ids if cid]
    if not normalized_ids:
        return {}
    rows_result = await session.execute(
        select(
            Message.conversation_id,
            Message.role,
            Message.content,
            Message.summary_snapshot,
            Message.created_at,
        )
        .where(Message.conversation_id.in_(normalized_ids))
        .order_by(Message.conversation_id.asc(), Message.created_at.desc())
    )
    previews: Dict[str, Dict[str, Optional[str]]] = {}
    for conversation_id, role, content, summary_snapshot, _ in rows_result.all():
        key = str(conversation_id)
        current = previews.setdefault(key, {"summary": None, "last_user_message": None})
        if current["summary"] is None:
            summary_candidate = (summary_snapshot or content or "").strip()
            if summary_candidate:
                current["summary"] = summary_candidate
        if role == "user" and current["last_user_message"] is None and content:
                current["last_user_message"] = content
    return previews


def _normalize_excerpt_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _truncate_excerpt_around_query(text: str, query: str, radius: int = 56) -> str:
    clean_text = _normalize_excerpt_text(text)
    clean_query = _normalize_excerpt_text(query)
    if not clean_text:
        return ""
    if not clean_query:
        return clean_text[: radius * 2].strip()
    lowered_text = clean_text.lower()
    lowered_query = clean_query.lower()
    index = lowered_text.find(lowered_query)
    if index < 0:
        return clean_text[: radius * 2].strip()
    start = max(0, index - radius)
    end = min(len(clean_text), index + len(clean_query) + radius)
    excerpt = clean_text[start:end].strip()
    if start > 0:
        excerpt = f"...{excerpt}"
    if end < len(clean_text):
        excerpt = f"{excerpt}..."
    return excerpt


def _build_match_excerpt(content: Optional[str], query: str, fallback: Optional[str] = None) -> str:
    clean_query = _normalize_excerpt_text(query)
    paragraphs = [
        _normalize_excerpt_text(part)
        for part in re.split(r"[\r\n]+", str(content or ""))
        if _normalize_excerpt_text(part)
    ]
    lowered_query = clean_query.lower()
    for paragraph in paragraphs:
        if lowered_query and lowered_query in paragraph.lower():
            return _truncate_excerpt_around_query(paragraph, clean_query)

    clean_content = _normalize_excerpt_text(content)
    if clean_content:
        return _truncate_excerpt_around_query(clean_content, clean_query)
    return _normalize_excerpt_text(fallback)


async def _build_conversation_match_excerpt_map(
    session: AsyncSession,
    conversation_ids: List[Any],
    query: str,
    fallback_map: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
) -> Dict[str, str]:
    normalized_ids = [cid for cid in conversation_ids if cid]
    clean_query = _normalize_excerpt_text(query)
    if not normalized_ids or not clean_query:
        return {}

    rows_result = await session.execute(
        select(
            Message.conversation_id,
            Message.content,
            Message.summary_snapshot,
            Message.created_at,
        )
        .where(
            Message.conversation_id.in_(normalized_ids),
            Message.content.ilike(f"%{clean_query}%"),
        )
        .order_by(Message.conversation_id.asc(), Message.created_at.desc())
    )

    excerpt_map: Dict[str, str] = {}
    for conversation_id, content, summary_snapshot, _ in rows_result.all():
        key = str(conversation_id)
        if key in excerpt_map:
            continue
        fallback = (fallback_map or {}).get(key, {}).get("summary") or summary_snapshot
        excerpt_map[key] = _build_match_excerpt(content, clean_query, fallback)
    return excerpt_map


def _conversation_public_access_clause(user_role: str):
    if not user_role:
        return None
    return and_(
        Conversation.visibility == "public",
        Conversation.owner_role.isnot(None),
        Conversation.owner_role == user_role,
    )


def _conversation_read_access_clause(user_id: int, identifier: str, user_role: str):
    clauses = [Conversation.user_id == user_id]

    public_clause = _conversation_public_access_clause(user_role)
    if public_clause is not None:
        clauses.append(public_clause)

    clauses.append(
        exists(
            select(ConversationInvitation.id).where(
                ConversationInvitation.conversation_id == Conversation.id,
                ConversationInvitation.status != "revoked",
                or_(
                    ConversationInvitation.invited_user_id == user_id,
                    and_(
                        ConversationInvitation.invited_email == identifier,
                        ConversationInvitation.invited_email != "",
                    ),
                ),
            )
        )
    )

    clauses.append(
        and_(
            Conversation.project_id.isnot(None),
            or_(
                Project.owner_user_id == user_id,
                Project.visibility == "public",
                exists(
                    select(ProjectInvitation.id).where(
                        ProjectInvitation.project_id == Project.id,
                        ProjectInvitation.status != "revoked",
                        or_(
                            ProjectInvitation.invited_user_id == user_id,
                            and_(
                                ProjectInvitation.invited_email == identifier,
                                ProjectInvitation.invited_email != "",
                            ),
                        ),
                    )
                ),
            ),
        )
    )

    return or_(*clauses)


async def can_read_conversation(
    session: AsyncSession,
    user: Dict[str, Any],
    conversation: Any,
) -> bool:
    if _is_sadmin(user):
        return True

    user_id, identifier = await ensure_authenticated_user(user)
    conversation_user_id = getattr(conversation, "user_id", None)
    if conversation_user_id is None and isinstance(conversation, dict):
        conversation_user_id = conversation.get("user_id")
    if conversation_user_id == user_id:
        return True

    visibility = getattr(conversation, "visibility", None)
    if visibility is None and isinstance(conversation, dict):
        visibility = conversation.get("visibility")
    owner_role = getattr(conversation, "owner_role", None)
    if owner_role is None and isinstance(conversation, dict):
        owner_role = conversation.get("owner_role")
    user_role = str((user or {}).get("role") or "").strip().lower()
    owner_role_value = str(owner_role or "").strip().lower()
    if user_role and (visibility or "").strip().lower() == "public" and owner_role_value == user_role:
        return True

    conversation_id = getattr(conversation, "id", None)
    if conversation_id is None and isinstance(conversation, dict):
        conversation_id = conversation.get("id")
    try:
        conversation_uuid = uuid.UUID(str(conversation_id))
    except (ValueError, TypeError, AttributeError):
        conversation_uuid = None
    if conversation_uuid is not None:
        invitation_result = await session.execute(
            select(ConversationInvitation.id)
            .where(
                ConversationInvitation.conversation_id == conversation_uuid,
                ConversationInvitation.status != "revoked",
                or_(
                    ConversationInvitation.invited_user_id == user_id,
                    and_(
                        ConversationInvitation.invited_email == identifier,
                        ConversationInvitation.invited_email != "",
                    ),
                ),
            )
            .limit(1)
        )
        if invitation_result.scalar_one_or_none() is not None:
            return True

    project_id = getattr(conversation, "project_id", None)
    if project_id is None and isinstance(conversation, dict):
        project_id = conversation.get("project_id")
    if project_id:
        project_result = await session.execute(
            select(Project).where(Project.id == project_id, Project.is_archived.is_(False))
        )
        project = project_result.scalar_one_or_none()
        if project and await can_read_project(session, user, project):
            return True

    return False


async def can_write_conversation(
    session: AsyncSession,
    user: Dict[str, Any],
    conversation: Any,
) -> bool:
    if _is_sadmin(user):
        return True
    user_id, identifier = await ensure_authenticated_user(user)
    conversation_user_id = getattr(conversation, "user_id", None)
    if conversation_user_id is None and isinstance(conversation, dict):
        conversation_user_id = conversation.get("user_id")
    if conversation_user_id == user_id:
        return True

    conversation_id = getattr(conversation, "id", None)
    if conversation_id is None and isinstance(conversation, dict):
        conversation_id = conversation.get("id")
    try:
        conversation_uuid = uuid.UUID(str(conversation_id))
    except (ValueError, TypeError, AttributeError):
        conversation_uuid = None
    if conversation_uuid is not None:
        invitation_result = await session.execute(
            select(ConversationInvitation.id)
            .where(
                ConversationInvitation.conversation_id == conversation_uuid,
                ConversationInvitation.status != "revoked",
                or_(
                    ConversationInvitation.invited_user_id == user_id,
                    and_(
                        ConversationInvitation.invited_email == identifier,
                        ConversationInvitation.invited_email != "",
                    ),
                ),
            )
            .limit(1)
        )
        if invitation_result.scalar_one_or_none() is not None:
            return True

    project_id = getattr(conversation, "project_id", None)
    if project_id is None and isinstance(conversation, dict):
        project_id = conversation.get("project_id")
    if project_id:
        project_result = await session.execute(
            select(Project).where(Project.id == project_id, Project.is_archived.is_(False))
        )
        project = project_result.scalar_one_or_none()
        if project and await can_read_project(session, user, project):
            return True
    return False


async def ensure_authenticated_user(user: Optional[Dict[str, Any]]) -> Tuple[int, str]:
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Login required")
    return int(user["id"]), _user_identifier(user)


async def can_read_project(session: AsyncSession, user: Dict[str, Any], project: Project) -> bool:
    if _is_sadmin(user):
        return True
    user_id, identifier = await ensure_authenticated_user(user)
    if project.owner_user_id == user_id:
        return True
    if _normalize_visibility(project.visibility) == "public":
        return True

    invitation_exists = await session.execute(
        select(ProjectInvitation.id)
        .where(
            ProjectInvitation.project_id == project.id,
            ProjectInvitation.status != "revoked",
            or_(
                ProjectInvitation.invited_user_id == user_id,
                and_(ProjectInvitation.invited_email == identifier, ProjectInvitation.invited_email != ""),
            ),
        )
        .limit(1)
    )
    return invitation_exists.scalar_one_or_none() is not None


async def can_manage_project(user: Dict[str, Any], project: Project) -> bool:
    user_id, _ = await ensure_authenticated_user(user)
    return project.owner_user_id == user_id


async def list_projects(
    session: AsyncSession,
    user: Dict[str, Any],
    q: Optional[str],
    page: int,
    page_size: int,
) -> Dict[str, Any]:
    user_id, identifier = await ensure_authenticated_user(user)

    filters = [Project.is_archived.is_(False)]
    if q:
        term = f"%{q.strip()}%"
        conversation_match_clause = exists(
            select(Conversation.id).where(
                Conversation.project_id == Project.id,
                Conversation.is_archived.is_(False),
                or_(
                    Conversation.title.ilike(term),
                    exists(
                        select(Message.id).where(
                            Message.conversation_id == Conversation.id,
                            Message.content.ilike(term),
                        )
                    ),
                ),
            )
        )
        filters.append(
            or_(
                Project.name.ilike(term),
                conversation_match_clause,
            )
        )

    access_clause = or_(
        Project.owner_user_id == user_id,
        Project.visibility == "public",
                exists(
                    select(ProjectInvitation.id).where(
                        ProjectInvitation.project_id == Project.id,
                        ProjectInvitation.status != "revoked",
                        or_(
                    ProjectInvitation.invited_user_id == user_id,
                    and_(ProjectInvitation.invited_email == identifier, ProjectInvitation.invited_email != ""),
                ),
            )
        ),
    )

    if _is_sadmin(user):
        where_clause = and_(*filters)
    else:
        where_clause = and_(access_clause, *filters)

    total_result = await session.execute(select(func.count(Project.id)).where(where_clause))
    total = int(total_result.scalar() or 0)

    offset = (page - 1) * page_size
    projects_result = await session.execute(
        select(Project, User.username)
        .outerjoin(User, User.id == Project.owner_user_id)
        .where(where_clause)
        .order_by(desc(Project.updated_at), desc(Project.created_at))
        .offset(offset)
        .limit(page_size)
    )
    rows = projects_result.all()

    project_ids = [project.id for project, _ in rows]
    counts: Dict[str, int] = {}
    if project_ids:
        count_result = await session.execute(
            select(Conversation.project_id, func.count(Conversation.id))
            .where(
                Conversation.project_id.in_(project_ids),
                Conversation.is_archived.is_(False),
            )
            .group_by(Conversation.project_id)
        )
        counts = {pid: int(cnt or 0) for pid, cnt in count_result.all()}

    items = []
    for project, owner_name in rows:
        items.append(
            {
                "id": project.id,
                "name": project.name,
                "visibility": project.visibility,
                "owner_user_id": project.owner_user_id,
                "owner": owner_name or "-",
                "conversation_count": counts.get(project.id, 0),
                "updated_at": project.updated_at.isoformat() if project.updated_at else None,
                "created_at": project.created_at.isoformat() if project.created_at else None,
                "customer_profile": {
                    "customer_type": project.customer_type,
                    "trade_count": project.trade_count,
                    "last_trade_at": project.last_trade_at.isoformat() if project.last_trade_at else None,
                    "avg_unit_price": project.avg_unit_price,
                    "preference_note": project.preference_note,
                    "region": project.region,
                },
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def create_project(
    session: AsyncSession,
    user: Dict[str, Any],
    payload: Dict[str, Any],
) -> Project:
    user_id, _ = await ensure_authenticated_user(user)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")

    requested_visibility = payload.get("visibility")
    default_visibility = user.get("conversation_visibility_default") or "private"
    visibility = _normalize_visibility(
        requested_visibility if requested_visibility is not None else default_visibility
    )
    profile = payload.get("customer_profile") or {}

    project = Project(
        id=str(payload.get("id") or f"proj-{uuid.uuid4().hex[:12]}"),
        owner_user_id=user_id,
        name=name,
        visibility=visibility,
        customer_type=profile.get("customer_type"),
        trade_count=profile.get("trade_count"),
        last_trade_at=_coerce_datetime(profile.get("last_trade_at")),
        avg_unit_price=profile.get("avg_unit_price"),
        preference_note=profile.get("preference_note"),
        region=profile.get("region"),
    )

    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def get_project_or_404(session: AsyncSession, project_id: str) -> Project:
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.is_archived.is_(False))
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def update_project(
    session: AsyncSession,
    user: Dict[str, Any],
    project: Project,
    payload: Dict[str, Any],
) -> Project:
    if not await can_manage_project(user, project):
        raise HTTPException(status_code=403, detail="Permission denied")

    name = payload.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            raise HTTPException(status_code=400, detail="Project name is required")
        project.name = name

    if payload.get("visibility") is not None:
        project.visibility = _normalize_visibility(payload.get("visibility"))

    profile = payload.get("customer_profile") or {}
    if "customer_type" in profile:
        project.customer_type = profile.get("customer_type")
    if "trade_count" in profile:
        project.trade_count = profile.get("trade_count")
    if "last_trade_at" in profile:
        project.last_trade_at = _coerce_datetime(profile.get("last_trade_at"))
    if "avg_unit_price" in profile:
        project.avg_unit_price = profile.get("avg_unit_price")
    if "preference_note" in profile:
        project.preference_note = profile.get("preference_note")
    if "region" in profile:
        project.region = profile.get("region")
    project.updated_at = func.now()
    await session.commit()
    await session.refresh(project)

    if name is not None:
        await session.execute(
            Conversation.__table__.update()
            .where(Conversation.project_id == project.id)
            .values(project_label=project.name, updated_at=func.now())
        )
        await session.commit()

    return project


async def archive_project_and_conversations(
    session: AsyncSession,
    user: Dict[str, Any],
    project: Project,
) -> None:
    if not await can_manage_project(user, project):
        raise HTTPException(status_code=403, detail="Permission denied")

    project.is_archived = True
    project.updated_at = func.now()
    await session.execute(
        Conversation.__table__.update()
        .where(Conversation.project_id == project.id)
        .values(is_archived=True, archived_at=func.now(), archived_by=user.get("id"), archived_role=user.get("role"), updated_at=func.now())
    )
    await session.commit()


async def list_project_conversations(
    session: AsyncSession,
    user: Dict[str, Any],
    project: Project,
    q: Optional[str],
    page: int,
    page_size: int,
) -> Dict[str, Any]:
    if not await can_read_project(session, user, project):
        raise HTTPException(status_code=403, detail="Permission denied")

    filters = [
        Conversation.project_id == project.id,
        Conversation.is_archived.is_(False),
    ]

    if q:
        term = f"%{q.strip()}%"
        filters.append(
            or_(
                Conversation.title.ilike(term),
                exists(
                    select(Message.id).where(
                        Message.conversation_id == Conversation.id,
                        Message.content.ilike(term),
                    )
                ),
            )
        )

    where_clause = and_(*filters)
    total_result = await session.execute(
        select(func.count(func.distinct(Conversation.id)))
        .select_from(Conversation)
        .outerjoin(Project, Project.id == Conversation.project_id)
        .where(where_clause)
    )
    total = int(total_result.scalar() or 0)

    offset = (page - 1) * page_size
    rows_result = await session.execute(
        select(Conversation, User.username)
        .outerjoin(User, User.id == Conversation.user_id)
        .where(where_clause)
        .order_by(desc(Conversation.updated_at), desc(Conversation.created_at))
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_result.all()
    preview_map = await _build_conversation_preview_map(
        session, [conversation.id for conversation, _ in rows if conversation.id]
    )

    items = []
    for conversation, owner_name in rows:
        preview = preview_map.get(str(conversation.id), {})
        title = conversation.title or ""
        items.append(
            {
                "id": str(conversation.id),
                "project_id": conversation.project_id,
                "project_label": conversation.project_label,
                "title": title,
                "has_custom_title": _has_custom_title(title),
                "last_user_message": preview.get("last_user_message"),
                "summary": preview.get("summary"),
                "visibility": conversation.visibility,
                "owner": owner_name or "-",
                "owner_user_id": conversation.user_id,
                "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
                "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
                "customer_id": str(conversation.customer_id) if conversation.customer_id else None,
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def search_conversations_global(
    session: AsyncSession,
    user: Dict[str, Any],
    q: Optional[str],
    page: int,
    page_size: int,
    scope: str = "all",
) -> Dict[str, Any]:
    user_id, identifier = await ensure_authenticated_user(user)
    normalized_scope = str(scope or "all").strip().lower()
    if normalized_scope not in {"all", "inbox"}:
        normalized_scope = "all"
    normalized_q = (q or "").strip()
    if normalized_scope != "inbox" and not normalized_q:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    if normalized_scope == "inbox":
        inbox_filters = [
            Conversation.is_archived.is_(False),
            Conversation.project_id.is_(None),
            Conversation.user_id == user_id,
        ]
        if normalized_q:
            term = f"%{normalized_q}%"
            inbox_filters.append(
                or_(
                    Conversation.title.ilike(term),
                    exists(
                        select(Message.id).where(
                            Message.conversation_id == Conversation.id,
                            Message.content.ilike(term),
                        )
                    ),
                )
            )
        inbox_where_clause = and_(*inbox_filters)
        total_result = await session.execute(select(func.count(Conversation.id)).where(inbox_where_clause))
        total = int(total_result.scalar() or 0)
        offset = (page - 1) * page_size
        rows_result = await session.execute(
            select(Conversation, User.username)
            .outerjoin(User, User.id == Conversation.user_id)
            .where(inbox_where_clause)
            .order_by(desc(Conversation.updated_at), desc(Conversation.created_at))
            .offset(offset)
            .limit(page_size)
        )
        rows = rows_result.all()
        preview_map = await _build_conversation_preview_map(
            session, [conversation.id for conversation, _ in rows if conversation.id]
        )
        excerpt_map = await _build_conversation_match_excerpt_map(
            session,
            [conversation.id for conversation, _ in rows if conversation.id],
            normalized_q,
            preview_map,
        )
        lowered_q = normalized_q.lower()
        items = []
        for conversation, owner_name in rows:
            title = conversation.title or ""
            preview = preview_map.get(str(conversation.id), {})
            title_lower = title.lower()
            if lowered_q and lowered_q in title_lower:
                matched_by = "title"
            elif lowered_q:
                matched_by = "content"
            else:
                matched_by = "inbox"
            match_excerpt = None
            if normalized_q:
                match_excerpt = title if matched_by == "title" else excerpt_map.get(str(conversation.id))
            items.append(
                {
                    "id": str(conversation.id),
                    "project_id": conversation.project_id,
                    "project_name": None,
                    "project_label": conversation.project_label or "",
                    "title": title,
                    "has_custom_title": _has_custom_title(title),
                    "last_user_message": preview.get("last_user_message"),
                    "summary": preview.get("summary"),
                    "visibility": conversation.visibility,
                    "owner": owner_name or "-",
                    "owner_user_id": conversation.user_id,
                    "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
                    "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
                    "customer_id": str(conversation.customer_id) if conversation.customer_id else None,
                    "matched_by": matched_by,
                    "match_excerpt": match_excerpt,
                }
            )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    term = f"%{normalized_q}%"
    search_clause = or_(
        exists(
            select(Message.id).where(
                Message.conversation_id == Conversation.id,
                Message.content.ilike(term),
            )
        ),
        Conversation.title.ilike(term),
    )
    access_clause = _conversation_read_access_clause(
        user_id,
        identifier,
        str((user or {}).get("role") or "").strip().lower(),
    )

    filters = [
        Conversation.is_archived.is_(False),
        or_(Conversation.project_id.is_(None), Project.is_archived.is_(False)),
        search_clause,
    ]
    if not _is_sadmin(user):
        filters.append(access_clause)
    where_clause = and_(*filters)

    total_result = await session.execute(
        select(func.count(func.distinct(Conversation.id)))
        .select_from(Conversation)
        .outerjoin(Project, Project.id == Conversation.project_id)
        .where(where_clause)
    )
    total = int(total_result.scalar() or 0)

    offset = (page - 1) * page_size
    rows_result = await session.execute(
        select(Conversation, Project.name, User.username)
        .outerjoin(Project, Project.id == Conversation.project_id)
        .outerjoin(User, User.id == Conversation.user_id)
        .where(where_clause)
        .order_by(desc(Conversation.updated_at), desc(Conversation.created_at))
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_result.all()
    preview_map = await _build_conversation_preview_map(
        session, [conversation.id for conversation, _, _ in rows if conversation.id]
    )
    excerpt_map = await _build_conversation_match_excerpt_map(
        session,
        [conversation.id for conversation, _, _ in rows if conversation.id],
        normalized_q,
        preview_map,
    )

    lowered_q = normalized_q.lower()
    items = []
    for conversation, project_name, owner_name in rows:
        title = conversation.title or ""
        preview = preview_map.get(str(conversation.id), {})
        project_label = project_name or conversation.project_label or ""
        title_lower = title.lower()
        if lowered_q and lowered_q in title_lower:
            matched_by = "title"
        else:
            matched_by = "content"
        match_excerpt = title if matched_by == "title" else excerpt_map.get(str(conversation.id))

        items.append(
            {
                "id": str(conversation.id),
                "project_id": conversation.project_id,
                "project_name": project_label,
                "project_label": project_label,
                "title": title,
                "has_custom_title": _has_custom_title(title),
                "last_user_message": preview.get("last_user_message"),
                "summary": preview.get("summary"),
                "visibility": conversation.visibility,
                "owner": owner_name or "-",
                "owner_user_id": conversation.user_id,
                "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
                "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
                "customer_id": str(conversation.customer_id) if conversation.customer_id else None,
                "matched_by": matched_by,
                "match_excerpt": match_excerpt,
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _get_conversation_or_404(session: AsyncSession, conversation_id: str) -> Conversation:
    try:
        conv_uuid = uuid.UUID(str(conversation_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation_id") from exc

    result = await session.execute(
        select(Conversation).where(Conversation.id == conv_uuid, Conversation.is_archived.is_(False))
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


async def _can_manage_conversation(session: AsyncSession, user: Dict[str, Any], conversation: Conversation) -> bool:
    user_id, _ = await ensure_authenticated_user(user)
    return conversation.user_id == user_id


async def search_invitable_users(
    session: AsyncSession,
    user: Dict[str, Any],
    keyword: str,
    scope: str,
    target_id: str,
    *,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    user_id, _ = await ensure_authenticated_user(user)
    normalized_scope = str(scope or "").strip().lower()
    normalized_keyword = (keyword or "").strip().lower()
    if len(normalized_keyword) < 2:
        return []
    if normalized_scope not in {"project", "conversation"}:
        raise HTTPException(status_code=400, detail="Invalid invitation scope")
    if not str(target_id or "").strip():
        raise HTTPException(status_code=400, detail="Target id is required")

    excluded_user_ids = {user_id}
    excluded_usernames: set[str] = set()

    if normalized_scope == "project":
        project = await get_project_or_404(session, target_id)
        if not await can_manage_project(user, project):
            raise HTTPException(status_code=403, detail="Permission denied")
        invitation_rows = await session.execute(
            select(ProjectInvitation.invited_user_id, ProjectInvitation.invited_email).where(
                ProjectInvitation.project_id == project.id,
                ProjectInvitation.status != "revoked",
            )
        )
    else:
        conversation = await _get_conversation_or_404(session, target_id)
        if not await _can_manage_conversation(session, user, conversation):
            raise HTTPException(status_code=403, detail="Permission denied")
        invitation_rows = await session.execute(
            select(ConversationInvitation.invited_user_id, ConversationInvitation.invited_email).where(
                ConversationInvitation.conversation_id == conversation.id,
                ConversationInvitation.status != "revoked",
            )
        )

    for invited_user_id, invited_email in invitation_rows.all():
        if invited_user_id:
            excluded_user_ids.add(int(invited_user_id))
        normalized_email = str(invited_email or "").strip().lower()
        if normalized_email:
            excluded_usernames.add(normalized_email)

    result = await session.execute(
        select(User.id, User.username, User.name)
        .where(
            func.lower(User.username).like(f"%{normalized_keyword}%"),
            User.id.notin_(excluded_user_ids),
        )
        .order_by(func.lower(User.username).asc())
        .limit(max(1, min(limit, 20)))
    )

    items: List[Dict[str, Any]] = []
    for item_id, username, name in result.all():
        normalized_username = str(username or "").strip().lower()
        if not normalized_username or normalized_username in excluded_usernames:
            continue
        items.append(
            {
                "id": int(item_id),
                "username": username,
                "label": name or username,
            }
        )
    return items


async def create_project_invitation(
    session: AsyncSession,
    user: Dict[str, Any],
    project: Project,
    identifier: str,
) -> ProjectInvitation:
    if not await can_manage_project(user, project):
        raise HTTPException(status_code=403, detail="Permission denied")
    if _normalize_visibility(project.visibility) != "private":
        raise HTTPException(status_code=400, detail="Invitations are only available for private projects")

    normalized_identifier = _normalize_invite_identifier(identifier)
    invited_user = await _resolve_user_by_identifier(session, normalized_identifier)
    if not invited_user:
        raise HTTPException(status_code=400, detail="Selected account does not exist")

    user_id, _ = await ensure_authenticated_user(user)
    if int(invited_user.id) == user_id:
        raise HTTPException(status_code=400, detail="You cannot invite yourself")

    existing_pending = await session.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.project_id == project.id,
            or_(
                ProjectInvitation.invited_user_id == invited_user.id,
                func.lower(ProjectInvitation.invited_email) == normalized_identifier,
            ),
            ProjectInvitation.status != "revoked",
        )
    )
    invitation = existing_pending.scalar_one_or_none()
    if invitation:
        invitation.invited_email = invited_user.username
        invitation.invited_user_id = invited_user.id
        invitation.status = "accepted"
        invitation.responded_at = invitation.responded_at or _now()
        invitation.updated_at = func.now()
        await session.commit()
        await session.refresh(invitation)
        return invitation

    invitation = ProjectInvitation(
        project_id=project.id,
        invited_email=invited_user.username,
        invited_user_id=invited_user.id,
        invited_by_user_id=user_id,
        status="accepted",
        responded_at=_now(),
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)
    return invitation


async def list_project_invitations(
    session: AsyncSession,
    user: Dict[str, Any],
    project: Project,
) -> List[Dict[str, Any]]:
    if not await can_manage_project(user, project):
        raise HTTPException(status_code=403, detail="Permission denied")

    result = await session.execute(
        select(ProjectInvitation, User.username, User.name)
        .outerjoin(User, User.id == ProjectInvitation.invited_user_id)
        .where(ProjectInvitation.project_id == project.id)
        .order_by(desc(ProjectInvitation.created_at))
    )
    items = []
    for item, username, name in result.all():
        if not _is_active_share_status(item.status):
            continue
        items.append(
            {
                "id": str(item.id),
                "email": item.invited_email,
                "username": username or item.invited_email,
                "name": name or username or item.invited_email,
                "status": _display_share_status(item.status),
                "invited_user_id": item.invited_user_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "responded_at": item.responded_at.isoformat() if item.responded_at else None,
            }
        )
    return items


async def revoke_project_invitation(
    session: AsyncSession,
    user: Dict[str, Any],
    project: Project,
    invitation_id: str,
) -> None:
    if not await can_manage_project(user, project):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        invitation_uuid = uuid.UUID(str(invitation_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid invitation id") from exc

    result = await session.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.id == invitation_uuid,
            ProjectInvitation.project_id == project.id,
        )
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    invitation.status = "revoked"
    invitation.responded_at = _now()
    invitation.updated_at = func.now()
    await session.commit()


async def create_conversation_invitation(
    session: AsyncSession,
    user: Dict[str, Any],
    conversation_id: str,
    identifier: str,
) -> ConversationInvitation:
    conversation = await _get_conversation_or_404(session, conversation_id)
    if not await _can_manage_conversation(session, user, conversation):
        raise HTTPException(status_code=403, detail="Permission denied")
    if _normalize_visibility(conversation.visibility) != "private":
        raise HTTPException(status_code=400, detail="Invitations are only available for private conversations")

    normalized_identifier = _normalize_invite_identifier(identifier)
    invited_user = await _resolve_user_by_identifier(session, normalized_identifier)
    if not invited_user:
        raise HTTPException(status_code=400, detail="Selected account does not exist")

    user_id, _ = await ensure_authenticated_user(user)
    if int(invited_user.id) == user_id:
        raise HTTPException(status_code=400, detail="You cannot invite yourself")

    existing_pending = await session.execute(
        select(ConversationInvitation).where(
            ConversationInvitation.conversation_id == conversation.id,
            or_(
                ConversationInvitation.invited_user_id == invited_user.id,
                func.lower(ConversationInvitation.invited_email) == normalized_identifier,
            ),
            ConversationInvitation.status != "revoked",
        )
    )
    invitation = existing_pending.scalar_one_or_none()
    if invitation:
        invitation.invited_email = invited_user.username
        invitation.invited_user_id = invited_user.id
        invitation.status = "accepted"
        invitation.responded_at = invitation.responded_at or _now()
        invitation.updated_at = func.now()
        await session.commit()
        await session.refresh(invitation)
        return invitation

    invitation = ConversationInvitation(
        conversation_id=conversation.id,
        invited_email=invited_user.username,
        invited_user_id=invited_user.id,
        invited_by_user_id=user_id,
        status="accepted",
        responded_at=_now(),
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)
    return invitation


async def revoke_conversation_invitation(
    session: AsyncSession,
    user: Dict[str, Any],
    conversation_id: str,
    invitation_id: str,
) -> None:
    conversation = await _get_conversation_or_404(session, conversation_id)
    if not await _can_manage_conversation(session, user, conversation):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        invitation_uuid = uuid.UUID(str(invitation_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid invitation id") from exc

    result = await session.execute(
        select(ConversationInvitation).where(
            ConversationInvitation.id == invitation_uuid,
            ConversationInvitation.conversation_id == conversation.id,
        )
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    invitation.status = "revoked"
    invitation.responded_at = _now()
    invitation.updated_at = func.now()
    await session.commit()


async def list_conversation_invitations(
    session: AsyncSession,
    user: Dict[str, Any],
    conversation_id: str,
) -> List[Dict[str, Any]]:
    conversation = await _get_conversation_or_404(session, conversation_id)
    if not await _can_manage_conversation(session, user, conversation):
        raise HTTPException(status_code=403, detail="Permission denied")

    result = await session.execute(
        select(ConversationInvitation, User.username, User.name)
        .outerjoin(User, User.id == ConversationInvitation.invited_user_id)
        .where(ConversationInvitation.conversation_id == conversation.id)
        .order_by(desc(ConversationInvitation.created_at))
    )
    items = []
    for item, username, name in result.all():
        if not _is_active_share_status(item.status):
            continue
        items.append(
            {
                "id": str(item.id),
                "email": item.invited_email,
                "username": username or item.invited_email,
                "name": name or username or item.invited_email,
                "status": _display_share_status(item.status),
                "invited_user_id": item.invited_user_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "responded_at": item.responded_at.isoformat() if item.responded_at else None,
            }
        )
    return items


async def list_pending_invitations(
    session: AsyncSession,
    user: Dict[str, Any],
) -> List[Dict[str, Any]]:
    user_id, identifier = await ensure_authenticated_user(user)

    project_rows = await session.execute(
        select(ProjectInvitation, Project.name)
        .join(Project, Project.id == ProjectInvitation.project_id)
        .where(
            ProjectInvitation.status == "pending",
            or_(
                ProjectInvitation.invited_user_id == user_id,
                and_(ProjectInvitation.invited_email == identifier, ProjectInvitation.invited_email != ""),
            ),
            Project.is_archived.is_(False),
        )
        .order_by(desc(ProjectInvitation.created_at))
    )

    conversation_rows = await session.execute(
        select(ConversationInvitation, Conversation.title, Conversation.project_id)
        .join(Conversation, Conversation.id == ConversationInvitation.conversation_id)
        .where(
            ConversationInvitation.status == "pending",
            or_(
                ConversationInvitation.invited_user_id == user_id,
                and_(ConversationInvitation.invited_email == identifier, ConversationInvitation.invited_email != ""),
            ),
            Conversation.is_archived.is_(False),
        )
        .order_by(desc(ConversationInvitation.created_at))
    )

    items: List[Dict[str, Any]] = []
    for invitation, project_name in project_rows.all():
        items.append(
            {
                "id": str(invitation.id),
                "scope": "project",
                "target_id": invitation.project_id,
                "target_name": project_name,
                "email": invitation.invited_email,
                "status": invitation.status,
                "created_at": invitation.created_at.isoformat() if invitation.created_at else None,
            }
        )

    for invitation, conversation_title, project_id in conversation_rows.all():
        items.append(
            {
                "id": str(invitation.id),
                "scope": "conversation",
                "target_id": str(invitation.conversation_id),
                "project_id": project_id,
                "target_name": conversation_title,
                "email": invitation.invited_email,
                "status": invitation.status,
                "created_at": invitation.created_at.isoformat() if invitation.created_at else None,
            }
        )

    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return items


async def respond_invitation(
    session: AsyncSession,
    user: Dict[str, Any],
    invitation_id: str,
    status: str,
) -> Dict[str, Any]:
    if status not in {"accepted", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    user_id, identifier = await ensure_authenticated_user(user)
    try:
        invitation_uuid = uuid.UUID(str(invitation_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid invitation id") from exc

    project_result = await session.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.id == invitation_uuid,
            ProjectInvitation.status == "pending",
            or_(
                ProjectInvitation.invited_user_id == user_id,
                and_(ProjectInvitation.invited_email == identifier, ProjectInvitation.invited_email != ""),
            ),
        )
    )
    project_invitation = project_result.scalar_one_or_none()
    if project_invitation:
        project_invitation.status = status
        project_invitation.responded_at = _now()
        project_invitation.updated_at = func.now()
        if not project_invitation.invited_user_id:
            project_invitation.invited_user_id = user_id
        await session.commit()
        return {"scope": "project", "status": status}

    conversation_result = await session.execute(
        select(ConversationInvitation).where(
            ConversationInvitation.id == invitation_uuid,
            ConversationInvitation.status == "pending",
            or_(
                ConversationInvitation.invited_user_id == user_id,
                and_(ConversationInvitation.invited_email == identifier, ConversationInvitation.invited_email != ""),
            ),
        )
    )
    conversation_invitation = conversation_result.scalar_one_or_none()
    if conversation_invitation:
        conversation_invitation.status = status
        conversation_invitation.responded_at = _now()
        conversation_invitation.updated_at = func.now()
        if not conversation_invitation.invited_user_id:
            conversation_invitation.invited_user_id = user_id
        await session.commit()
        return {"scope": "conversation", "status": status}

    raise HTTPException(status_code=404, detail="Invitation not found")


async def resolve_project_name_map(session: AsyncSession, project_ids: List[str]) -> Dict[str, str]:
    normalized_ids = [pid for pid in project_ids if pid]
    if not normalized_ids:
        return {}
    result = await session.execute(
        select(Project.id, Project.name)
        .where(Project.id.in_(normalized_ids), Project.is_archived.is_(False))
    )
    return {pid: name for pid, name in result.all() if pid and name}
