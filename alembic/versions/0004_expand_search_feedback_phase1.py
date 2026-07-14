"""Expand search_feedback for phase 1 grounding and tuning logs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_feedback_phase1"
down_revision = "0003_rename_message_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_feedback", sa.Column("conversation_id", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("message_id", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("prompt_category", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("issue_tags", postgresql.JSONB(), nullable=True))
    op.add_column("search_feedback", sa.Column("correction_text", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("grounding", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("source_quality", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("attachment_type", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("preferred_answer", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("retrieval_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("search_feedback", sa.Column("answer_metadata_snapshot", postgresql.JSONB(), nullable=True))
    op.create_index("ix_search_feedback_conversation_id", "search_feedback", ["conversation_id"], unique=False)
    op.create_index("ix_search_feedback_message_id", "search_feedback", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_search_feedback_message_id", table_name="search_feedback")
    op.drop_index("ix_search_feedback_conversation_id", table_name="search_feedback")
    op.drop_column("search_feedback", "answer_metadata_snapshot")
    op.drop_column("search_feedback", "retrieval_snapshot")
    op.drop_column("search_feedback", "preferred_answer")
    op.drop_column("search_feedback", "attachment_type")
    op.drop_column("search_feedback", "source_quality")
    op.drop_column("search_feedback", "grounding")
    op.drop_column("search_feedback", "correction_text")
    op.drop_column("search_feedback", "issue_tags")
    op.drop_column("search_feedback", "prompt_category")
    op.drop_column("search_feedback", "message_id")
    op.drop_column("search_feedback", "conversation_id")
