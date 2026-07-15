"""Knowledge-first phase 1: additive outdoor-general schema and backfill."""

from alembic import op
import sqlalchemy as sa

revision = "0012_knowledge_first_phase1"
down_revision = "0011_feedback_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_state JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_version VARCHAR(32) NOT NULL DEFAULT 'outdoor-v1'")

    op.execute("ALTER TABLE official_product_profiles ADD COLUMN IF NOT EXISTS brand TEXT")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='official_product_profiles'
                  AND column_name='producer'
            ) THEN
                EXECUTE 'UPDATE official_product_profiles SET brand = producer WHERE brand IS NULL';
            END IF;
        END
        $$
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_official_product_profiles_brand ON official_product_profiles(brand)")

    op.execute("ALTER TABLE file_resources ADD COLUMN IF NOT EXISTS brand VARCHAR(255)")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='file_resources'
                  AND column_name='producer'
            ) THEN
                EXECUTE 'UPDATE file_resources SET brand = producer WHERE brand IS NULL';
            END IF;
        END
        $$
        """
    )
    op.execute("UPDATE file_resources SET resource_type = 'product_label' WHERE resource_type = 'wine_label'")
    op.alter_column("file_resources", "resource_type", server_default="product_label")
    op.execute("CREATE INDEX IF NOT EXISTS ix_file_resources_brand ON file_resources(brand)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS brand_source_domains (
            id SERIAL PRIMARY KEY,
            brand_name_raw TEXT NOT NULL,
            brand_name_normalized TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            domain TEXT,
            source_tier TEXT NOT NULL,
            source_origin TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            region_scope TEXT,
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_brand_source_domains_brand_name_normalized ON brand_source_domains(brand_name_normalized)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_brand_source_domains_domain ON brand_source_domains(domain)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_brand_source_domains_verification_status ON brand_source_domains(verification_status)")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.producer_source_domains') IS NOT NULL THEN
                INSERT INTO brand_source_domains (
                    brand_name_raw, brand_name_normalized, source_kind, domain, source_tier,
                    source_origin, verification_status, region_scope, notes, created_at, updated_at
                )
                SELECT producer_name_raw, producer_name_normalized, source_kind, domain, source_tier,
                       source_origin, verification_status, region_scope, notes, created_at, updated_at
                FROM producer_source_domains;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_index("ix_brand_source_domains_verification_status", table_name="brand_source_domains")
    op.drop_index("ix_brand_source_domains_domain", table_name="brand_source_domains")
    op.drop_index("ix_brand_source_domains_brand_name_normalized", table_name="brand_source_domains")
    op.drop_table("brand_source_domains")
    op.drop_index("ix_file_resources_brand", table_name="file_resources")
    op.drop_column("file_resources", "brand")
    op.drop_index("ix_official_product_profiles_brand", table_name="official_product_profiles")
    op.drop_column("official_product_profiles", "brand")
    op.drop_column("conversations", "context_version")
    op.drop_column("conversations", "context_state")
