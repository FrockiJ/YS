import json
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import and_, desc, func, or_, select

from ..core.database import get_async_session
from ..models.customer import Customer
from ..models.project import ConversationInvitation, Project, ProjectInvitation
from .models import Conversation, Message, Role, User


def _is_super_admin(role: Optional[str]) -> bool:
    if not role:
        return False
    return role.strip().lower() == "sadmin"


def _has_custom_title(title: Optional[str]) -> bool:
    normalized = (title or "").strip()
    if not normalized:
        return False
    return normalized.lower() not in {"new conversation", "?啣?閰?"}


def _normalize_message_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def get_messages_by_conversation(
    conversation_id: uuid.UUID,
    include_metadata: bool = False,
) -> List[dict]:
    async with get_async_session() as session:
        conversation_result = await session.execute(
            select(Conversation.user_id, User.username, User.name)
            .outerjoin(User, User.id == Conversation.user_id)
            .where(Conversation.id == conversation_id)
        )
        conversation_row = conversation_result.first()
        owner_user_id = conversation_row[0] if conversation_row else None
        owner_username = conversation_row[1] if conversation_row else None
        owner_name = conversation_row[2] if conversation_row else None

        result = await session.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
        )
        messages = result.scalars().all()
        history: List[Dict[str, Any]] = []
        for msg in messages:
            metadata = _normalize_message_metadata(msg.message_metadata)
            if str(msg.role or "").strip().lower() == "user":
                metadata.setdefault("author_user_id", owner_user_id)
                metadata.setdefault("author_username", owner_username)
                metadata.setdefault("author_name", owner_name or owner_username)
            payload: Dict[str, Any] = {
                "id": str(msg.id) if msg.id else None,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "metadata": metadata,
            }
            if str(msg.role or "").strip().lower() == "user":
                payload["author_user_id"] = metadata.get("author_user_id")
                payload["author_username"] = metadata.get("author_username")
                payload["author_name"] = metadata.get("author_name")
            if include_metadata:
                payload["summary"] = msg.summary_snapshot
                payload["summary_snapshot"] = msg.summary_snapshot
                highlights = msg.highlights if isinstance(msg.highlights, list) else None
                payload["highlights"] = highlights or []
            history.append(payload)
        return history


