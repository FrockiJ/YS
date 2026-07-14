from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from ..core.models import Base


class ProducerSourceDomain(Base):
    __tablename__ = "producer_source_domains"

    id = Column(Integer, primary_key=True, index=True)
    producer_name_raw = Column(Text, nullable=False)
    producer_name_normalized = Column(Text, nullable=False, index=True)
    source_kind = Column(Text, nullable=False)
    domain = Column(Text, nullable=True, index=True)
    source_tier = Column(Text, nullable=False)
    source_origin = Column(Text, nullable=False)
    verification_status = Column(Text, nullable=False, index=True)
    region_scope = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
