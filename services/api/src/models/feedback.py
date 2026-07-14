from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from ..core.models import Base


class SearchFeedback(Base):
    __tablename__ = "search_feedback"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text, nullable=False)
    selected_key = Column(Text, nullable=True)
    feedback_type = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_id = Column(Integer, nullable=True, index=True)
    case_id = Column(Text, nullable=True, index=True)
    conversation_id = Column(Text, nullable=True, index=True)
    message_id = Column(Text, nullable=True, index=True)
    prompt_category = Column(Text, nullable=True)
    issue_tags = Column(JSONB, nullable=True)
    correction_text = Column(Text, nullable=True)
    grounding = Column(Text, nullable=True)
    source_quality = Column(Text, nullable=True)
    attachment_type = Column(Text, nullable=True)
    preferred_answer = Column(Text, nullable=True)
    retrieval_snapshot = Column(JSONB, nullable=True)
    answer_metadata_snapshot = Column(JSONB, nullable=True)
    review_status = Column(Text, nullable=True, index=True)
    reviewed_by = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_note = Column(Text, nullable=True)
    dataset_split = Column(Text, nullable=True, index=True)
