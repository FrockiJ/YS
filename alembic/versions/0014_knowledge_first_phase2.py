"""Knowledge-first phase 2: remove retired domain compatibility schema."""

from alembic import op


revision = "0014_knowledge_first_phase2"
down_revision = "0013_edm_table_columns_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Refuse the destructive step if phase-one backfills are incomplete.
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
                IF EXISTS (
                    SELECT 1
                    FROM official_product_profiles
                    WHERE producer IS NOT NULL AND brand IS NULL
                ) THEN
                    RAISE EXCEPTION 'official_product_profiles brand backfill is incomplete';
                END IF;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='file_resources'
                  AND column_name='producer'
            ) THEN
                IF EXISTS (
                    SELECT 1
                    FROM file_resources
                    WHERE producer IS NOT NULL AND brand IS NULL
                ) THEN
                    RAISE EXCEPTION 'file_resources brand backfill is incomplete';
                END IF;
            END IF;
        END
        $$
        """
    )
    op.execute("ALTER TABLE official_product_profiles DROP COLUMN IF EXISTS producer")
    op.execute("ALTER TABLE file_resources DROP COLUMN IF EXISTS producer")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS has_wine_cabinet")
    op.execute("DROP TABLE IF EXISTS rap_records CASCADE")
    op.execute("DROP TABLE IF EXISTS producer_source_domains CASCADE")


def downgrade() -> None:
    # Only compatibility columns are recreated. Removed domain records are not
    # regenerated because phase two intentionally discards that retired data.
    op.execute("ALTER TABLE official_product_profiles ADD COLUMN IF NOT EXISTS producer TEXT")
    op.execute("UPDATE official_product_profiles SET producer = brand WHERE producer IS NULL")
    op.execute("ALTER TABLE file_resources ADD COLUMN IF NOT EXISTS producer VARCHAR(255)")
    op.execute("UPDATE file_resources SET producer = brand WHERE producer IS NULL")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS has_wine_cabinet BOOLEAN NOT NULL DEFAULT false")
