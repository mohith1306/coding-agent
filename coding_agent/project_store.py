"""Project facts store — Postgres-backed replacement for ProjectContext.md.

One row per project (sha256 of absolute path, same hashing as the old
file system for continuity). Facts (identity/key files/structure) come
from the shared project_scan module; learnings accumulate from every
meaningful turn across all intents.

All methods are offline-safe: any database failure logs and degrades
to empty facts / dropped learnings so context building never crashes
without a database (tests, InMemory mode).
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .db import get_connection, return_connection
from .project_scan import scan_project


logger = logging.getLogger(__name__)

MAX_LEARNINGS = 20
MIN_RESPONSE_CHARS = 50


def project_hash(root: Path) -> str:
    """Stable hash identifying a project (matches legacy scheme)."""
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _learning_entry(intent: str, target: str, user_message: str, agent_response: str) -> Optional[dict]:
    """Build a learning entry for a turn; None when not worth recording."""
    if not agent_response or len(agent_response) < MIN_RESPONSE_CHARS:
        return None
    entry: dict[str, Any] = {
        "ts": _utcnow(),
        "intent": intent,
        "target": (target or "")[:200],
    }
    if intent in {"explain", "unknown"} and len(agent_response) > 100:
        entry["summary"] = f"Asked: {user_message[:200]} | {agent_response[:500]}"
    elif intent in {"create_file", "create_files", "create_project"}:
        entry["summary"] = f"Created {target or 'files'}: {user_message[:200]}"
    elif intent == "modify_code":
        entry["summary"] = f"Modified {target}: {user_message[:200]}"
    elif intent in {"read_file", "search_files"}:
        entry["summary"] = f"Examined {target or user_message[:100]}"
    else:
        entry["summary"] = f"{intent} {target}: {user_message[:200]}"
    return entry


class ProjectStore:
    """Reads/writes project facts in the project_contexts table."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.hash = project_hash(self.root)

    def get_or_create(self) -> dict:
        """Return facts for this project, scanning + inserting on first use."""
        try:
            row = self._fetch()
            if row is not None:
                return row
            return self._create()
        except Exception as error:
            logger.warning("Project facts unavailable, omitting: %s", error)
            return {}

    def record_learning(
        self,
        intent: str,
        target: str,
        user_message: str,
        agent_response: str,
    ) -> None:
        """Append a learning entry (capped); no-op on trivial turns or DB errors."""
        entry = _learning_entry(intent, target or "", user_message, agent_response)
        if entry is None:
            return
        conn = None
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT learnings FROM project_contexts WHERE project_hash = %s",
                    (self.hash,),
                )
                row = cur.fetchone()
            if row is None:
                # No facts row yet (learnings before first build): create
                # facts first so the learning has a home.
                conn.rollback()
                return_connection(conn)
                conn = None
                self._create()
                conn = get_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT learnings FROM project_contexts WHERE project_hash = %s",
                        (self.hash,),
                    )
                    row = cur.fetchone()
            learnings = list(row[0] or []) if row else []
            learnings.append(entry)
            learnings = learnings[-MAX_LEARNINGS:]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE project_contexts
                    SET learnings = %s::jsonb, updated_at = NOW()
                    WHERE project_hash = %s
                    """,
                    (json.dumps(learnings), self.hash),
                )
            conn.commit()
        except Exception as error:
            logger.warning("Failed to record learning, dropping: %s", error)
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            if conn is not None:
                return_connection(conn)

    @staticmethod
    def format_for_prompt(facts: dict) -> str:
        """Render facts as prompt text (empty string when no facts)."""
        if not facts:
            return ""
        parts = []
        identity = facts.get("identity", {})
        if identity.get("language"):
            parts.append(f"**Language**: {identity['language']}")
        configs = []
        if identity.get("has_test_config"):
            configs.append("tests")
        if identity.get("has_lint_config"):
            configs.append("lint")
        if identity.get("has_typecheck_config"):
            configs.append("typecheck")
        if configs:
            parts.append(f"**Config**: {', '.join(configs)}")
        key_files = facts.get("key_files", [])
        if key_files:
            parts.append("## Key Files")
            for item in key_files[:15]:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    parts.append(f"- `{item[0]}` ({item[1]})")
        if facts.get("structure"):
            parts.append("## Structure")
            parts.append(str(facts["structure"]))
        learnings = facts.get("learnings", [])
        if learnings:
            parts.append("## Learnings")
            for entry in learnings[-10:]:
                parts.append(f"- [{entry.get('ts', '')}] {entry.get('summary', '')}")
        if not parts:
            return ""
        return "\n--- Project Context (from previous sessions) ---\n" + "\n".join(parts)

    # -- internals --

    def _fetch(self) -> Optional[dict]:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT identity, key_files, structure, learnings
                    FROM project_contexts WHERE project_hash = %s
                    """,
                    (self.hash,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            identity, key_files, structure, learnings = row
            return {
                "identity": identity or {},
                "key_files": key_files or [],
                "structure": structure or "",
                "learnings": learnings or [],
            }
        finally:
            return_connection(conn)

    def _create(self) -> dict:
        scan = scan_project(self.root)
        identity = {
            "language": scan.identity.language,
            "has_test_config": scan.identity.has_test_config,
            "has_lint_config": scan.identity.has_lint_config,
            "has_typecheck_config": scan.identity.has_typecheck_config,
        }
        key_files = [[p, k] for p, k in scan.key_files]
        facts = {
            "identity": identity,
            "key_files": key_files,
            "structure": scan.structure,
            "learnings": [],
        }
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO project_contexts
                        (project_hash, project_path, identity, key_files, structure, learnings)
                    VALUES (%s, %s, %s, %s, %s, '[]')
                    ON CONFLICT (project_hash) DO NOTHING
                    """,
                    (
                        self.hash,
                        str(self.root),
                        json.dumps(identity),
                        json.dumps(key_files),
                        scan.structure,
                    ),
                )
            conn.commit()
        finally:
            return_connection(conn)
        return facts
