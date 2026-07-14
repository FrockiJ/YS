import secrets
from datetime import datetime, timezone
from typing import Dict, Optional, Sequence, Set

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.models import User, Role
from ..core.security import get_password_hash
from ..core.user import UserCreate, UserUpdate


async def _load_role_map(db: AsyncSession, role_names: Set[str]) -> Dict[str, Role]:
    if not role_names:
        return {}
    stmt = (
        select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.name.in_(role_names))
    )
    result = await db.execute(stmt)
    return {role.name: role for role in result.scalars().all()}


def _attach_permissions(user: Optional[User], role_map: Dict[str, Role]) -> Optional[User]:
    if not user:
        return None
    permissions = []
    role_active = True
    conversation_visibility_default = "private"
    if user.role:
        role = role_map.get(user.role)
        if role:
            permissions = [perm.code for perm in (role.permissions or [])]
            role_active = bool(getattr(role, "is_active", True))
            conversation_visibility_default = (
                getattr(role, "conversation_visibility_default", "private") or "private"
            )
    setattr(user, "permissions", permissions)
    setattr(user, "role_active", role_active)
    setattr(user, "conversation_visibility_default", conversation_visibility_default)
    return user


async def _attach_permissions_to_users(db: AsyncSession, users: Sequence[User]) -> Sequence[User]:
    role_names = {user.role for user in users if user and user.role}
    role_map = await _load_role_map(db, role_names)
    for user in users:
        _attach_permissions(user, role_map)
    return users


async def get_user_by_username(db: AsyncSession, username: str):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if not user:
        return None
    await _attach_permissions_to_users(db, [user])
    return user


async def get_user_by_email(db: AsyncSession, email: str):
    normalized = str(email or "").strip().lower()
    if not normalized:
        return None
    result = await db.execute(select(User).where(func.lower(User.email) == normalized))
    user = result.scalars().first()
    if not user:
        return None
    await _attach_permissions_to_users(db, [user])
    return user


async def get_user(db: AsyncSession, user_id: int):
    user = await db.get(User, user_id)
    if not user:
        return None
    await _attach_permissions_to_users(db, [user])
    return user


async def get_users(db: AsyncSession, skip: int = 0, limit: int = 100):
    result = await db.execute(
        select(User)
        .order_by(User.updated_at.desc().nullslast(), User.id.asc())
        .offset(skip)
        .limit(limit)
    )
    users = result.scalars().all()
    await _attach_permissions_to_users(db, users)
    return users


async def create_user(db: AsyncSession, user: UserCreate):
    normalized_email = str(user.email or "").strip().lower() or None
    if not user.password and not normalized_email:
        raise ValueError("Email is required when creating a user without a password")

    password_value = user.password or secrets.token_urlsafe(24)
    hashed_password = get_password_hash(password_value)
    db_user = User(
        name=user.name.strip(),
        username=user.username,
        email=normalized_email,
        hashed_password=hashed_password,
        role=user.role or "user",
        is_active=True,
        password_set_at=datetime.now(timezone.utc) if user.password else None,
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    await _attach_permissions_to_users(db, [db_user])
    return db_user


async def update_user(db: AsyncSession, user_id: int, updates: UserUpdate):
    db_user = await db.get(User, user_id)
    if not db_user:
        return None
    session_changed = False
    if updates.name is not None:
        db_user.name = updates.name.strip()
    if updates.username:
        db_user.username = updates.username
    if updates.email is not None:
        normalized_email = str(updates.email or "").strip().lower() or None
        db_user.email = normalized_email
    if updates.password:
        db_user.hashed_password = get_password_hash(updates.password)
        db_user.password_set_at = datetime.now(timezone.utc)
        session_changed = True
    if updates.role and updates.role != db_user.role:
        db_user.role = updates.role
        session_changed = True
    if updates.is_active is not None and bool(updates.is_active) != bool(getattr(db_user, "is_active", True)):
        db_user.is_active = bool(updates.is_active)
        session_changed = True
    if session_changed:
        db_user.session_version = (getattr(db_user, "session_version", 1) or 1) + 1
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    await _attach_permissions_to_users(db, [db_user])
    return db_user


async def delete_user(db: AsyncSession, user_id: int):
    db_user = await db.get(User, user_id)
    if db_user:
        await db.delete(db_user)
        await db.commit()
    return db_user
