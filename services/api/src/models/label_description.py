import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from ..core.database import Base


class LabelDescription(Base):
    __tablename__ = "label_descriptions"
    __table_args__ = (
        UniqueConstraint("product_code", "lang", name="uq_label_desc_code_lang"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_code = Column(String(64), nullable=False, index=True)
    lang = Column(String(16), nullable=False, default="zh-TW")
    description = Column(Text, nullable=False)
    price_override = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
