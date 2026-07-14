"""Add file_resources table."""

from alembic import op

revision = "0009_add_file_resources"
down_revision = "0008_official_product_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS file_resources (
            id UUID PRIMARY KEY,
            resource_type VARCHAR(32) NOT NULL DEFAULT 'wine_label',
            display_name VARCHAR(255) NOT NULL,
            producer VARCHAR(255),
            attachment_path TEXT NOT NULL,
            attachment_filename VARCHAR(255) NOT NULL,
            attachment_mime VARCHAR(255) NOT NULL,
            attachment_size BIGINT,
            cerp_code_full VARCHAR(64),
            cerp_code_family VARCHAR(64),
            created_by_user_id INTEGER REFERENCES users(id),
            created_by_username VARCHAR(255),
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_resources_type ON file_resources(resource_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_resources_cerp_code_full ON file_resources(cerp_code_full)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_resources_cerp_code_family ON file_resources(cerp_code_family)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_resources_created_by_user_id ON file_resources(created_by_user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_file_resources_created_by_user_id")
    op.execute("DROP INDEX IF EXISTS ix_file_resources_cerp_code_family")
    op.execute("DROP INDEX IF EXISTS ix_file_resources_cerp_code_full")
    op.execute("DROP INDEX IF EXISTS ix_file_resources_type")
    op.execute("DROP TABLE IF EXISTS file_resources")
