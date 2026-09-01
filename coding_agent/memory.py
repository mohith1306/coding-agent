"""Memory store backed by PostgreSQL.

Provides the same public API as the previous ChromaDB implementation.
Vector search (retrieve_similar) is stubbed out for now - will be added
later when pgvector embeddings are implemented.
"""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor, Json

from .db import get_connection, return_connection, init_db


logger = logging.getLogger(__name__)


class MemoryStore:
    """PostgreSQL-backed memory store for agent context."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        """Initialize the memory store.

        Args:
            storage_dir: Unused, kept for API compatibility.
        """
        try:
            init_db()
        except Exception as error:
            logger.warning("Database initialization failed: %s", error)
            raise

        self._last_ts = 0.0

    def _next_timestamp(self) -> float:
        """Generate a monotonically increasing timestamp."""
        now = time.time()
        if now <= self._last_ts:
            now = self._last_ts + 1e-6
        self._last_ts = now
        return now

    # -- chat turns --

    def add_turn(
        self,
        user_message: str,
        agent_response: str,
        intent: str = "",
        target: str = "",
    ) -> None:
        """Store a conversation turn."""
        doc_id = str(uuid.uuid4())
        metadata = {
            "doc_type": "chat",
            "role": "user",
            "content": user_message[:1000],
            "agent_response": agent_response[:2000],
            "intent": intent,
            "target": target,
            "timestamp": self._next_timestamp(),
        }

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memory (id, doc_type, content, metadata)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        doc_id,
                        "chat",
                        f"User: {user_message}\nAgent: {agent_response}",
                        Json(metadata),
                    ),
                )
            conn.commit()
        except Exception as error:
            conn.rollback()
            logger.warning("Failed to add turn: %s", error)
        finally:
            return_connection(conn)

    def recent_turns(self, limit: int = 5) -> list[dict[str, str]]:
        """Get recent chat turns ordered by timestamp."""
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT metadata
                    FROM agent_memory
                    WHERE doc_type = %s
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    ("chat",),
                )
                rows = cur.fetchall()

            if not rows:
                return []

            entries = []
            for row in rows:
                meta = row["metadata"]
                entries.append({
                    "user": meta.get("content", ""),
                    "agent": meta.get("agent_response", ""),
                    "intent": meta.get("intent", ""),
                    "target": meta.get("target", ""),
                    "_ts": meta.get("timestamp", 0),
                })

            entries.sort(key=lambda e: e["_ts"], reverse=True)
            for e in entries:
                del e["_ts"]
            return entries[:limit]
        except Exception as error:
            logger.warning("Failed to get recent turns: %s", error)
            return []
        finally:
            return_connection(conn)

    # -- file events --

    def add_file_event(
        self, path: str, operation: str, content: str = ""
    ) -> None:
        """Store a file event (create, modify, delete)."""
        doc_id = str(uuid.uuid4())
        text = f"[{operation}] {path}: {content[:500]}"
        metadata = {
            "doc_type": "file",
            "path": path,
            "operation": operation,
            "content_preview": content[:500],
            "timestamp": self._next_timestamp(),
        }

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memory (id, doc_type, content, metadata)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (doc_id, "file", text[:2000], Json(metadata)),
                )
            conn.commit()
        except Exception as error:
            conn.rollback()
            logger.warning("Failed to add file event: %s", error)
        finally:
            return_connection(conn)

    # -- tasks --

    def add_task(
        self,
        description: str,
        status: str = "pending",
        files_affected: Optional[list[str]] = None,
    ) -> None:
        """Store a task event."""
        doc_id = str(uuid.uuid4())
        text = f"[Task: {description}] ({status})"
        metadata = {
            "doc_type": "task",
            "description": description[:500],
            "status": status,
            "files_affected": ",".join(files_affected or []),
            "timestamp": self._next_timestamp(),
        }

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memory (id, doc_type, content, metadata)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (doc_id, "task", text, Json(metadata)),
                )
            conn.commit()
        except Exception as error:
            conn.rollback()
            logger.warning("Failed to add task: %s", error)
        finally:
            return_connection(conn)

    # -- preferences / key-value --

    def set_preference(self, key: str, value: str) -> None:
        """Set a preference (upsert)."""
        doc_id = f"pref_{key}"
        metadata = {
            "doc_type": "preference",
            "key": key,
            "value": value[:1000],
            "timestamp": self._next_timestamp(),
        }

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memory (id, doc_type, content, metadata)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        created_at = NOW()
                    """,
                    (doc_id, "preference", value, Json(metadata)),
                )
            conn.commit()
        except Exception as error:
            conn.rollback()
            logger.warning("Failed to set preference: %s", error)
        finally:
            return_connection(conn)

    def get_preference(self, key: str) -> Optional[str]:
        """Get a preference value by key."""
        doc_id = f"pref_{key}"
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT metadata
                    FROM agent_memory
                    WHERE id = %s
                    """,
                    (doc_id,),
                )
                row = cur.fetchone()

            if row and row["metadata"]:
                return row["metadata"].get("value")
            return None
        except Exception as error:
            logger.warning("Failed to get preference: %s", error)
            return None
        finally:
            return_connection(conn)

    def list_preferences(self, limit: int = 50) -> list[dict[str, str]]:
        """List all preferences."""
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT metadata
                    FROM agent_memory
                    WHERE doc_type = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    ("preference", limit),
                )
                rows = cur.fetchall()

            merged = []
            for row in rows:
                meta = row["metadata"]
                merged.append({
                    "key": meta.get("key", ""),
                    "value": meta.get("value", ""),
                })
            merged.sort(key=lambda p: p["key"])
            return merged
        except Exception as error:
            logger.warning("Failed to list preferences: %s", error)
            return []
        finally:
            return_connection(conn)

    # -- vector retrieval (stubbed for now) --

    def retrieve_similar(
        self,
        query: str,
        k: int = 5,
        doc_type: Optional[str] = None,
        max_distance: float = 0.95,
    ) -> list[dict]:
        """Retrieve similar documents using vector search.

        Currently returns empty - will be implemented with pgvector embeddings.
        """
        logger.info(
            "Vector search (stubbed): query=%s k=%s doc_type=%s",
            query[:80],
            k,
            doc_type,
        )
        return []

    # -- raw filter (no vector) --

    def get_by_type(
        self, doc_type: str, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        """Get documents by type with pagination."""
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, content, metadata
                    FROM agent_memory
                    WHERE doc_type = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (doc_type, limit, offset),
                )
                rows = cur.fetchall()

            merged = []
            for row in rows:
                merged.append({
                    "id": str(row["id"]),
                    "document": row["content"],
                    "metadata": row["metadata"],
                })
            return merged
        except Exception as error:
            logger.warning("Failed to get by type: %s", error)
            return []
        finally:
            return_connection(conn)

    def get_all_by_type(self, doc_type: str) -> list[dict]:
        """Fetch every document of a type."""
        results: list[dict] = []
        offset = 0
        page_size = 300
        while True:
            page = self.get_by_type(doc_type, limit=page_size, offset=offset)
            if not page:
                break
            results.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return results

    def delete_by_ids(self, ids: list[str]) -> None:
        """Delete documents by ID."""
        if not ids:
            return

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM agent_memory
                    WHERE id = ANY(%s)
                    """,
                    (ids,),
                )
            conn.commit()
        except Exception as error:
            conn.rollback()
            logger.warning("Failed to delete by ids: %s", error)
        finally:
            return_connection(conn)


