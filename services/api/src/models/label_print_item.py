import uuid

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from ..core.database import Base


class LabelPrintItem(Base):
    __tablename__ = "label_print_items"
    __table_args__ = (
        UniqueConstraint("user_id", "product_code", "size", name="uq_label_print_user_product_size"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_code = Column(String(64), nullable=False, index=True)
    size = Column(String(16), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    price_override = Column(Integer, nullable=True)
    product_snapshot = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
