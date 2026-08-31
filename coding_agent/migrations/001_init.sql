-- Agent memory schema for PostgreSQL
-- Replaces ChromaDB collection with proper relational tables

CREATE TABLE IF NOT EXISTS agent_memory (
    id UUID PRIMARY KEY,
    doc_type VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for filtering by document type
CREATE INDEX IF NOT EXISTS idx_memory_doc_type ON agent_memory(doc_type);

-- GIN index for JSONB metadata queries
CREATE INDEX IF NOT EXISTS idx_memory_metadata ON agent_memory USING GIN(metadata);

-- Index for timestamp-based queries (recent turns)
CREATE INDEX IF NOT EXISTS idx_memory_created_at ON agent_memory(created_at DESC);

-- Composite index for doc_type + timestamp (common query pattern)
CREATE INDEX IF NOT EXISTS idx_memory_doc_type_ts ON agent_memory(doc_type, created_at DESC);
