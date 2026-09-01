"""Shared test doubles for the coding agent test harness.

Consolidates FakeMemory (previously duplicated in 4 files) and adds
FakeLLM for deterministic agent testing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List, Optional

from coding_agent.intent import Intent


# ---------------------------------------------------------------------------
# FakeMemory — drop-in replacement for MemoryStore used across all tests
# ---------------------------------------------------------------------------

class FakeMemory:
    """In-memory fake matching the MemoryStore public API.

    Records all mutations so tests can assert on agent behavior without
    touching PostgreSQL or ChromaDB.
    """

    def __init__(self) -> None:
        self.turns: list[dict] = []
        self.tasks: list[dict] = []
        self.file_events: list[dict] = []
        self.preferences: dict[str, str] = {}
        self.deleted: list[str] = []
        self._ts: float = 0.0

    def _next_ts(self) -> float:
        self._ts += 1
        return self._ts

    # -- chat turns --

    def add_turn(self, user_message: str, agent_response: str, intent: str = "", target: str = "") -> None:
        self.turns.append({
            "id": f"turn_{len(self.turns)}",
            "document": f"User: {user_message}\nAgent: {agent_response}",
            "metadata": {
                "content": user_message[:1000],
                "agent_response": agent_response[:2000],
                "intent": intent,
                "target": target,
                "timestamp": self._next_ts(),
            },
        })

    def recent_turns(self, limit: int = 5) -> list[dict[str, str]]:
        return []

    # -- file events --

    def add_file_event(self, path: str, operation: str, content: str = "") -> None:
        self.file_events.append({
            "id": f"file_{len(self.file_events)}",
            "document": f"[{operation}] {path}: {content[:500]}",
            "metadata": {
                "doc_type": "file",
                "path": path,
                "operation": operation,
                "content_preview": content[:500],
                "timestamp": self._next_ts(),
            },
        })

    # -- tasks --

    def add_task(self, description: str, status: str = "pending", files_affected: Optional[List[str]] = None) -> None:
        self.tasks.append({
            "id": f"task_{len(self.tasks)}",
            "document": f"[Task: {description}] ({status})",
            "metadata": {
                "description": description[:500],
                "status": status,
                "files_affected": ",".join(files_affected or []),
                "timestamp": self._next_ts(),
            },
        })

    # -- preferences --

    def set_preference(self, key: str, value: str) -> None:
        self.preferences[key] = value

    def get_preference(self, key: str) -> Optional[str]:
        return self.preferences.get(key)

    def list_preferences(self, limit: int = 50) -> list[dict[str, str]]:
        return [{"key": k, "value": v} for k, v in sorted(self.preferences.items())][:limit]

    # -- retrieval --

    def retrieve_similar(self, query: str, k: int = 5, doc_type: Optional[str] = None, max_distance: float = 0.95) -> list[dict]:
        return []

    def get_by_type(self, doc_type: str, limit: int = 20, offset: int = 0) -> list[dict]:
        if doc_type == "task":
            return self.tasks[offset:offset + limit]
        return []

    def get_all_by_type(self, doc_type: str) -> list[dict]:
        if doc_type == "chat":
            return self.turns
        return []

    def delete_by_ids(self, ids: list[str]) -> None:
        id_set = set(ids)
        self.deleted.extend(ids)
        self.turns = [t for t in self.turns if t.get("id") not in id_set]
        self.tasks = [t for t in self.tasks if t.get("id") not in id_set]


# ---------------------------------------------------------------------------
# FakeLLM — deterministic LLM replacement for agent tests
# ---------------------------------------------------------------------------

@dataclass
class LLMCall:
    """Record of a single LLM call."""
    messages: list[dict[str, str]]
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeLLM:
    """Scripted LLM that returns predetermined responses in order.

    Usage::

        llm = FakeLLM(responses=["Hello!", "How can I help?"])
        result = llm.chat([{"role": "user", "content": "Hi"}])
        assert result == "Hello!"
        result = llm.chat([{"role": "user", "content": "Help"}])
        assert result == "How can I help?"

    Features:
        - Responses consumed in order (one per call)
        - Call log for assertion
        - Default response for tail calls
        - Can raise exceptions to simulate errors
    """

    def __init__(
        self,
        responses: Optional[List] = None,
        default_response: str = "",
    ) -> None:
        self.responses = list(responses or [])
        self.default_response = default_response
        self.call_log: list[LLMCall] = []
        self._index = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Return next scripted response (or default)."""
        call = LLMCall(messages=list(messages), kwargs=kwargs)
        self.call_log.append(call)

        if self._index < len(self.responses):
            response = self.responses[self._index]
            self._index += 1
            if isinstance(response, Exception):
                raise response
            return response

        return self.default_response

    def generate(self, system_prompt: str, user_message: str = "", **kwargs: Any) -> str:
        """Match IntentParser.generate(system_prompt, user_message) signature."""
        return self.chat([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}], **kwargs)

    @property
    def call_count(self) -> int:
        return len(self.call_log)

    @property
    def last_messages(self) -> list[dict[str, str]]:
        """Messages from the most recent call."""
        if not self.call_log:
            return []
        return self.call_log[-1].messages


class FakeIntentParser:
    """Deterministic intent parser that returns scripted Intent objects.

    Usage::

        parser = FakeIntentParser(intents=[
            Intent(name="create_file", confidence=1.0, target="foo.py", ...),
            Intent(name="unknown", confidence=0.0, reason="...", ...),
        ])
        intent = parser.parse("create foo.py")
        assert intent.name == "create_file"
    """

    def __init__(self, intents: Optional[List[Intent]] = None) -> None:
        self.intents = list(intents or [])
        self._index = 0
        self.parse_calls: list[dict] = []
        self.model: str = ""

    def parse(self, user_message: str, history: Optional[List[dict]] = None) -> Intent:
        self.parse_calls.append({"message": user_message, "history": history})

        if self._index < len(self.intents):
            intent = self.intents[self._index]
            self._index += 1
            return intent

        return Intent(
            name="unknown",
            confidence=0.0,
            reason="No more scripted intents",
            raw_message=user_message,
        )

    def generate(self, system_prompt: str, user_message: str = "", **kwargs: Any) -> str:
        return ""


class FakeToolRegistry:
    """Minimal tool registry stub for integration tests."""

    def __init__(self) -> None:
        self.terminal = FakeTerminal()


class FakeTerminal:
    """Minimal terminal stub that records commands."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.results: list[str] = []

    def run(self, command: str, timeout: int = 30) -> str:
        self.commands.append(command)
        if self.results:
            return self.results.pop(0)
        return "done"

    def close(self) -> None:
        pass
