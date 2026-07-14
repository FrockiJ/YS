"""Add department_role and visibility to file_resources."""

from alembic import op

revision = "0010_add_file_resource_visibility_department"
down_revision = "0009_add_file_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE file_resources
        ADD COLUMN IF NOT EXISTS department_role VARCHAR(100)
        """
    )
    op.execute(
        """
        ALTER TABLE file_resources
        ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) NOT NULL DEFAULT 'public'
        """
    )
    op.execute(
        """
        UPDATE file_resources
        SET visibility = 'public'
        WHERE visibility IS NULL OR LOWER(COALESCE(visibility, '')) NOT IN ('private', 'public')
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_resources_department_role ON file_resources(department_role)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_resources_visibility ON file_resources(visibility)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_file_resources_type_visibility_department "
        "ON file_resources(resource_type, visibility, department_role)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_file_resources_type_visibility_department")
    op.execute("DROP INDEX IF EXISTS ix_file_resources_visibility")
    op.execute("DROP INDEX IF EXISTS ix_file_resources_department_role")
    op.execute("ALTER TABLE file_resources DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE file_resources DROP COLUMN IF EXISTS department_role")
