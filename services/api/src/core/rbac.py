from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=15)
    description: Optional[str] = None
    is_active: bool = True
    conversation_visibility_default: Literal["private", "public"] = "private"


class RoleCreate(RoleBase):
    permissions: List[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=15)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    conversation_visibility_default: Optional[Literal["private", "public"]] = None
    permissions: Optional[List[str]] = None


class PermissionBase(BaseModel):
    code: str
    scope: Optional[str] = None
    description: Optional[str] = None


class Permission(PermissionBase):
    id: int

    class Config:
        from_attributes = True


class Role(RoleBase):
    id: int
    updated_at: Optional[datetime] = None
    member_count: int = 0
    permissions: List[Permission] = Field(default_factory=list)

    class Config:
        from_attributes = True


class PermissionCreate(PermissionBase):
    pass


class PermissionUpdate(BaseModel):
    code: Optional[str] = None
    scope: Optional[str] = None
    description: Optional[str] = None
