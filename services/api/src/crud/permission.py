from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.models import Permission
from ..core.rbac import PermissionCreate, PermissionUpdate


async def get_permission_by_code(db: AsyncSession, code: str):
    result = await db.execute(select(Permission).where(Permission.code == code))
    return result.scalars().first()


async def get_permission(db: AsyncSession, permission_id: int):
    return await db.get(Permission, permission_id)


async def get_permissions(db: AsyncSession, skip: int = 0, limit: int = 200):
    result = await db.execute(select(Permission).offset(skip).limit(limit))
    return result.scalars().all()


async def create_permission(db: AsyncSession, payload: PermissionCreate):
    permission = Permission(
        code=payload.code,
        scope=payload.scope,
        description=payload.description,
    )
    db.add(permission)
    await db.commit()
    await db.refresh(permission)
    return permission


async def update_permission(db: AsyncSession, permission_id: int, updates: PermissionUpdate):
    permission = await db.get(Permission, permission_id)
    if not permission:
        return None
    if updates.code is not None:
        permission.code = updates.code
    if updates.scope is not None:
        permission.scope = updates.scope
    if updates.description is not None:
        permission.description = updates.description
    db.add(permission)
    await db.commit()
    await db.refresh(permission)
    return permission


async def delete_permission(db: AsyncSession, permission_id: int):
    permission = await db.get(Permission, permission_id)
    if permission:
        await db.delete(permission)
        await db.commit()
    return permission
