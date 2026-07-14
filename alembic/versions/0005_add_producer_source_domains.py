"""Add producer_source_domains table for authoritative seeds."""

from alembic import op
import sqlalchemy as sa

revision = "0005_producer_source_domains"
down_revision = "0004_feedback_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "producer_source_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("producer_name_raw", sa.Text(), nullable=False),
        sa.Column("producer_name_normalized", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("source_tier", sa.Text(), nullable=False),
        sa.Column("source_origin", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column("region_scope", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
    )
    op.create_index(
        "ix_producer_source_domains_producer_name_normalized",
        "producer_source_domains",
        ["producer_name_normalized"],
        unique=False,
    )
    op.create_index(
        "ix_producer_source_domains_domain",
        "producer_source_domains",
        ["domain"],
        unique=False,
    )
    op.create_index(
        "ix_producer_source_domains_verification_status",
        "producer_source_domains",
        ["verification_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_producer_source_domains_verification_status", table_name="producer_source_domains")
    op.drop_index("ix_producer_source_domains_domain", table_name="producer_source_domains")
    op.drop_index("ix_producer_source_domains_producer_name_normalized", table_name="producer_source_domains")
    op.drop_table("producer_source_domains")
