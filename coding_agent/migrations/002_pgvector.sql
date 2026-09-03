-- pgvector support for semantic memory retrieval.
--
-- Graceful degradation: if the `vector` extension is unavailable
-- (older Postgres, restricted cloud instance), the DO block swallows
-- the error and the embedding column/index are skipped. Python detects
-- this at runtime (pg_extension check) and falls back to keyword search.
-- The migration itself never fails for a missing extension.

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pgvector unavailable, skipping vector column: %', SQLERRM;
END
$$;

-- Capability flag so runtime can check without probing pg_extension each time.
CREATE TABLE IF NOT EXISTS db_capabilities (
    name TEXT PRIMARY KEY,
    available BOOLEAN NOT NULL DEFAULT FALSE,
    detail TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

DO $$
DECLARE
    has_vector BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_vector;

    INSERT INTO db_capabilities (name, available, detail, updated_at)
    VALUES ('pgvector', has_vector,
            CASE WHEN has_vector THEN 'vector extension installed' ELSE 'vector extension unavailable' END,
            NOW())
    ON CONFLICT (name) DO UPDATE SET
        available = EXCLUDED.available,
        detail = EXCLUDED.detail,
        updated_at = NOW();

    -- NOTE: the embedding column itself is created by application code
    -- (db.ensure_vector_column) because its dimension follows the
    -- configured embedding model (CODING_AGENT_EMBED_DIM). Creating it
    -- here would lock the dimension at migration time.
END
$$;
