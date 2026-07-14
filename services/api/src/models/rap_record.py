from sqlalchemy import Column, DateTime, Float, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from ..core.models import Base


class RapRecord(Base):
    __tablename__ = "rap_records"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, nullable=True, index=True)
    record_key = Column(Text, nullable=False, unique=True)
    source_file = Column(Text, nullable=False, index=True)
    source_sheet = Column(Text, nullable=False)
    source_row = Column(Integer, nullable=False)
    source_site = Column(Text, nullable=False, index=True)
    producer = Column(Text, nullable=True, index=True)
    wine_name = Column(Text, nullable=True)
    full_wine_name = Column(Text, nullable=True)
    vintage = Column(Text, nullable=True)
    region = Column(Text, nullable=True, index=True)
    country = Column(Text, nullable=True)
    appellation = Column(Text, nullable=True)
    classification = Column(Text, nullable=True)
    vineyard_name = Column(Text, nullable=True)
    wine_color = Column(Text, nullable=True)
    grape_blend = Column(Text, nullable=True)
    score_raw = Column(Text, nullable=True)
    score_numeric = Column(Float, nullable=True)
    reviewer = Column(Text, nullable=True)
    reviewer_title = Column(Text, nullable=True)
    drinking_window = Column(Text, nullable=True)
    drink_date = Column(Text, nullable=True)
    tasting_note = Column(Text, nullable=True)
    producer_note = Column(Text, nullable=True)
    published_date = Column(Text, nullable=True)
    tasting_date = Column(Text, nullable=True)
    selling_price = Column(Text, nullable=True)
    page_url = Column(Text, nullable=True)
    image_urls = Column(JSONB, nullable=False, default=list)
    raw_row = Column(JSONB, nullable=False, default=dict)
    mapped_fields = Column(JSONB, nullable=False, default=dict)
    unmapped_fields = Column(JSONB, nullable=False, default=dict)
    mapping_confidence = Column(Float, nullable=True)
    schema_version = Column(Text, nullable=False, default="rap_tabular_hybrid_v1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
