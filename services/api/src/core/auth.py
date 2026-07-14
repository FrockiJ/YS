import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional
from urllib.parse import quote

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .config import ADMIN_EMAIL as CONFIG_ADMIN_EMAIL
from .config import ADMIN_PASSWORD as CONFIG_ADMIN_PASSWORD
from .config import PASSWORD_ACTION_FRONTEND_BASE_URL
from .database import SessionLocal
from .email_service import EmailServiceError, build_password_email, get_email_service
from .models import PasswordActionToken, Role, User
from .security import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    get_password_hash,
    verify_password,
)

ADMIN_USERNAME = os.getenv("YS_ADMIN_USERNAME") or os.getenv("ADMIN_USERNAME", "jopasck")
ADMIN_EMAIL = CONFIG_ADMIN_EMAIL or os.getenv("ADMIN_EMAIL", "admin@local.local")
ADMIN_PASSWORD = CONFIG_ADMIN_PASSWORD or os.getenv("ADMIN_PASSWORD", "")
ADMIN_ROLE = "admin"
SADMIN_ROLE = "SAdmin"
ADMIN_ROLE_SET = {ADMIN_ROLE, SADMIN_ROLE}
DEV_ADMIN_PERMISSIONS = (
    "admin.chat.access",
    "admin.projects.access",
    "admin.labels.access",
    "admin.files.access",
    "admin.users.read",
    "admin.users.write",
    "admin.roles.manage",
    "admin.permissions.manage",
    "admin.settings.access",
)
PLATFORM_SUPERUSER_USERNAMES = {"frocki"}
PASSWORD_ACTION_PURPOSE_RESET = "reset_password"
PASSWORD_ACTION_PURPOSE_SETUP = "setup_password"
PASSWORD_RESET_TOKEN_TTL = timedelta(minutes=30)
PASSWORD_SETUP_TOKEN_TTL = timedelta(hours=72)
PASSWORD_ACTION_GENERIC_MESSAGE = "If the email exists in DEV, a password email has been sent."


def _error_payload(code: str, message_key: str, *, detail: Optional[str] = None, context: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "code": code,
        "message_key": message_key,
    }
    if detail:
        payload["detail_message"] = detail
    if context:
        payload["context"] = context
    return payload


