class MemoryStore:
    def __init__(self) -> None:
        self._turns: list[dict[str, str]] = []

    def add_turn(self, user_message: str, agent_response: str) -> None:
        self._turns.append(
            {
                "user": user_message,
                "agent": agent_response,
            }
        )

    def recent_turns(self, limit: int = 5) -> list[dict[str, str]]:
        return self._turns[-limit:]
