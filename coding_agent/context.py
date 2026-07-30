from dataclasses import dataclass

from .memory import MemoryStore


@dataclass(frozen=True)
class AgentContext:
    user_message: str
    recent_messages: list[dict[str, str]]


class ContextBuilder:
    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def build(self, user_message: str) -> AgentContext:
        return AgentContext(
            user_message=user_message,
            recent_messages=self.memory.recent_turns(),
        )
