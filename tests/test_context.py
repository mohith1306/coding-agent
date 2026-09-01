from pathlib import Path

from coding_agent.context import ContextBuilder
from coding_agent.memory import MemoryStore

from tests.fakes import FakeMemory


def _make_builder(chat: list[dict]) -> ContextBuilder:
    memory = FakeMemory()
    memory.turns = chat
    return ContextBuilder(memory, root=Path("/tmp"))


def test_format_for_prompt_includes_prior_turns() -> None:
    chat = [
        {"user": "create a to-do list project", "agent": "Here is the plan:\n# To-Do List App", "intent": "create_project", "target": ""},
        {"user": "make a README.md file for this", "agent": "Created `README.md`", "intent": "create_file", "target": "README.md"},
    ]
    builder = _make_builder(chat)
    ctx = builder.build("make a README.md file for this")

    prompt = builder.format_for_prompt(ctx)
    assert "Chat history:" in prompt
    assert "User: create a to-do list project" in prompt
    assert "Agent: Here is the plan:" in prompt
    assert "To-Do List App" in prompt
    assert "User: make a README.md file for this" in prompt


def test_format_for_prompt_without_history_is_empty() -> None:
    builder = _make_builder([])
    ctx = builder.build("hello")

    prompt = builder.format_for_prompt(ctx)
    assert "Chat history:" not in prompt
