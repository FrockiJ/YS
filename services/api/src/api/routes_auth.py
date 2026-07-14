from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import (
    PASSWORD_ACTION_PURPOSE_RESET,
    PASSWORD_ACTION_PURPOSE_SETUP,
    _raise_api_error,
    change_password,
    complete_password_action,
    login_with_password,
    refresh_access_token,
    request_password_reset,
    validate_password_action_token,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginIn(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: str = Field(..., min_length=1)

    @property
    def identifier(self) -> str:
        return (self.username or self.email or "").strip()


class ForgotPasswordIn(BaseModel):
    email: str = Field(..., min_length=3)


class PasswordTokenIn(BaseModel):
    token: str = Field(..., min_length=10)


class PasswordCompleteIn(PasswordTokenIn):
    password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)


@router.post("/login")
async def login(payload: LoginIn):
    try:
        if not payload.identifier:
            _raise_api_error(400, "auth.identifier_required", "api_errors.auth.identifier_required")
        token, profile = await login_with_password(payload.identifier, payload.password)
        return {"ok": True, "token": token, "access_token": token, "user": profile}
    except HTTPException as http_error:
        raise http_error
    except Exception as ex:
        _raise_api_error(500, "auth.login_failed", "api_errors.request_failed", detail=str(ex))


@router.post("/refresh")
async def refresh(authorization: str = Header(None)):
    try:
        token, profile = await refresh_access_token(authorization)
        return {"ok": True, "token": token, "access_token": token, "user": profile}
    except HTTPException as http_error:
        raise http_error
    except Exception as ex:
        _raise_api_error(500, "auth.refresh_failed", "api_errors.auth.refresh_failed", detail=str(ex))


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordIn):
    try:
        return await request_password_reset(payload.email)
    except HTTPException as http_error:
        raise http_error
    except Exception as ex:
        _raise_api_error(500, "auth.forgot_password_failed", "api_errors.request_failed", detail=str(ex))


@router.post("/reset-password/validate")
async def validate_reset_password(payload: PasswordTokenIn):
    try:
        return await validate_password_action_token(payload.token, PASSWORD_ACTION_PURPOSE_RESET)
    except HTTPException as http_error:
        raise http_error
    except Exception as ex:
        _raise_api_error(500, "auth.reset_password_validate_failed", "api_errors.request_failed", detail=str(ex))


@router.post("/reset-password/complete")
async def complete_reset_password(payload: PasswordCompleteIn):
    try:
        return await complete_password_action(
            payload.token,
            PASSWORD_ACTION_PURPOSE_RESET,
            payload.password,
            payload.confirm_password,
        )
    except HTTPException as http_error:
        raise http_error
    except Exception as ex:
        _raise_api_error(500, "auth.reset_password_failed", "api_errors.request_failed", detail=str(ex))


@router.post("/setup-password/validate")
async def validate_setup_password(payload: PasswordTokenIn):
    try:
        return await validate_password_action_token(payload.token, PASSWORD_ACTION_PURPOSE_SETUP)
    except HTTPException as http_error:
        raise http_error
    except Exception as ex:
        _raise_api_error(500, "auth.setup_password_validate_failed", "api_errors.request_failed", detail=str(ex))


@router.post("/setup-password/complete")
async def complete_setup_password(payload: PasswordCompleteIn):
    try:
        return await complete_password_action(
            payload.token,
            PASSWORD_ACTION_PURPOSE_SETUP,
            payload.password,
            payload.confirm_password,
        )
    except HTTPException as http_error:
        raise http_error
    except Exception as ex:
        _raise_api_error(500, "auth.setup_password_failed", "api_errors.request_failed", detail=str(ex))


@router.post("/change-password")
async def change_password_route(payload: ChangePasswordIn, authorization: str = Header(None)):
    try:
        return await change_password(
            authorization,
            payload.current_password,
            payload.new_password,
            payload.confirm_password,
        )
    except HTTPException as http_error:
        raise http_error
    except Exception as ex:
        _raise_api_error(500, "auth.change_password_failed", "api_errors.auth.change_password_failed", detail=str(ex))
