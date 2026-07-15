import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from ..core.database import Base


class FileResource(Base):
    __tablename__ = "file_resources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_type = Column(String(32), nullable=False, default="product_label", index=True)
    display_name = Column(String(255), nullable=False)
    brand = Column(String(255), nullable=True, index=True)
    department_role = Column(String(100), nullable=True, index=True)
    visibility = Column(String(20), nullable=False, default="public", index=True)
    attachment_path = Column(Text, nullable=False)
    attachment_filename = Column(String(255), nullable=False)
    attachment_mime = Column(String(255), nullable=False)
    attachment_size = Column(BigInteger, nullable=True)
    cerp_code_full = Column(String(64), nullable=True, index=True)
    cerp_code_family = Column(String(64), nullable=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by_username = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