async def get_conversation_meta(conversation_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return None
        customer_payload = None
        if conversation.customer:
            customer_payload = {
                "id": conversation.customer.id,
                "name": conversation.customer.name,
                "email": conversation.customer.email,
                "phone": conversation.customer.phone,
                "cerp_id": conversation.customer.cerp_id,
                "tags": conversation.customer.tags,
            }
        return {
            "id": str(conversation.id) if conversation.id else None,
            "user_id": conversation.user_id,
            "customer_id": conversation.customer_id,
            "customer": customer_payload,
            "project_id": conversation.project_id,
            "project_label": conversation.project_label,
            "title": conversation.title,
            "has_custom_title": _has_custom_title(conversation.title),
            "visibility": conversation.visibility,
            "owner_role": conversation.owner_role,
            "is_archived": conversation.is_archived,
            "archived_at": conversation.archived_at.isoformat() if conversation.archived_at else None,
            "archived_by": conversation.archived_by,
            "archived_role": conversation.archived_role,
            "context_state": conversation.context_state if isinstance(conversation.context_state, dict) else {},
            "context_version": conversation.context_version or "outdoor-v1",
            "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
            "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        }


async def get_message_in_conversation(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    async with get_async_session() as session:
        result = await session.execute(
            select(Message).where(
                and_(
                    Message.id == message_id,
                    Message.conversation_id == conversation_id,
                )
            )
        )
        message = result.scalars().first()
        if not message:
            return None
        return {
            "id": str(message.id),
            "conversation_id": str(message.conversation_id),
            "role": message.role,
            "content": message.content,
            "metadata": _normalize_message_metadata(message.message_metadata),
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }


async def find_product_bridge_response(
    conversation_id: uuid.UUID,
    source_message_id: uuid.UUID,
) -> Optional[Dict[str, Any]]:
    """Find a persisted ERP response for idempotent product-bridge requests."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Message)
            .where(
                and_(
                    Message.conversation_id == conversation_id,
                    Message.role == "assistant",
                )
            )
            .order_by(desc(Message.created_at))
        )
        for message in result.scalars().all():
            metadata = _normalize_message_metadata(message.message_metadata)
            bridge = metadata.get("product_bridge")
            if not isinstance(bridge, dict):
                continue
            if str(bridge.get("source_message_id") or "") != str(source_message_id):
                continue
            if not bridge.get("fulfilled"):
                continue
            return {
                "id": str(message.id),
                "conversation_id": str(message.conversation_id),
                "role": message.role,
                "content": message.content,
                "metadata": metadata,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
    return None


async def update_conversation_context_state(
    conversation_id: uuid.UUID,
    context_state: Dict[str, Any],
    *,
    context_version: str = "outdoor-v1",
) -> bool:
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return False
        conversation.context_state = dict(context_state or {})
        conversation.context_version = context_version
        conversation.updated_at = func.now()
        await session.commit()
        return True


async def merge_conversation_context_state(
    conversation_id: uuid.UUID,
    updates: Dict[str, Any],
    *,
    context_version: str = "outdoor-v1",
) -> bool:
    """Merge top-level context keys without discarding unrelated saved state."""
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return False
        existing = conversation.context_state if isinstance(conversation.context_state, dict) else {}
        conversation.context_state = {**existing, **dict(updates or {})}
        conversation.context_version = context_version
        conversation.updated_at = func.now()
        await session.commit()
        return True


async def add_message_to_conversation(
    conversation_id: Optional[uuid.UUID],
    role: str,
    content: str,
    user_id: Optional[int] = None,
    project_id: Optional[str] = None,
    project_label: Optional[str] = None,
    summary_snapshot: Optional[str] = None,
    highlights: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    return_message_id: bool = False,
    owner_role: Optional[str] = None,
) -> Union[uuid.UUID, Tuple[uuid.UUID, uuid.UUID]]:
    async with get_async_session() as session:
        conversation = None
        if conversation_id:
            result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
            conversation = result.scalars().first()

        resolved_owner_role = owner_role
        resolved_visibility = None
        if not resolved_owner_role and user_id:
            user_role_result = await session.execute(select(User.role).where(User.id == user_id))
            resolved_owner_role = user_role_result.scalar_one_or_none()
        if resolved_owner_role:
            role_result = await session.execute(
                select(Role.conversation_visibility_default).where(Role.name == resolved_owner_role)
            )
            resolved_visibility = role_result.scalar_one_or_none()

        if conversation is None:
            new_id = conversation_id or uuid.uuid4()
            conversation = Conversation(
                id=new_id,
                user_id=user_id,
                project_id=project_id,
                project_label=project_label,
                owner_role=resolved_owner_role,
                visibility=(resolved_visibility or "private"),
            )
            session.add(conversation)
        elif user_id and conversation.user_id is None:
            conversation.user_id = user_id
        if project_id and not conversation.project_id:
            conversation.project_id = project_id
        if project_label and not conversation.project_label:
            conversation.project_label = project_label
        if not conversation.owner_role and resolved_owner_role:
            conversation.owner_role = resolved_owner_role
        if not conversation.visibility:
            conversation.visibility = resolved_visibility or "private"

        conv_id = conversation.id or uuid.uuid4()
        if conversation.id is None:
            conversation.id = conv_id

        message_metadata = dict(metadata or {})
        if str(role or "").strip().lower() == "user" and user_id:
            author_result = await session.execute(
                select(User.username, User.name).where(User.id == user_id)
            )
            author_row = author_result.first()
            author_username = author_row[0] if author_row else None
            author_name = author_row[1] if author_row else None
            message_metadata.update(
                {
                    "author_user_id": user_id,
                    "author_username": author_username,
                    "author_name": author_name or author_username,
                }
            )

        new_message = Message(
            conversation_id=conv_id,
            role=role,
            content=content,
            summary_snapshot=summary_snapshot,
            highlights=highlights,
            message_metadata=message_metadata or None,
        )
        session.add(new_message)
        conversation.updated_at = func.now()
        await session.commit()
        if return_message_id:
            return conv_id, new_message.id
        return conv_id


async def update_message_enrichment(
    message_id: Optional[Union[str, uuid.UUID]],
    *,
    highlights: Optional[List[str]] = None,
    summary_snapshot: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    if not message_id:
        return
    try:
        normalized_id = uuid.UUID(str(message_id))
    except (ValueError, TypeError, AttributeError):
        return
    async with get_async_session() as session:
        result = await session.execute(select(Message).where(Message.id == normalized_id))
        message = result.scalars().first()
        if not message:
            return
        if highlights is not None:
            message.highlights = highlights or None
        if summary_snapshot is not None:
            message.summary_snapshot = summary_snapshot or None
        if metadata is not None:
            message.message_metadata = metadata or None
        await session.commit()


async def update_conversation_label(conversation_id: uuid.UUID, label: str) -> bool:
    normalized_label = (label or "").strip()
    if not normalized_label:
        return False
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return False
        conversation.title = normalized_label
        conversation.updated_at = func.now()
        await session.commit()
        return True


async def update_conversation_customer(
    conversation_id: uuid.UUID,
    customer_id: Optional[str],
) -> bool:
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return False
        normalized_id = None
        if customer_id:
            try:
                normalized_id = uuid.UUID(str(customer_id))
            except (ValueError, TypeError):
                return False
            customer_result = await session.execute(select(Customer).where(Customer.id == normalized_id))
            if not customer_result.scalars().first():
                return False
        conversation.customer_id = normalized_id
        conversation.updated_at = func.now()
        await session.commit()
        return True


async def update_conversation_visibility(
    conversation_id: uuid.UUID,
    visibility: str,
    *,
    owner_role: Optional[str] = None,
) -> bool:
    normalized = (visibility or "").strip().lower()
    if normalized not in {"private", "public"}:
        return False
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return False
        conversation.visibility = normalized
        if owner_role and not conversation.owner_role:
            conversation.owner_role = owner_role
        conversation.updated_at = func.now()
        await session.commit()
        return True


async def update_conversation_project(
    conversation_id: uuid.UUID,
    project_id: Optional[str],
    project_label: Optional[str] = None,
) -> bool:
    normalized_project_id = (project_id or "").strip() or None
    normalized_project_label = (project_label or "").strip() or None
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return False
        conversation.project_id = normalized_project_id
        conversation.project_label = normalized_project_label if normalized_project_id else None
        conversation.updated_at = func.now()
        await session.commit()
        return True


async def find_conversation_by_project(
    user_id: Optional[int],
    project_id: Optional[str],
) -> Optional[uuid.UUID]:
    if not user_id or not project_id:
        return None
    async with get_async_session() as session:
        result = await session.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.project_id == project_id,
                Conversation.is_archived.is_(False),
            )
            .order_by(desc(Conversation.updated_at), desc(Conversation.created_at))
            .limit(1)
        )
        conversation = result.scalars().first()
        return conversation.id if conversation else None


async def list_conversations_by_user(
    user_id: Optional[int],
    user_role: Optional[str],
    limit: int = 50,
) -> List[dict]:
    if not user_id:
        return []
    safe_limit = max(1, min(limit, 200))
    async with get_async_session() as session:
        user_result = await session.execute(select(User.username).where(User.id == user_id))
        identifier = str(user_result.scalar_one_or_none() or "").strip().lower()
        filters = [Conversation.user_id == user_id]
        if user_role:
            filters.append(
                and_(
                    Conversation.visibility == "public",
                    Conversation.owner_role.isnot(None),
                    Conversation.owner_role == user_role,
                )
            )
        filters.append(
            Conversation.id.in_(
                select(ConversationInvitation.conversation_id).where(
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
        filters.append(
            Conversation.project_id.in_(
                select(Project.id).where(
                    Project.is_archived.is_(False),
                    or_(
                        Project.owner_user_id == user_id,
                        Project.visibility == "public",
                        Project.id.in_(
                            select(ProjectInvitation.project_id).where(
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
        )
        clause = or_(*filters) if len(filters) > 1 else filters[0]
        include_archived = _is_super_admin(user_role)
        query = select(Conversation).where(clause)
        if not include_archived:
            query = query.where(Conversation.is_archived.is_(False))
        conv_result = await session.execute(
            query.order_by(desc(Conversation.updated_at), desc(Conversation.created_at)).limit(safe_limit)
        )
        conversations = conv_result.scalars().all()
        if not conversations:
            return []
        conv_ids = [conv.id for conv in conversations if conv.id]
        latest_messages: dict = {}
        latest_user_messages: dict = {}
        if conv_ids:
            msg_result = await session.execute(
                select(Message)
                .where(Message.conversation_id.in_(conv_ids))
                .order_by(Message.conversation_id, Message.created_at.desc())
            )
            for msg in msg_result.scalars():
                key = msg.conversation_id
                if key not in latest_messages:
                    latest_messages[key] = msg
                if msg.role == "user" and key not in latest_user_messages:
                    latest_user_messages[key] = msg
        summaries = []
        for conv in conversations:
            msg = latest_messages.get(conv.id)
            last_user_msg = latest_user_messages.get(conv.id)
            summaries.append(
                {
                    "id": str(conv.id) if conv.id else None,
                    "project_id": conv.project_id,
                    "project_label": conv.project_label,
                    "title": conv.title,
                    "has_custom_title": _has_custom_title(conv.title),
                    "visibility": conv.visibility or "private",
                    "owner_role": conv.owner_role,
                    "user_id": conv.user_id,
                    "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
                    "created_at": conv.created_at.isoformat() if conv.created_at else None,
                    "last_message": msg.content if msg else None,
                    "last_role": msg.role if msg else None,
                    "last_message_at": msg.created_at.isoformat() if msg and msg.created_at else None,
                    "last_user_message": last_user_msg.content if last_user_msg else None,
                    "last_user_message_at": last_user_msg.created_at.isoformat() if last_user_msg and last_user_msg.created_at else None,
                    "message_count": None,
                    "is_archived": conv.is_archived,
                    "archived_at": conv.archived_at.isoformat() if conv.archived_at else None,
                    "archived_by": conv.archived_by,
                    "archived_role": conv.archived_role,
                }
            )
        return summaries


async def archive_conversation(
    conversation_id: uuid.UUID,
    *,
    archived_by: Optional[int] = None,
    archived_role: Optional[str] = None,
) -> bool:
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return False
        if conversation.is_archived:
            return True
        conversation.is_archived = True
        conversation.archived_at = func.now()
        conversation.archived_by = archived_by
        conversation.archived_role = archived_role
        conversation.updated_at = func.now()
        await session.commit()
        return True


async def restore_conversation(conversation_id: uuid.UUID) -> bool:
    async with get_async_session() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalars().first()
        if not conversation:
            return False
        if not conversation.is_archived:
            return True
        conversation.is_archived = False
        conversation.archived_at = None
        conversation.archived_by = None
        conversation.archived_role = None
        conversation.updated_at = func.now()
        await session.commit()
        return True
