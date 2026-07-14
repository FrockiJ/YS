
-- Base schema for YS AI (pgvector + JSONB)
CREATE TABLE IF NOT EXISTS documents (
  id SERIAL PRIMARY KEY,
  filename TEXT NOT NULL,
  filetype TEXT,
  meta JSONB DEFAULT '{}'::jsonb,
  file_mtime TIMESTAMPTZ,
  filesize BIGINT,
  checksum TEXT,
  created_at TIMESTAMP DEFAULT now()
);

-- chunks table: text + embedding vector(384)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns WHERE table_name='chunks' AND column_name='embedding'
  ) THEN
    CREATE TABLE chunks (
      id BIGSERIAL PRIMARY KEY,
      document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
      chunk_idx INTEGER NOT NULL,
      text TEXT NOT NULL,
      meta JSONB DEFAULT '{}'::jsonb,
      embedding vector(384),
      created_at TIMESTAMP DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
    CREATE INDEX IF NOT EXISTS idx_chunks_vec ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
  END IF;
END $$;

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS keywords TEXT[];
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS kg JSONB DEFAULT '{}'::jsonb;
CREATE INDEX IF NOT EXISTS idx_chunks_keywords ON chunks USING GIN(keywords);

-- Named entities extracted from chunks
CREATE TABLE IF NOT EXISTS entities (
  id BIGSERIAL PRIMARY KEY,
  chunk_id BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
  type TEXT,
  value TEXT,
  normalized TEXT,
  confidence REAL,
  meta JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entities_norm ON entities(normalized);

-- Alias table
CREATE TABLE IF NOT EXISTS alias (
  id BIGSERIAL PRIMARY KEY,
  canonical TEXT NOT NULL,
  variant TEXT NOT NULL,
  type TEXT,
  lang TEXT,
  source TEXT,
  confidence REAL,
  created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alias_variant ON alias(variant);
CREATE INDEX IF NOT EXISTS idx_alias_canonical ON alias(canonical);

-- Error / low-confidence log
CREATE TABLE IF NOT EXISTS errors (
  id BIGSERIAL PRIMARY KEY,
  document_id INTEGER,
  chunk_id BIGINT,
  stage TEXT,
  field TEXT,
  reason TEXT,
  detail JSONB,
  created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_log (
  id BIGSERIAL PRIMARY KEY,
  filename TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  filesize BIGINT,
  file_mtime TIMESTAMPTZ,
  checksum TEXT,
  created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ingest_log_file ON ingest_log(filename);
