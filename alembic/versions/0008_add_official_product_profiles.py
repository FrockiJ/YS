"""Add official_product_profiles table."""

from alembic import op

revision = "0008_official_product_profiles"
down_revision = "0007_extract_job_worker_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS official_product_profiles (
            id SERIAL PRIMARY KEY,
            product_handle TEXT NOT NULL,
            product_title TEXT NOT NULL,
            producer TEXT,
            product_type TEXT,
            official_url TEXT NOT NULL,
            product_json_hash TEXT,
            availability BOOLEAN,
            price_min DOUBLE PRECISION,
            price_max DOUBLE PRECISION,
            images_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            variants_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            description_html TEXT,
            description_text TEXT,
            search_terms_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_tier TEXT NOT NULL DEFAULT 'internal_official',
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_official_product_profiles_handle ON official_product_profiles(product_handle)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_official_product_profiles_producer ON official_product_profiles(producer)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_official_product_profiles_active ON official_product_profiles(is_active)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_official_product_profiles_active")
    op.execute("DROP INDEX IF EXISTS ix_official_product_profiles_producer")
    op.execute("DROP INDEX IF EXISTS uq_official_product_profiles_handle")
    op.execute("DROP TABLE IF EXISTS official_product_profiles")
