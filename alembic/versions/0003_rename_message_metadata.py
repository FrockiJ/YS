"""Rename metadata column to message_metadata."""

from alembic import op

revision = "0003_rename_message_metadata"
down_revision = "0002_add_message_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("messages", "metadata", new_column_name="message_metadata")


def downgrade() -> None:
    op.alter_column("messages", "message_metadata", new_column_name="metadata")
