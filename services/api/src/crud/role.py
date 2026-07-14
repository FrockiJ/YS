from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.models import Conversation, Permission, Role, User
from ..core.rbac import RoleCreate, RoleUpdate


async def _resolve_permissions(db: AsyncSession, codes):
    codes = [code.strip() for code in (codes or []) if code and code.strip()]
    if not codes:
        return []
    result = await db.execute(select(Permission).where(Permission.code.in_(codes)))
    permissions = result.scalars().all()
    found = {perm.code for perm in permissions}
    missing = [code for code in set(codes) if code not in found]
    if missing:
        raise ValueError(f"Unknown permissions: {', '.join(sorted(missing))}")
    mapping = {perm.code: perm for perm in permissions}
    return [mapping[code] for code in codes]


async def _attach_member_counts(db: AsyncSession, roles):
    role_names = [role.name for role in (roles or []) if getattr(role, "name", None)]
    if not role_names:
        return roles
    result = await db.execute(
        select(User.role, func.count(User.id))
        .where(User.role.in_(role_names))
        .group_by(User.role)
    )
    counts = {name: count for name, count in result.all()}
    for role in roles:
        setattr(role, "member_count", int(counts.get(role.name, 0) or 0))
    return roles


async def _bump_role_sessions(
    db: AsyncSession,
    old_role_name: str,
    *,
    new_role_name: str | None = None,
):
    target_role_name = new_role_name or old_role_name
    await db.execute(
        update(User)
        .where(User.role == old_role_name)
        .values(
            role=target_role_name,
            session_version=User.session_version + 1,
        )
    )
    if new_role_name and new_role_name != old_role_name:
        await db.execute(
            update(Conversation)
            .where(Conversation.owner_role == old_role_name)
            .values(owner_role=new_role_name)
        )
        await db.execute(
            update(Conversation)
            .where(Conversation.archived_role == old_role_name)
            .values(archived_role=new_role_name)
        )


async def get_role_by_name(db: AsyncSession, name: str):
    result = await db.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.name == name)
    )
    role = result.scalars().first()
    if role:
        await _attach_member_counts(db, [role])
    return role


async def get_role(db: AsyncSession, role_id: int):
    result = await db.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
    )
    role = result.scalars().first()
    if role:
        await _attach_member_counts(db, [role])
    return role


async def get_roles(db: AsyncSession, skip: int = 0, limit: int = 100):
    result = await db.execute(
        select(Role)
        .options(selectinload(Role.permissions))
        .order_by(Role.updated_at.desc().nullslast(), Role.id.asc())
        .offset(skip)
        .limit(limit)
    )
    roles = result.scalars().all()
    await _attach_member_counts(db, roles)
    return roles


async def create_role(db: AsyncSession, payload: RoleCreate):
    role = Role(
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        conversation_visibility_default=payload.conversation_visibility_default,
    )
    if payload.permissions:
        role.permissions = await _resolve_permissions(db, payload.permissions)
    db.add(role)
    await db.commit()
    return await get_role(db, role.id)


async def update_role(db: AsyncSession, role_id: int, updates: RoleUpdate):
    role = await get_role(db, role_id)
    if not role:
        return None
    previous_name = role.name
    previous_permissions = [perm.code for perm in (role.permissions or [])]
    previous_is_active = bool(getattr(role, "is_active", True))
    previous_visibility = getattr(role, "conversation_visibility_default", "private") or "private"
    permissions_changed = False

    if updates.name is not None:
        role.name = updates.name
    if updates.description is not None:
        role.description = updates.description
    if updates.is_active is not None:
        role.is_active = updates.is_active
    if updates.conversation_visibility_default is not None:
        role.conversation_visibility_default = updates.conversation_visibility_default
    if updates.permissions is not None:
        permissions_changed = previous_permissions != [code.strip() for code in updates.permissions]
        role.permissions = await _resolve_permissions(db, updates.permissions)
    db.add(role)

    needs_session_bump = any(
        (
            role.name != previous_name,
            permissions_changed,
            bool(role.is_active) != previous_is_active,
            (role.conversation_visibility_default or "private") != previous_visibility,
        )
    )
    if needs_session_bump:
        await _bump_role_sessions(
            db,
            previous_name,
            new_role_name=role.name if role.name != previous_name else None,
        )

    await db.commit()
    return await get_role(db, role_id)


async def delete_role(db: AsyncSession, role_id: int):
    role = await get_role(db, role_id)
    if role:
        member_count = int(getattr(role, "member_count", 0) or 0)
        if member_count:
            raise ValueError("Role is still assigned to one or more users")
        await db.delete(role)
        await db.commit()
    return role
