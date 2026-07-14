import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer, Table, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from .database import Base

role_permissions_table = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, default="", server_default="")
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    session_version = Column(Integer, nullable=False, default=1)
    password_set_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PasswordActionToken(Base):
    __tablename__ = "password_action_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    purpose = Column(String(32), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(String(255), nullable=True)

    user = relationship("User")

class Conversation(Base):
    __tablename__ = 'conversations'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True, index=True)
    project_id = Column(String(255), nullable=True, index=True)
    project_label = Column(String(255), nullable=True)
    title = Column(String(255), default="New Conversation")
    owner_role = Column(String(100), nullable=True)
    visibility = Column(String(20), nullable=False, default="private")
    is_archived = Column(Boolean, nullable=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(Integer, nullable=True)
    archived_role = Column(String(100), nullable=True)
    customer_snapshot = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    user = relationship("User")
    customer = relationship("Customer", back_populates="conversations")

class Message(Base):
    __tablename__ = 'messages'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey('conversations.id'), nullable=False)
    role = Column(String(50), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    summary_snapshot = Column(String(255), nullable=True)
    highlights = Column(JSONB, nullable=True)
    message_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    conversation = relationship("Conversation", back_populates="messages")

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    conversation_visibility_default = Column(String(20), nullable=False, default="private", server_default="private")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    permissions = relationship(
        "Permission",
        secondary=role_permissions_table,
        back_populates="roles",
        lazy="selectin",
    )

class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(150), unique=True, nullable=False)
    scope = Column(String(150), nullable=True)
    description = Column(Text, nullable=True)
    roles = relationship(
        "Role",
        secondary=role_permissions_table,
        back_populates="permissions",
        lazy="selectin",
    )

class Quote(Base):
    __tablename__ = "quotes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_no = Column(String(32), unique=True, index=True, nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True, index=True)
    customer_name = Column(String(255), nullable=True)
    sales_rep = Column(String(255), nullable=True)
    quote_date = Column(DateTime(timezone=True), nullable=False)
    reply_date = Column(DateTime(timezone=True), nullable=True)
    taxable_amount = Column(Integer, nullable=True)
    tax_amount = Column(Integer, nullable=True)
    total_amount = Column(Integer, nullable=True)
    quote_items = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EdmPreview(Base):
    __tablename__ = "edm_previews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    share_token = Column(String(64), unique=True, index=True, nullable=False)
    conversation_id = Column(String(64), nullable=True, index=True)
    created_by_username = Column(String(255), nullable=True)
    quote_no = Column(String(32), unique=True, index=True, nullable=False)
    quote_date = Column(DateTime(timezone=True), nullable=False)
    sales_rep = Column(String(255), nullable=True)
    hero_text = Column(Text, nullable=True)
    banner_snapshot = Column(JSONB, nullable=False, default=dict)
    rows_snapshot = Column(JSONB, nullable=False, default=list)
    project_snapshot = Column(JSONB, nullable=True)
    share_url = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