def _raise_api_error(
    status_code: int,
    code: str,
    message_key: str,
    *,
    detail: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    context: Optional[Dict[str, object]] = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=_error_payload(code, message_key, detail=detail, context=context),
        headers=headers,
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized.lower() if normalized else None


def _normalize_email(value: Optional[str]) -> Optional[str]:
    normalized = _normalize(value)
    return normalized if normalized and "@" in normalized else None


def _is_platform_superuser_identifier(value: Optional[str]) -> bool:
    normalized = _normalize(value)
    return bool(normalized and normalized in PLATFORM_SUPERUSER_USERNAMES)


def _is_platform_superuser_profile(user: Optional[Dict[str, object]]) -> bool:
    if not user:
        return False
    if bool(user.get("is_platform_superuser")):
        return True
    return _is_platform_superuser_identifier(str(user.get("username") or ""))


def _normalize_permission_codes(permissions: Optional[Iterable[object]]) -> list[str]:
    normalized: list[str] = []
    for entry in permissions or []:
        if isinstance(entry, dict):
            candidate = entry.get("code")
        else:
            candidate = getattr(entry, "code", entry)
        value = str(candidate or "").strip()
        if value:
            normalized.append(value)
    return normalized


def _hash_action_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _mask_email(email: Optional[str]) -> str:
    normalized = str(email or "").strip()
    if not normalized or "@" not in normalized:
        return ""
    local_part, domain = normalized.split("@", 1)
    if len(local_part) <= 2:
        masked_local = f"{local_part[:1]}*"
    else:
        masked_local = f"{local_part[:2]}{'*' * max(2, len(local_part) - 2)}"
    return f"{masked_local}@{domain}"


def _ensure_valid_new_password(password: str, confirm_password: str) -> None:
    candidate = str(password or "")
    if candidate != str(confirm_password or ""):
        _raise_api_error(400, "auth.password_confirmation_mismatch", "api_errors.auth.password_confirmation_mismatch")
    if len(candidate) < 8:
        _raise_api_error(400, "auth.password_too_short", "api_errors.auth.password_too_short")
    if len(candidate) > 128:
        _raise_api_error(400, "auth.password_too_long", "api_errors.auth.password_too_long")


def _build_access_token_for_profile(username: str, profile: Dict[str, object]) -> str:
    return create_access_token(
        {
            "sub": username,
            "role": profile["role"],
            "version": profile["session_version"],
        }
    )


def _build_password_action_url(purpose: str, raw_token: str) -> str:
    base_url = str(PASSWORD_ACTION_FRONTEND_BASE_URL or "http://localhost:5263").rstrip("/")
    route_name = "reset-password" if purpose == PASSWORD_ACTION_PURPOSE_RESET else "setup-password"
    return f"{base_url}/{route_name}/{quote(raw_token)}"


def _build_platform_superuser_profile(user: User) -> Dict[str, object]:
    return {
        "id": user.id,
        "name": getattr(user, "name", "") or user.username,
        "username": user.username,
        "email": getattr(user, "email", None),
        "role": SADMIN_ROLE,
        "is_active": True,
        "permissions": list(DEV_ADMIN_PERMISSIONS),
        "role_active": True,
        "conversation_visibility_default": "private",
        "session_version": getattr(user, "session_version", 1),
        "password_set_at": getattr(user, "password_set_at", None),
        "is_platform_superuser": True,
    }


async def _load_role(session, role_name: Optional[str]) -> Optional[Role]:
    normalized_name = str(role_name or "").strip()
    if not normalized_name:
        return None
    result = await session.execute(
        select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.name == normalized_name)
    )
    return result.scalar_one_or_none()


async def _build_profile_from_user(session, user: User) -> Dict[str, object]:
    if _is_platform_superuser_identifier(user.username):
        return _build_platform_superuser_profile(user)
    role = await _load_role(session, user.role)
    permissions = _normalize_permission_codes(getattr(role, "permissions", []))
    role_active = True if role is None else bool(getattr(role, "is_active", True))
    visibility_default = (
        getattr(role, "conversation_visibility_default", "private") if role else "private"
    ) or "private"
    return {
        "id": user.id,
        "name": getattr(user, "name", "") or user.username,
        "username": user.username,
        "email": getattr(user, "email", None),
        "role": user.role or "user",
        "is_active": bool(getattr(user, "is_active", True)),
        "permissions": permissions,
        "role_active": role_active,
        "conversation_visibility_default": visibility_default,
        "session_version": getattr(user, "session_version", 1),
        "password_set_at": getattr(user, "password_set_at", None),
        "is_platform_superuser": False,
    }


def _build_dev_admin_profile(identifier: str) -> Dict[str, object]:
    return {
        "id": None,
        "email": ADMIN_EMAIL or identifier,
        "name": ADMIN_USERNAME or identifier,
        "username": ADMIN_USERNAME or identifier,
        "role": "admin",
        "is_active": True,
        "permissions": list(DEV_ADMIN_PERMISSIONS),
        "role_active": True,
        "conversation_visibility_default": "private",
        "session_version": 1,
        "password_set_at": _utcnow(),
    }


async def _fetch_user_by_identifier(identifier: str) -> Optional[User]:
    normalized_identifier = str(identifier or "").strip()
    normalized_email = _normalize_email(normalized_identifier)
    async with SessionLocal() as session:
        if normalized_email:
            result = await session.execute(
                select(User).where(func.lower(User.email) == normalized_email)
            )
            user = result.scalar_one_or_none()
            if user:
                return user
        result = await session.execute(select(User).where(User.username == normalized_identifier))
        return result.scalar_one_or_none()


