import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import chromadb


logger = logging.getLogger(__name__)


DEFAULT_TENANT = "fc88920c-2c38-4228-abe3-ee448a2d7fa6"
DEFAULT_DATABASE = "Coding_Agent"


class MemoryStore:
    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._load_dotenv(Path.cwd() / ".env")
        tenant = os.getenv("CHROMA_TENANT", DEFAULT_TENANT)
        database = os.getenv("CHROMA_DATABASE", DEFAULT_DATABASE)
        api_key = os.getenv("CHROMA_API_KEY", "")

        if not api_key:
            raise RuntimeError(
                "CHROMA_API_KEY is not set. Add it to .env "
                "(copy from your Chroma Cloud dashboard)."
            )

        self.client = chromadb.CloudClient(
            tenant=tenant,
            database=database,
            api_key=api_key,
        )
        self.collection = self.client.get_or_create_collection(
            name="agent_memory",
        )
        self._last_ts = 0.0

    def _next_timestamp(self) -> float:
        now = time.time()
        if now <= self._last_ts:
            now = self._last_ts + 1e-6
        self._last_ts = now
        return now

    def _load_dotenv(self, path: Path) -> None:
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)

    # -- chat turns --

    def add_turn(self, user_message: str, agent_response: str, intent: str = "", target: str = "") -> None:
        content = f"User: {user_message}\nAgent: {agent_response}"
        doc_id = str(uuid.uuid4())
        self.collection.add(
            documents=[content],
            metadatas=[{
                "doc_type": "chat",
                "role": "user",
                "content": user_message[:1000],
                "agent_response": agent_response[:1000],
                "intent": intent,
                "target": target,
                "timestamp": self._next_timestamp(),
            }],
            ids=[doc_id],
        )

    def recent_turns(self, limit: int = 5) -> list[dict[str, str]]:
        results = self.collection.get(
            where={"doc_type": "chat"},
            include=["metadatas"],
        )
        if not results["ids"]:
            return []

        entries = []
        for i in range(len(results["ids"])):
            meta = results["metadatas"][i]
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

    # -- file events --

    def add_file_event(self, path: str, operation: str, content: str = "") -> None:
        text = f"[{operation}] {path}: {content[:500]}"
        doc_id = str(uuid.uuid4())
        self.collection.add(
            documents=[text[:2000]],
            metadatas=[{
                "doc_type": "file",
                "path": path,
                "operation": operation,
                "content_preview": content[:500],
                "timestamp": self._next_timestamp(),
            }],
            ids=[doc_id],
        )

    # -- tasks --

    def add_task(self, description: str, status: str = "pending", files_affected: Optional[list[str]] = None) -> None:
        text = f"[Task: {description}] ({status})"
        doc_id = str(uuid.uuid4())
        self.collection.add(
            documents=[text],
            metadatas=[{
                "doc_type": "task",
                "description": description[:500],
                "status": status,
                "files_affected": ",".join(files_affected or []),
                "timestamp": self._next_timestamp(),
            }],
            ids=[doc_id],
        )

    # -- preferences / key-value --

    def set_preference(self, key: str, value: str) -> None:
        doc_id = f"pref_{key}"
        self.collection.upsert(
            documents=[value],
            metadatas=[{
                "doc_type": "preference",
                "key": key,
                "value": value[:1000],
                "timestamp": self._next_timestamp(),
            }],
            ids=[doc_id],
        )

    def get_preference(self, key: str) -> Optional[str]:
        results = self.collection.get(
            ids=[f"pref_{key}"],
            include=["metadatas"],
        )
        if results["ids"] and results["metadatas"]:
            return results["metadatas"][0].get("value")
        return None

    def list_preferences(self, limit: int = 50) -> list[dict[str, str]]:
        results = self.collection.get(
            where={"doc_type": "preference"},
            include=["metadatas"],
        )
        merged = []
        if results["ids"]:
            for i in range(len(results["ids"])):
                meta = results["metadatas"][i]
                merged.append({
                    "key": meta.get("key", ""),
                    "value": meta.get("value", ""),
                })
        merged.sort(key=lambda p: p["key"])
        return merged[:limit]

    # -- vector retrieval --

    def retrieve_similar(self, query: str, k: int = 5, doc_type: Optional[str] = None, max_distance: float = 0.95) -> list[dict]:
        logger.info("Vector search: query=%s k=%s doc_type=%s", query[:80], k, doc_type)
        where = {"doc_type": doc_type} if doc_type else None
        results = self.collection.query(
            query_texts=[query],
            n_results=k,
            where=where,
            include=["metadatas", "documents", "distances"],
        )

        merged = []
        if results["ids"][0]:
            for i in range(len(results["ids"][0])):
                dist = results["distances"][0][i]
                logger.debug("  candidate dist=%.3f doc_type=%s text=%s",
                             dist,
                             results["metadatas"][0][i].get("doc_type"),
                             results["documents"][0][i][:60])
                if dist > max_distance:
                    continue
                merged.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": dist,
                })
        logger.info("Vector search returned %d/%d results", len(merged), len(results["ids"][0]))
        return merged

    # -- raw filter (no vector) --

    def get_by_type(self, doc_type: str, limit: int = 20) -> list[dict]:
        results = self.collection.get(
            where={"doc_type": doc_type},
            include=["metadatas", "documents"],
            limit=limit,
        )
        merged = []
        if results["ids"]:
            for i in range(len(results["ids"])):
                merged.append({
                    "id": results["ids"][i],
                    "document": results["documents"][i],
                    "metadata": results["metadatas"][i],
                })
        return merged

    def get_all_by_type(self, doc_type: str) -> list[dict]:
        return self.get_by_type(doc_type, limit=100000)

    def delete_by_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        self.collection.delete(ids=ids)
