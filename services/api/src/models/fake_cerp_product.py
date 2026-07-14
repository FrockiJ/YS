from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from ..core.database import Base


class FakeCerpProduct(Base):
    __tablename__ = "fake_cerp_products"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(Text, nullable=False, default="", server_default="")
    spec1 = Column(String(255), nullable=True)
    amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    stock = Column(Integer, nullable=False, default=0, server_default="0")
    raw_row = Column(JSONB, nullable=False, default=dict)
    imported_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
