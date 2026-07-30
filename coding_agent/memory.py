import logging
import uuid
from pathlib import Path
from typing import Optional

import chromadb


logger = logging.getLogger(__name__)


TENANT = "fc88920c-2c38-4228-abe3-ee448a2d7fa6"
DATABASE = "Coding_Agent"
API_KEY = "ck-34rspAKf7QoKJiNSqi7ZE27wVAHnd5gx775ZcfLjUTmA"


class MemoryStore:
    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.client = chromadb.CloudClient(
            tenant=TENANT,
            database=DATABASE,
            api_key=API_KEY,
        )
        self.collection = self.client.get_or_create_collection(
            name="agent_memory",
        )
        self._tick = 0

    # -- chat turns --

    def add_turn(self, user_message: str, agent_response: str, intent: str = "", target: str = "") -> None:
        content = f"User: {user_message}\nAgent: {agent_response}"
        doc_id = str(uuid.uuid4())
        self._tick += 1
        self.collection.add(
            documents=[content],
            metadatas=[{
                "doc_type": "chat",
                "role": "user",
                "content": user_message[:1000],
                "agent_response": agent_response[:1000],
                "intent": intent,
                "target": target,
                "timestamp": self._tick,
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
        self._tick += 1
        self.collection.add(
            documents=[text[:2000]],
            metadatas=[{
                "doc_type": "file",
                "path": path,
                "operation": operation,
                "content_preview": content[:500],
                "timestamp": self._tick,
            }],
            ids=[doc_id],
        )

    # -- tasks --

    def add_task(self, description: str, status: str = "pending", files_affected: Optional[list[str]] = None) -> None:
        text = f"[Task: {description}] ({status})"
        doc_id = str(uuid.uuid4())
        self._tick += 1
        self.collection.add(
            documents=[text],
            metadatas=[{
                "doc_type": "task",
                "description": description[:500],
                "status": status,
                "files_affected": ",".join(files_affected or []),
                "timestamp": self._tick,
            }],
            ids=[doc_id],
        )

    # -- preferences / key-value --

    def set_preference(self, key: str, value: str) -> None:
        doc_id = f"pref_{key}"
        self._tick += 1
        self.collection.upsert(
            documents=[value],
            metadatas=[{
                "doc_type": "preference",
                "key": key,
                "value": value[:1000],
                "timestamp": self._tick,
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
