import uuid

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from ..core.models import Base


class ExtractJob(Base):
    __tablename__ = "extract_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(Text, nullable=False, default="extract")
    source_scope = Column(Text, nullable=False)
    file_types = Column(JSONB, nullable=False, default=list)
    rebuild_mode = Column(Text, nullable=False, default="incremental")
    input_roots = Column(JSONB, nullable=False, default=list)
    status = Column(Text, nullable=False, default="queued")
    requested_by = Column(Text, nullable=True)
    worker_id = Column(Text, nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=2)
    total_files = Column(Integer, nullable=False, default=0)
    processed_files = Column(Integer, nullable=False, default=0)
    success_files = Column(Integer, nullable=False, default=0)
    failed_files = Column(Integer, nullable=False, default=0)
    request_payload = Column(JSONB, nullable=False, default=dict)
    summary = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
