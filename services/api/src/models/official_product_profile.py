from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from ..core.models import Base


class OfficialProductProfile(Base):
    __tablename__ = "official_product_profiles"

    id = Column(Integer, primary_key=True, index=True)
    product_handle = Column(Text, nullable=False, unique=True, index=True)
    product_title = Column(Text, nullable=False)
    producer = Column(Text, nullable=True, index=True)
    product_type = Column(Text, nullable=True)
    official_url = Column(Text, nullable=False)
    product_json_hash = Column(Text, nullable=True)
    availability = Column(Boolean, nullable=True)
    price_min = Column(Float, nullable=True)
    price_max = Column(Float, nullable=True)
    images_json = Column(JSONB, nullable=False, default=list)
    variants_json = Column(JSONB, nullable=False, default=list)
    tags_json = Column(JSONB, nullable=False, default=list)
    description_html = Column(Text, nullable=True)
    description_text = Column(Text, nullable=True)
    search_terms_json = Column(JSONB, nullable=False, default=list)
    source_payload_json = Column(JSONB, nullable=False, default=dict)
    source_tier = Column(Text, nullable=False, default="internal_official")
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
