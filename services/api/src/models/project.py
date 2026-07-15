import uuid
from sqlalchemy import Column, String, DateTime, Integer, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from ..core.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(255), primary_key=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    visibility = Column(String(20), nullable=False, default="private")

    customer_type = Column(String(20), nullable=True)
    trade_count = Column(Integer, nullable=True)
    last_trade_at = Column(DateTime(timezone=True), nullable=True)
    avg_unit_price = Column(Integer, nullable=True)
    preference_note = Column(Text, nullable=True)
    region = Column(String(255), nullable=True)
    is_archived = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProjectInvitation(Base):
    __tablename__ = "project_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(String(255), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    invited_email = Column(String(255), nullable=False, index=True)
    invited_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    responded_at = Column(DateTime(timezone=True), nullable=True)


class ConversationInvitation(Base):
    __tablename__ = "conversation_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    invited_email = Column(String(255), nullable=False, index=True)
    invited_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    responded_at = Column(DateTime(timezone=True), nullable=True)
