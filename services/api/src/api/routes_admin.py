from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import SessionLocal
from ..core.auth import (
    _is_platform_superuser_identifier,
    _raise_api_error,
    create_setup_password_invite,
    require_permissions,
)
from ..crud import user as crud_user
from ..crud import role as crud_role
from ..crud import permission as crud_permission
from ..core.user import User, UserCreate, UserUpdate
from ..core.rbac import (
    Role as RoleSchema,
    RoleCreate,
    RoleUpdate,
    Permission as PermissionSchema,
    PermissionCreate,
    PermissionUpdate,
)

router = APIRouter()

async def get_db():
    async with SessionLocal() as db:
        yield db

async def _ensure_role_exists(db: AsyncSession, role_name: Optional[str]):
    if not role_name:
        return
    existing = await crud_role.get_role_by_name(db, role_name)
    if not existing:
        _raise_api_error(400, "admin.role_not_found", "api_errors.admin.role_not_found", context={"role_name": role_name})
    if not bool(getattr(existing, "is_active", True)):
        _raise_api_error(400, "admin.role_disabled", "api_errors.admin.role_disabled", context={"role_name": role_name})


def _is_protected_user(user: User) -> bool:
    return _is_platform_superuser_identifier(getattr(user, "username", None))


def _reject_protected_user_change(action: str) -> None:
    _raise_api_error(
        403,
        "admin.protected_user",
        "api_errors.admin.protected_user",
        context={"action": action},
    )


def _ensure_protected_user_can_be_updated(existing_user: User, updates: UserUpdate) -> None:
    if not _is_protected_user(existing_user):
        return
    updated_fields = getattr(updates, "model_fields_set", None) or getattr(updates, "__fields_set__", set())
    protected_fields = {"username", "password", "role", "is_active"}
    if protected_fields.intersection(updated_fields):
        _reject_protected_user_change("update")

@router.post("/users/", response_model=User, dependencies=[Depends(require_permissions("admin.users.write"))])
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    db_user = await crud_user.get_user_by_username(db, username=user.username)
    if db_user:
        _raise_api_error(400, "admin.username_exists", "api_errors.admin.username_exists")
    if user.email:
        existing_email = await crud_user.get_user_by_email(db, email=user.email)
        if existing_email:
            _raise_api_error(400, "admin.email_exists", "api_errors.admin.email_exists")
    await _ensure_role_exists(db, user.role)
    try:
        return await crud_user.create_user(db=db, user=user)
    except ValueError as exc:
        _raise_api_error(400, "admin.user_create_invalid", "api_errors.request_failed", detail=str(exc))