class InMemoryMemoryStore:
    """Fallback in-memory store when PostgreSQL is unavailable.

    Same public API as MemoryStore — data lives only for the process lifetime.
    """

    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._prefs: dict[str, str] = {}
        self._ts = 0.0
        self._next_id = 0

    def _alloc_id(self) -> str:
        self._next_id += 1
        return f"mem_{self._next_id}"

    def _next_timestamp(self) -> float:
        self._ts += 1
        return self._ts

    def add_turn(self, user_message: str, agent_response: str, intent: str = "", target: str = "") -> None:
        doc_text = f"User: {user_message}\nAgent: {agent_response}"
        self._rows.append({
            "id": self._alloc_id(),
            "doc_type": "chat",
            "document": doc_text[:2000],
            "metadata": {
                "doc_type": "chat",
                "content": user_message[:1000], "agent_response": agent_response[:2000],
                "intent": intent, "target": target, "timestamp": self._next_timestamp(),
            },
        })

    def recent_turns(self, limit: int = 5) -> list[dict[str, str]]:
        chats = [r for r in self._rows if r["doc_type"] == "chat"]
        chats.sort(key=lambda r: r["metadata"]["timestamp"], reverse=True)
        return [
            {"user": r["metadata"]["content"], "agent": r["metadata"]["agent_response"],
             "intent": r["metadata"].get("intent", ""), "target": r["metadata"].get("target", "")}
            for r in chats[:limit]
        ]

    def add_file_event(self, path: str, operation: str, content: str = "") -> None:
        doc_text = f"[{operation}] {path}: {content[:500]}"
        self._rows.append({
            "id": self._alloc_id(),
            "doc_type": "file",
            "document": doc_text[:2000],
            "metadata": {
                "doc_type": "file",
                "path": path, "operation": operation, "content_preview": content[:500],
                "timestamp": self._next_timestamp(),
            },
        })

    def add_task(self, description: str, status: str = "pending", files_affected=None) -> None:
        doc_text = f"[Task: {description}] ({status})"
        self._rows.append({
            "id": self._alloc_id(),
            "doc_type": "task",
            "document": doc_text,
            "metadata": {
                "doc_type": "task",
                "description": description[:500], "status": status,
                "files_affected": ",".join(files_affected or []),
                "timestamp": self._next_timestamp(),
            },
        })

    def set_preference(self, key: str, value: str) -> None:
        self._prefs[key] = value

    def get_preference(self, key: str):
        return self._prefs.get(key)

    def list_preferences(self, limit: int = 50) -> list[dict[str, str]]:
        return [{"key": k, "value": v} for k, v in sorted(self._prefs.items())][:limit]

    def retrieve_similar(self, query: str, k: int = 5, doc_type=None, max_distance: float = 0.95) -> list[dict]:
        return []

    def get_by_type(self, doc_type: str, limit: int = 20, offset: int = 0) -> list[dict]:
        rows = [r for r in self._rows if r["doc_type"] == doc_type]
        rows.sort(key=lambda r: r["metadata"].get("timestamp", 0), reverse=True)
        return [{"id": r["id"], "document": r["document"], "metadata": r["metadata"]} for r in rows[offset:offset + limit]]

    def get_all_by_type(self, doc_type: str) -> list[dict]:
        return self.get_by_type(doc_type, limit=999999)

    def delete_by_ids(self, ids: list[str]) -> None:
        id_set = set(ids)
        self._rows = [r for r in self._rows if r["id"] not in id_set]
