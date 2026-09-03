-- Project facts table: replaces the file-based ProjectContext.md system.
--
-- One row per project (hash of absolute path, same scheme as before).
-- identity/key_files/structure come from project_scan; learnings is a
-- capped JSONB list of {ts, intent, target, summary} appended after
-- each meaningful turn (all intents, not just explain-path).

CREATE TABLE IF NOT EXISTS project_contexts (
    project_hash TEXT PRIMARY KEY,
    project_path TEXT NOT NULL DEFAULT '',
    identity JSONB NOT NULL DEFAULT '{}',
    key_files JSONB NOT NULL DEFAULT '[]',
    structure TEXT NOT NULL DEFAULT '',
    learnings JSONB NOT NULL DEFAULT '[]',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
