from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List


class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    username: str
    email: Optional[str] = None
    role: Optional[str] = "user"


class UserCreate(UserBase):
    password: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class User(UserBase):
    id: int
    is_active: bool = True
    updated_at: Optional[datetime] = None
    password_set_at: Optional[datetime] = None
    permissions: List[str] = Field(default_factory=list)
    role_active: bool = True
    conversation_visibility_default: str = "private"
    session_version: int = 1

    class Config:
        from_attributes = True
