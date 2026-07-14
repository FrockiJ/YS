"""Add extract_jobs and rap_records tables."""

from alembic import op

revision = "0006_extract_jobs_rap_records"
down_revision = "0005_producer_source_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS extract_jobs (
            id UUID PRIMARY KEY,
            job_type TEXT NOT NULL DEFAULT 'extract',
            source_scope TEXT NOT NULL,
            file_types JSONB NOT NULL DEFAULT '[]'::jsonb,
            rebuild_mode TEXT NOT NULL DEFAULT 'incremental',
            input_roots JSONB NOT NULL DEFAULT '[]'::jsonb,
            status TEXT NOT NULL DEFAULT 'queued',
            requested_by TEXT,
            total_files INTEGER NOT NULL DEFAULT 0,
            processed_files INTEGER NOT NULL DEFAULT 0,
            success_files INTEGER NOT NULL DEFAULT 0,
            failed_files INTEGER NOT NULL DEFAULT 0,
            request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            summary JSONB,
            error TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_extract_jobs_status ON extract_jobs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_extract_jobs_created_at ON extract_jobs(created_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rap_records (
            id SERIAL PRIMARY KEY,
            document_id INTEGER,
            record_key TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_sheet TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            source_site TEXT NOT NULL,
            producer TEXT,
            wine_name TEXT,
            full_wine_name TEXT,
            vintage TEXT,
            region TEXT,
            country TEXT,
            appellation TEXT,
            classification TEXT,
            vineyard_name TEXT,
            wine_color TEXT,
            grape_blend TEXT,
            score_raw TEXT,
            score_numeric DOUBLE PRECISION,
            reviewer TEXT,
            reviewer_title TEXT,
            drinking_window TEXT,
            drink_date TEXT,
            tasting_note TEXT,
            producer_note TEXT,
            published_date TEXT,
            tasting_date TEXT,
            selling_price TEXT,
            page_url TEXT,
            image_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
            raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,
            mapped_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            unmapped_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            mapping_confidence DOUBLE PRECISION,
            schema_version TEXT NOT NULL DEFAULT 'rap_tabular_hybrid_v1',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_rap_records_record_key ON rap_records(record_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rap_records_document_id ON rap_records(document_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rap_records_source_file ON rap_records(source_file)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rap_records_source_site ON rap_records(source_site)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rap_records_producer ON rap_records(producer)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rap_records_region ON rap_records(region)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rap_records_region")
    op.execute("DROP INDEX IF EXISTS ix_rap_records_producer")
    op.execute("DROP INDEX IF EXISTS ix_rap_records_source_site")
    op.execute("DROP INDEX IF EXISTS ix_rap_records_source_file")
    op.execute("DROP INDEX IF EXISTS ix_rap_records_document_id")
    op.execute("DROP INDEX IF EXISTS uq_rap_records_record_key")
    op.execute("DROP TABLE IF EXISTS rap_records")
    op.execute("DROP INDEX IF EXISTS ix_extract_jobs_created_at")
    op.execute("DROP INDEX IF EXISTS ix_extract_jobs_status")
    op.execute("DROP TABLE IF EXISTS extract_jobs")
