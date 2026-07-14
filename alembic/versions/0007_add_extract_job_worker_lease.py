"""Add extract_jobs worker lease fields."""

from alembic import op

revision = "0007_extract_job_worker_lease"
down_revision = "0006_extract_jobs_rap_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE extract_jobs
        ADD COLUMN IF NOT EXISTS worker_id TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE extract_jobs
        ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        ALTER TABLE extract_jobs
        ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        ALTER TABLE extract_jobs
        ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE extract_jobs
        ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 2
        """
    )
    op.execute("UPDATE extract_jobs SET attempt_count = COALESCE(attempt_count, 0)")
    op.execute("UPDATE extract_jobs SET max_attempts = COALESCE(max_attempts, 2)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_extract_jobs_worker_id ON extract_jobs(worker_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_extract_jobs_lease_expires_at ON extract_jobs(lease_expires_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_extract_jobs_lease_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_extract_jobs_worker_id")
    op.execute("ALTER TABLE extract_jobs DROP COLUMN IF EXISTS max_attempts")
    op.execute("ALTER TABLE extract_jobs DROP COLUMN IF EXISTS attempt_count")
    op.execute("ALTER TABLE extract_jobs DROP COLUMN IF EXISTS lease_expires_at")
    op.execute("ALTER TABLE extract_jobs DROP COLUMN IF EXISTS heartbeat_at")
    op.execute("ALTER TABLE extract_jobs DROP COLUMN IF EXISTS worker_id")