async def _ensure_dev_admin_user() -> tuple[User, Dict[str, object]]:
    username = (ADMIN_USERNAME or "jopasck").strip() or "jopasck"
    admin_email = _normalize_email(ADMIN_EMAIL)

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        changed = False

        if user is None:
            user = User(
                name=username,
                username=username,
                email=admin_email,
                hashed_password=get_password_hash(ADMIN_PASSWORD),
                role=ADMIN_ROLE,
                is_active=True,
                password_set_at=_utcnow(),
            )
            session.add(user)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(select(User).where(User.username == username))
                user = result.scalar_one_or_none()
                if user is None:
                    raise
            else:
                await session.refresh(user)
        else:
            if not (getattr(user, "name", "") or "").strip():
                user.name = username
                changed = True
            if admin_email and getattr(user, "email", None) != admin_email:
                user.email = admin_email
                changed = True
            if user.role not in ADMIN_ROLE_SET:
                user.role = ADMIN_ROLE
                changed = True
            if not bool(getattr(user, "is_active", True)):
                user.is_active = True
                changed = True
            if not verify_password(ADMIN_PASSWORD, user.hashed_password):
                user.hashed_password = get_password_hash(ADMIN_PASSWORD)
                user.password_set_at = _utcnow()
                changed = True
            elif getattr(user, "password_set_at", None) is None:
                user.password_set_at = _utcnow()
                changed = True
            if changed:
                user.session_version = (getattr(user, "session_version", 1) or 1) + 1
                await session.commit()
                await session.refresh(user)

        profile = await _build_profile_from_user(session, user)
        return user, profile


def _ensure_role_is_active(profile: Dict[str, object], *, status_code: int) -> None:
    if _is_platform_superuser_profile(profile):
        return
    if profile.get("role_active", True):
        return
    headers = {"WWW-Authenticate": "Bearer"} if status_code == status.HTTP_401_UNAUTHORIZED else None
    _raise_api_error(
        status_code,
        "auth.role_disabled",
        "api_errors.auth.role_disabled",
        headers=headers,
    )


def _ensure_user_is_active(profile: Dict[str, object], *, status_code: int) -> None:
    if _is_platform_superuser_profile(profile):
        return
    if profile.get("is_active", True):
        return
    headers = {"WWW-Authenticate": "Bearer"} if status_code == status.HTTP_401_UNAUTHORIZED else None
    _raise_api_error(
        status_code,
        "auth.user_disabled",
        "api_errors.auth.user_disabled",
        headers=headers,
    )


def _has_permission(user: Optional[Dict[str, object]], permission_code: str) -> bool:
    if not user:
        return False
    if _is_platform_superuser_profile(user):
        return True
    normalized = set(_normalize_permission_codes(user.get("permissions")))
    return permission_code in normalized


def _has_any_permission(user: Optional[Dict[str, object]], permission_codes: Iterable[str]) -> bool:
    if _is_platform_superuser_profile(user):
        return True
    normalized = set(_normalize_permission_codes(user.get("permissions") if user else []))
    return any(code in normalized for code in permission_codes)


async def login_with_password(identifier: str, password: str):
    identifier = (identifier or "").strip()
    if not identifier:
        _raise_api_error(400, "auth.identifier_required", "api_errors.auth.identifier_required")

    user = await _fetch_user_by_identifier(identifier)
    if user and verify_password(password, user.hashed_password):
        async with SessionLocal() as session:
            profile = await _build_profile_from_user(session, user)
        _ensure_user_is_active(profile, status_code=status.HTTP_403_FORBIDDEN)
        _ensure_role_is_active(profile, status_code=status.HTTP_403_FORBIDDEN)
        token = _build_access_token_for_profile(user.username, profile)
        return token, profile

    allowed_identifiers = {i for i in {_normalize(ADMIN_EMAIL), _normalize(ADMIN_USERNAME)} if i}
    if _normalize(identifier) in allowed_identifiers and password == ADMIN_PASSWORD:
        user, profile = await _ensure_dev_admin_user()
        token = _build_access_token_for_profile(user.username, profile)
        return token, profile

    _raise_api_error(401, "auth.credentials_invalid", "api_errors.auth.credentials_invalid")


