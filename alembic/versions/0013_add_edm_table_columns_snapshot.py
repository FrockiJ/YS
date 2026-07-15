"""Persist the Quote-view column snapshot used by EDM previews."""

from alembic import op


revision = "0013_edm_table_columns_snapshot"
down_revision = "0012_knowledge_first_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE edm_previews "
        "ADD COLUMN IF NOT EXISTS table_columns_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE edm_previews DROP COLUMN IF EXISTS table_columns_snapshot")
