import logging
import os
from typing import Callable, Optional

from .memory import MemoryStore


logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 200_000
KEEP_RECENT_TURNS = 10

COMPACTION_SYSTEM_PROMPT = (
    "You are a context compactor for a coding agent. The conversation history below has "
    "grown too large. Produce a single, dense summary that preserves: the task being worked "
    "on, files created or modified, key decisions and preferences, and any unresolved next "
    "steps. Return ONLY the summary text, no markdown fences, no preamble."
)


def estimate_tokens(text: str) -> int:
    """Heuristic token estimate (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class CompactionManager:
    """Tracks accumulated context and compacts it once the budget is exceeded."""

    def __init__(
        self,
        memory: MemoryStore,
        generate: Optional[Callable[[str, str], str]] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        keep_recent: int = KEEP_RECENT_TURNS,
        summary_key: str = "compaction_summary",
    ) -> None:
        self.memory = memory
        self.generate = generate
        self.max_tokens = self._resolve_max_tokens(max_tokens)
        self.keep_recent = keep_recent
        self.summary_key = summary_key

    def current_tokens(self) -> int:
        total = estimate_tokens(self.get_summary())
        for turn in self.memory.get_all_by_type("chat"):
            total += estimate_tokens(turn.get("document", ""))
        return total

    def should_compact(self) -> bool:
        return self.current_tokens() >= self.max_tokens

    def get_summary(self) -> str:
        return self.memory.get_preference(self.summary_key) or ""

    def compact(self) -> Optional[str]:
        turns = self.memory.get_all_by_type("chat")
        if len(turns) <= self.keep_recent + 1:
            return None

        turns.sort(key=lambda t: t["metadata"].get("timestamp", 0))
        old = turns[:-self.keep_recent]
        old_docs = [t["document"] for t in old if t.get("document")]
        if not old_docs:
            return None

        new_summary = self._generate_summary(old_docs)
        if not new_summary:
            return None

        self.memory.set_preference(self.summary_key, new_summary)
        self.memory.delete_by_ids([t["id"] for t in old])
        logger.info(
            "Compacted %d old turns into a %d-token summary; context now %d tokens",
            len(old),
            estimate_tokens(new_summary),
            self.current_tokens(),
        )
        return new_summary

    def _generate_summary(self, old_docs: list[str]) -> str:
        if not self.generate:
            return "".join(doc[:500] for doc in old_docs)[:4000]

        prior = self.get_summary()
        combined = "\n\n---\n\n".join(old_docs)
        user_prompt = (
            f"Previous summary:\n{prior or '(none)'}\n\n"
            f"Conversation to fold in:\n{combined}"
        )
        try:
            result = self.generate(COMPACTION_SYSTEM_PROMPT, user_prompt)
            return result.strip()
        except Exception as error:
            logger.warning("Summary generation failed: %s", error)
            return ""

    def _resolve_max_tokens(self, default: int) -> int:
        raw = os.getenv("CODING_AGENT_MAX_CONTEXT_TOKENS")
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                logger.warning("Invalid CODING_AGENT_MAX_CONTEXT_TOKENS=%s", raw)
        return default
