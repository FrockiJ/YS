"""Add phase 2 feedback review fields."""

from alembic import op
import sqlalchemy as sa

revision = "0011_feedback_phase2"
down_revision = "0010_add_file_resource_visibility_department"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_feedback", sa.Column("case_id", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("review_status", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("reviewed_by", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("search_feedback", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("search_feedback", sa.Column("dataset_split", sa.Text(), nullable=True))
    op.create_index("ix_search_feedback_case_id", "search_feedback", ["case_id"], unique=False)
    op.create_index("ix_search_feedback_review_status", "search_feedback", ["review_status"], unique=False)
    op.create_index("ix_search_feedback_dataset_split", "search_feedback", ["dataset_split"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_search_feedback_dataset_split", table_name="search_feedback")
    op.drop_index("ix_search_feedback_review_status", table_name="search_feedback")
    op.drop_index("ix_search_feedback_case_id", table_name="search_feedback")
    op.drop_column("search_feedback", "dataset_split")
    op.drop_column("search_feedback", "review_note")
    op.drop_column("search_feedback", "reviewed_at")
    op.drop_column("search_feedback", "reviewed_by")
    op.drop_column("search_feedback", "review_status")
    op.drop_column("search_feedback", "case_id")
