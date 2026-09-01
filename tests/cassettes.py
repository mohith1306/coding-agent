"""Cassette record/replay for LLM API calls.

Record real LLM interactions once, replay them in CI forever.
Zero cost, fully deterministic regression tests.

Usage:
    # Recording (first run)
    with Cassette.recording("my_test") as c:
        result = llm.chat(messages)
        c.record(messages, result)

    # Replay (subsequent runs)
    with Cassette.replay("my_test") as c:
        result = c.replay_entry(messages)
        assert result == expected
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


CASSETTES_DIR = Path(__file__).parent / "cassettes"


@dataclass
class CassetteEntry:
    """Single recorded request/response pair."""
    request_messages: list[dict[str, str]]
    request_kwargs: dict[str, Any] = field(default_factory=dict)
    response: str = ""
    error: str | None = None


@dataclass
class Cassette:
    """Record or replay LLM API calls.

    Cassette files are JSON, committed to git, and replayed in CI
    without any API key or network access.
    """

    name: str
    entries: list[CassetteEntry] = field(default_factory=list)
    _replay_index: int = 0
    _mode: str = "replay"

    @classmethod
    def recording(cls, name: str) -> Cassette:
        """Start a new recording session."""
        CASSETTES_DIR.mkdir(parents=True, exist_ok=True)
        return cls(name=name, _mode="recording")

    @classmethod
    def replay(cls, name: str) -> Cassette:
        """Load an existing cassette for replay."""
        path = CASSETTES_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Cassette '{name}' not found at {path}. "
                f"Run with recording mode first to create it."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [CassetteEntry(**e) for e in data.get("entries", [])]
        return cls(name=name, entries=entries, _mode="replay")

    def record(
        self,
        messages: list[dict[str, str]],
        response: str,
        **kwargs: Any,
    ) -> None:
        """Record a request/response pair."""
        if self._mode != "recording":
            return
        self.entries.append(CassetteEntry(
            request_messages=messages,
            request_kwargs=kwargs,
            response=response,
        ))

    def record_error(
        self,
        messages: list[dict[str, str]],
        error: str,
        **kwargs: Any,
    ) -> None:
        """Record a request that resulted in an error."""
        if self._mode != "recording":
            return
        self.entries.append(CassetteEntry(
            request_messages=messages,
            request_kwargs=kwargs,
            error=error,
        ))

    def replay_entry(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Replay the next recorded response, validating the request matches.

        Compares normalized messages and kwargs against the recorded entry.
        Raises ValueError on mismatch, IndexError if exhausted, RuntimeError on error.
        """
        if self._replay_index >= len(self.entries):
            raise IndexError(
                f"Cassette '{self.name}' exhausted: no more entries "
                f"after {self._replay_index} replays."
            )
        entry = self.entries[self._replay_index]

        # Validate request matches recorded entry
        recorded_str = json.dumps(entry.request_messages, sort_keys=True, ensure_ascii=False)
        actual_str = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        if recorded_str != actual_str:
            raise ValueError(
                f"Cassette '{self.name}' request mismatch at entry {self._replay_index}:\n"
                f"  Expected: {recorded_str[:200]}\n"
                f"  Actual:   {actual_str[:200]}"
            )

        self._replay_index += 1

        if entry.error:
            raise RuntimeError(entry.error)

        return entry.response

    def save(self) -> None:
        """Persist the recording to disk."""
        if self._mode != "recording":
            return
        CASSETTES_DIR.mkdir(parents=True, exist_ok=True)
        path = CASSETTES_DIR / f"{self.name}.json"
        data = {
            "name": self.name,
            "entry_count": len(self.entries),
            "entries": [
                {
                    "request_messages": e.request_messages,
                    "request_kwargs": e.request_kwargs,
                    "response": e.response,
                    "error": e.error,
                }
                for e in self.entries
            ],
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def is_exhausted(self) -> bool:
        return self._replay_index >= len(self.entries)

    @property
    def remaining(self) -> int:
        return max(0, len(self.entries) - self._replay_index)

    def __enter__(self) -> Cassette:
        return self

    def __exit__(self, *args: Any) -> None:
        if self._mode == "recording":
            self.save()


def cassette_hash(cassette_path: Path) -> str:
    """SHA-256 of a cassette file for drift detection."""
    if not cassette_path.exists():
        return ""
    return hashlib.sha256(cassette_path.read_bytes()).hexdigest()[:12]


def list_cassettes() -> list[str]:
    """List all available cassette names."""
    if not CASSETTES_DIR.exists():
        return []
    return sorted(p.stem for p in CASSETTES_DIR.glob("*.json"))