@router.get(
    "/users/",
    response_model=List[User],
    dependencies=[Depends(require_permissions("admin.users.read", "admin.users.write", any_of=True))],
)
async def read_users(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    return await crud_user.get_users(db, skip=skip, limit=limit)

@router.get(
    "/users/{user_id}",
    response_model=User,
    dependencies=[Depends(require_permissions("admin.users.read", "admin.users.write", any_of=True))],
)
async def read_user(user_id: int, db: AsyncSession = Depends(get_db)):
    db_user = await crud_user.get_user(db, user_id=user_id)
    if db_user is None:
        _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
    return db_user

@router.delete("/users/{user_id}", response_model=User, dependencies=[Depends(require_permissions("admin.users.write"))])
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    existing = await crud_user.get_user(db, user_id=user_id)
    if existing is None:
        _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
    if _is_protected_user(existing):
        _reject_protected_user_change("delete")
    db_user = await crud_user.delete_user(db, user_id=user_id)
    if db_user is None:
        _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
    return db_user

@router.patch("/users/{user_id}", response_model=User, dependencies=[Depends(require_permissions("admin.users.write"))])
async def update_user(user_id: int, user: UserUpdate, db: AsyncSession = Depends(get_db)):
    existing_user = await crud_user.get_user(db, user_id=user_id)
    if existing_user is None:
        _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
    _ensure_protected_user_can_be_updated(existing_user, user)
    if user.username:
        existing = await crud_user.get_user_by_username(db, username=user.username)
        if existing and existing.id != user_id:
            _raise_api_error(400, "admin.username_exists", "api_errors.admin.username_exists")
    if user.email:
        existing_email = await crud_user.get_user_by_email(db, email=user.email)
        if existing_email and existing_email.id != user_id:
            _raise_api_error(400, "admin.email_exists", "api_errors.admin.email_exists")
    if user.role:
        await _ensure_role_exists(db, user.role)
    try:
        db_user = await crud_user.update_user(db, user_id=user_id, updates=user)
    except ValueError as exc:
        _raise_api_error(400, "admin.user_update_invalid", "api_errors.request_failed", detail=str(exc))
    if db_user is None:
        _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
    return db_user


@router.post(
    "/users/{user_id}/send-setup-password",
    dependencies=[Depends(require_permissions("admin.users.write"))],
)
async def send_setup_password(user_id: int, auth_user: dict = Depends(require_permissions("admin.users.write"))):
    try:
        async with SessionLocal() as db:
            existing = await crud_user.get_user(db, user_id=user_id)
            if existing is None:
                _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
            if _is_protected_user(existing):
                _reject_protected_user_change("send_setup_password")
        return await create_setup_password_invite(user_id, requested_by=auth_user)
    except HTTPException as http_error:
        raise http_error
    except Exception as exc:
        _raise_api_error(500, "admin.setup_email_failed", "api_errors.admin.setup_email_failed", detail=str(exc))

@router.post("/roles/", response_model=RoleSchema, dependencies=[Depends(require_permissions("admin.roles.manage"))])
async def create_role(payload: RoleCreate, db: AsyncSession = Depends(get_db)):
    existing = await crud_role.get_role_by_name(db, payload.name)
    if existing:
        _raise_api_error(400, "admin.role_exists", "api_errors.admin.role_exists")
    return await crud_role.create_role(db, payload)


@router.get(
    "/roles/",
    response_model=List[RoleSchema],
    dependencies=[Depends(require_permissions("admin.roles.manage", "admin.users.read", "admin.users.write", any_of=True))],
)
async def read_roles(skip: int = 0, limit: int = 200, db: AsyncSession = Depends(get_db)):
    return await crud_role.get_roles(db, skip=skip, limit=limit)


@router.get(
    "/roles/{role_id}",
    response_model=RoleSchema,
    dependencies=[Depends(require_permissions("admin.roles.manage", "admin.users.read", "admin.users.write", any_of=True))],
)
async def read_role(role_id: int, db: AsyncSession = Depends(get_db)):
    role = await crud_role.get_role(db, role_id=role_id)
    if role is None:
        _raise_api_error(404, "admin.role_not_found", "api_errors.admin.role_not_found")
    return role


@router.patch("/roles/{role_id}", response_model=RoleSchema, dependencies=[Depends(require_permissions("admin.roles.manage"))])
async def update_role(role_id: int, payload: RoleUpdate, db: AsyncSession = Depends(get_db)):
    if payload.name:
        existing = await crud_role.get_role_by_name(db, payload.name)
        if existing and existing.id != role_id:
            _raise_api_error(400, "admin.role_exists", "api_errors.admin.role_exists")
    role = await crud_role.update_role(db, role_id=role_id, updates=payload)
    if role is None:
        _raise_api_error(404, "admin.role_not_found", "api_errors.admin.role_not_found")
    return role


@router.delete("/roles/{role_id}", response_model=RoleSchema, dependencies=[Depends(require_permissions("admin.roles.manage"))])
async def delete_role(role_id: int, db: AsyncSession = Depends(get_db)):
    try:
        role = await crud_role.delete_role(db, role_id=role_id)
    except ValueError as exc:
        _raise_api_error(409, "admin.role_delete_conflict", "api_errors.admin.role_delete_conflict", detail=str(exc))
    if role is None:
        _raise_api_error(404, "admin.role_not_found", "api_errors.admin.role_not_found")
    return role


@router.post("/permissions/", response_model=PermissionSchema, dependencies=[Depends(require_permissions("admin.permissions.manage"))])
async def create_permission(payload: PermissionCreate, db: AsyncSession = Depends(get_db)):
    existing = await crud_permission.get_permission_by_code(db, payload.code)
    if existing:
        _raise_api_error(400, "admin.permission_exists", "api_errors.admin.permission_exists")
    return await crud_permission.create_permission(db, payload)


@router.get("/permissions/", response_model=List[PermissionSchema], dependencies=[Depends(require_permissions("admin.permissions.manage"))])
async def read_permissions(skip: int = 0, limit: int = 200, db: AsyncSession = Depends(get_db)):
    return await crud_permission.get_permissions(db, skip=skip, limit=limit)


@router.get("/permissions/{permission_id}", response_model=PermissionSchema, dependencies=[Depends(require_permissions("admin.permissions.manage"))])
async def read_permission(permission_id: int, db: AsyncSession = Depends(get_db)):
    permission = await crud_permission.get_permission(db, permission_id=permission_id)
    if permission is None:
        _raise_api_error(404, "admin.permission_not_found", "api_errors.admin.permission_not_found")
    return permission


@router.patch("/permissions/{permission_id}", response_model=PermissionSchema, dependencies=[Depends(require_permissions("admin.permissions.manage"))])
async def update_permission(permission_id: int, payload: PermissionUpdate, db: AsyncSession = Depends(get_db)):
    if payload.code:
        existing = await crud_permission.get_permission_by_code(db, payload.code)
        if existing and existing.id != permission_id:
            _raise_api_error(400, "admin.permission_exists", "api_errors.admin.permission_exists")
    permission = await crud_permission.update_permission(db, permission_id=permission_id, updates=payload)
    if permission is None:
        _raise_api_error(404, "admin.permission_not_found", "api_errors.admin.permission_not_found")
    return permission


@router.delete("/permissions/{permission_id}", response_model=PermissionSchema, dependencies=[Depends(require_permissions("admin.permissions.manage"))])
async def delete_permission(permission_id: int, db: AsyncSession = Depends(get_db)):
    permission = await crud_permission.delete_permission(db, permission_id=permission_id)
    if permission is None:
        _raise_api_error(404, "admin.permission_not_found", "api_errors.admin.permission_not_found")
    return permission