async def _authenticate_access_token(token: str) -> tuple[User, Dict[str, object]]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_error_payload("auth.invalid_token", "api_errors.auth.invalid_token"),
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        version = payload.get("version")
    except JWTError as exc:
        raise credentials_exception from exc

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise credentials_exception
        if version is None or version != getattr(db_user, "session_version", 1):
            _raise_api_error(
                status.HTTP_401_UNAUTHORIZED,
                "auth.session_expired",
                "api_errors.auth.session_expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        profile = await _build_profile_from_user(session, db_user)
        _ensure_user_is_active(profile, status_code=status.HTTP_401_UNAUTHORIZED)
        _ensure_role_is_active(profile, status_code=status.HTTP_401_UNAUTHORIZED)
        return db_user, profile


async def refresh_access_token(authorization: Optional[str]) -> tuple[str, Dict[str, object]]:
    if not authorization or not authorization.lower().startswith("bearer "):
        _raise_api_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth.missing_token",
            "api_errors.auth.missing_token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1]
    user, profile = await _authenticate_access_token(token)
    refreshed_token = _build_access_token_for_profile(user.username, profile)
    return refreshed_token, profile


async def get_current_user_optional(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None

    token = authorization.split(" ", 1)[1]
    try:
        _, profile = await _authenticate_access_token(token)
        return profile
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get("code") == "auth.invalid_token" and token.startswith("dev-"):
            return _build_dev_admin_profile(token[4:])
        if detail.get("code") == "auth.invalid_token":
            return None
        raise


async def _issue_password_action_email(*, user: User, purpose: str, created_by: Optional[str]) -> None:
    recipient = _normalize_email(getattr(user, "email", None))
    if not recipient:
        _raise_api_error(400, "auth.email_missing", "api_errors.auth.email_missing")

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_action_token(raw_token)
    now = _utcnow()
    ttl = PASSWORD_RESET_TOKEN_TTL if purpose == PASSWORD_ACTION_PURPOSE_RESET else PASSWORD_SETUP_TOKEN_TTL
    expires_at = now + ttl

    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        if not db_user:
            _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
        await session.execute(
            update(PasswordActionToken)
            .where(
                PasswordActionToken.user_id == db_user.id,
                PasswordActionToken.purpose == purpose,
                PasswordActionToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        session.add(
            PasswordActionToken(
                user_id=db_user.id,
                email=recipient,
                purpose=purpose,
                token_hash=token_hash,
                expires_at=expires_at,
                created_by=created_by,
            )
        )
        await session.commit()

    try:
        email_service = get_email_service()
        action_url = _build_password_action_url(purpose, raw_token)
        if purpose == PASSWORD_ACTION_PURPOSE_RESET:
            payload = build_password_email(
                recipient=recipient,
                subject="ys password reset",
                heading="Reset your password",
                intro="A password reset was requested for your ys account. Use the button below to continue.",
                cta_label="Reset password",
                action_url=action_url,
                expiry_hint="This link expires in 30 minutes.",
                purpose=purpose,
            )
        else:
            payload = build_password_email(
                recipient=recipient,
                subject="ys setup your password",
                heading="Set up your password",
                intro="Your ys account is ready. Use the button below to set your first password.",
                cta_label="Set password",
                action_url=action_url,
                expiry_hint="This link expires in 72 hours.",
                purpose=purpose,
            )
        await email_service.send(payload)
    except EmailServiceError as exc:
        detail = str(exc)
        code = "auth.email_delivery_incomplete"
        message_key = "api_errors.auth.email_delivery_incomplete"
        if "not enabled" in detail.lower():
            code = "auth.email_delivery_disabled"
            message_key = "api_errors.auth.email_delivery_disabled"
        _raise_api_error(503, code, message_key, detail=detail)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_api_error(
            502,
            "auth.email_delivery_failed",
            "api_errors.auth.email_delivery_failed",
            detail=str(exc),
        )


async def request_password_reset(email: str) -> Dict[str, object]:
    normalized_email = _normalize_email(email)
    if not normalized_email:
        _raise_api_error(400, "auth.email_required", "api_errors.auth.email_required")

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(func.lower(User.email) == normalized_email))
        user = result.scalar_one_or_none()
        if not user:
            try:
                get_email_service()
            except EmailServiceError as exc:
                detail = str(exc)
                code = "auth.email_delivery_incomplete"
                message_key = "api_errors.auth.email_delivery_incomplete"
                if "not enabled" in detail.lower():
                    code = "auth.email_delivery_disabled"
                    message_key = "api_errors.auth.email_delivery_disabled"
                _raise_api_error(503, code, message_key, detail=detail)
            return {
                "ok": True,
                "message": PASSWORD_ACTION_GENERIC_MESSAGE,
                "message_key": "login.forgot.success_title",
            }

        profile = await _build_profile_from_user(session, user)
        _ensure_user_is_active(profile, status_code=status.HTTP_400_BAD_REQUEST)
        _ensure_role_is_active(profile, status_code=status.HTTP_400_BAD_REQUEST)

    await _issue_password_action_email(
        user=user,
        purpose=PASSWORD_ACTION_PURPOSE_RESET,
        created_by="self-service",
    )
    return {"ok": True, "message": PASSWORD_ACTION_GENERIC_MESSAGE}


async def create_setup_password_invite(user_id: int, requested_by: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
        profile = await _build_profile_from_user(session, user)
        _ensure_user_is_active(profile, status_code=status.HTTP_400_BAD_REQUEST)
        _ensure_role_is_active(profile, status_code=status.HTTP_400_BAD_REQUEST)

    sender = None
    if requested_by:
        sender = str(requested_by.get("username") or requested_by.get("email") or "").strip() or None
    await _issue_password_action_email(
        user=user,
        purpose=PASSWORD_ACTION_PURPOSE_SETUP,
        created_by=sender,
    )
    return {
        "ok": True,
        "message": "Setup password email sent.",
        "message_key": "account.form.setup_email_success",
        "user_id": user.id,
        "email": user.email,
    }


async def validate_password_action_token(raw_token: str, purpose: str) -> Dict[str, object]:
    token_hash = _hash_action_token(str(raw_token or "").strip())
    now = _utcnow()

    async with SessionLocal() as session:
        result = await session.execute(
            select(PasswordActionToken, User)
            .join(User, User.id == PasswordActionToken.user_id)
            .where(
                PasswordActionToken.token_hash == token_hash,
                PasswordActionToken.purpose == purpose,
            )
        )
        row = result.first()
        if not row:
            return {"ok": True, "valid": False, "purpose": purpose, "expired": False, "email": ""}

        action_token, user = row
        expired = action_token.expires_at <= now
        consumed = action_token.consumed_at is not None
        profile = await _build_profile_from_user(session, user)
        active = bool(profile.get("is_active", True) and profile.get("role_active", True))
        return {
            "ok": True,
            "valid": bool(not expired and not consumed and active),
            "purpose": purpose,
            "expired": expired,
            "consumed": consumed,
            "email": _mask_email(action_token.email),
        }


async def complete_password_action(raw_token: str, purpose: str, password: str, confirm_password: str) -> Dict[str, object]:
    _ensure_valid_new_password(password, confirm_password)
    token_hash = _hash_action_token(str(raw_token or "").strip())
    now = _utcnow()

    async with SessionLocal() as session:
        result = await session.execute(
            select(PasswordActionToken, User)
            .join(User, User.id == PasswordActionToken.user_id)
            .where(
                PasswordActionToken.token_hash == token_hash,
                PasswordActionToken.purpose == purpose,
            )
        )
        row = result.first()
        if not row:
            _raise_api_error(400, "auth.password_link_invalid", "api_errors.auth.password_link_invalid")

        action_token, user = row
        if action_token.consumed_at is not None:
            _raise_api_error(400, "auth.password_link_used", "api_errors.auth.password_link_used")
        if action_token.expires_at <= now:
            _raise_api_error(400, "auth.password_link_expired", "api_errors.auth.password_link_expired")

        profile = await _build_profile_from_user(session, user)
        _ensure_user_is_active(profile, status_code=status.HTTP_400_BAD_REQUEST)
        _ensure_role_is_active(profile, status_code=status.HTTP_400_BAD_REQUEST)

        user.hashed_password = get_password_hash(password)
        user.password_set_at = now
        user.session_version = (getattr(user, "session_version", 1) or 1) + 1
        action_token.consumed_at = now
        session.add(user)
        session.add(action_token)
        await session.commit()
        await session.refresh(user)
        next_profile = await _build_profile_from_user(session, user)

    return {
        "ok": True,
        "message": "Password updated successfully.",
        "message_key": "password_flow.reset.success_message"
        if purpose == PASSWORD_ACTION_PURPOSE_RESET
        else "password_flow.setup.success_message",
        "user": next_profile,
    }


async def change_password(
    authorization: Optional[str],
    current_password: str,
    new_password: str,
    confirm_password: str,
) -> Dict[str, object]:
    if not authorization or not authorization.lower().startswith("bearer "):
        _raise_api_error(401, "auth.missing_token", "api_errors.auth.missing_token")

    _ensure_valid_new_password(new_password, confirm_password)
    token = authorization.split(" ", 1)[1]
    _, profile = await _authenticate_access_token(token)

    async with SessionLocal() as session:
        db_user = await session.get(User, profile["id"])
        if not db_user:
            _raise_api_error(404, "admin.user_not_found", "api_errors.admin.user_not_found")
        if not verify_password(current_password, db_user.hashed_password):
            _raise_api_error(400, "auth.current_password_incorrect", "api_errors.auth.current_password_incorrect")
        db_user.hashed_password = get_password_hash(new_password)
        db_user.password_set_at = _utcnow()
        db_user.session_version = (getattr(db_user, "session_version", 1) or 1) + 1
        session.add(db_user)
        await session.commit()
        await session.refresh(db_user)
        next_profile = await _build_profile_from_user(session, db_user)

    return {
        "ok": True,
        "message": "Password changed successfully.",
        "message_key": "app.topbar.password_modal.toast_message",
        "user": next_profile,
    }


async def get_current_active_admin_user(user: dict = Depends(get_current_user_optional)):
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The user doesn't have enough privileges")
    _ensure_user_is_active(user, status_code=status.HTTP_403_FORBIDDEN)
    _ensure_role_is_active(user, status_code=status.HTTP_403_FORBIDDEN)
    if user.get("role") not in ADMIN_ROLE_SET and not _has_any_permission(
        user,
        (
            "admin.users.read",
            "admin.users.write",
            "admin.roles.manage",
            "admin.permissions.manage",
        ),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The user doesn't have enough privileges")
    return user


def require_permissions(*permission_codes: str, any_of: bool = False):
    async def dependency(user: dict = Depends(get_current_user_optional)):
        if not user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The user doesn't have enough privileges",
            )
        _ensure_user_is_active(user, status_code=status.HTTP_403_FORBIDDEN)
        _ensure_role_is_active(user, status_code=status.HTTP_403_FORBIDDEN)
        if any_of:
            allowed = _has_any_permission(user, permission_codes)
        else:
            allowed = all(_has_permission(user, code) for code in permission_codes)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The user doesn't have enough privileges",
            )
        return user

    return dependency
