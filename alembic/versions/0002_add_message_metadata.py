"""Add metadata column to messages."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_add_message_metadata"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "metadata")
