"""Multi-turn conversation tests.

Tests agent behavior across multiple conversation turns, including
context accumulation, error recovery, and state transitions.
"""

import pytest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from coding_agent.agent import CONFIRMATION_MARKER, CodingAgent
from coding_agent.intent import Intent

from tests.fakes import FakeLLM, FakeMemory, FakeIntentParser
from tests.helpers import AgentTrace, assert_tool_called, assert_no_errors


def _make_agent(workspace: Path, memory: Optional[FakeMemory] = None) -> tuple:
    mem = memory or FakeMemory()
    with patch.dict("os.environ", {"DATABASE_URL": "", "OPENROUTER_API_KEY": ""}, clear=False):
        agent = CodingAgent(memory=mem, root=workspace)
    parser = FakeIntentParser()
    agent.intent_parser = parser
    return agent, parser


class TestMultiTurn:
    """Test agent across multiple conversation turns."""

    def test_sequential_explain_calls(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)

        # Script 3 explain intents
        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="turn 1", raw_message="explain 1"),
            Intent(name="explain", confidence=1.0, target="",
                   reason="turn 2", raw_message="explain 2"),
            Intent(name="explain", confidence=1.0, target="",
                   reason="turn 3", raw_message="explain 3"),
        ]

        call_count = 0
        def fake_generate(system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            return f"response {call_count}"

        parser.generate = fake_generate

        r1 = agent.handle("explain 1", model="test")
        r2 = agent.handle("explain 2", model="test")
        r3 = agent.handle("explain 3", model="test")

        assert "response 1" in r1
        assert "response 2" in r2
        assert "response 3" in r3

    def test_error_recovery_between_turns(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)

        # First turn: valid intent
        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="ok", raw_message="ok"),
            Intent(name="unknown", confidence=0.0, reason="bad parse",
                   raw_message="bad"),
            Intent(name="explain", confidence=1.0, target="",
                   reason="recovery", raw_message="recovery"),
        ]

        parser.generate = lambda sys, usr: "ok"

        r1 = agent.handle("ok", model="test")
        assert "ok" in r1.lower() or len(r1) > 0

        # Second turn: unknown intent (should not crash)
        r2 = agent.handle("bad", model="test")
        assert isinstance(r2, str)

        # Third turn: should still work
        r3 = agent.handle("recovery", model="test")
        assert isinstance(r3, str)

    def test_delete_and_explain(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)

        # Turn 1: delete a file (requires confirmation)
        parser.intents = [
            Intent(name="delete_file", confidence=1.0, target="x.txt",
                   requires_confirmation=True,
                   reason="delete", raw_message="delete x.txt"),
        ]

        (workspace / "x.txt").write_text("data")

        r1 = agent.handle("delete x.txt", confirmed=True, model="test")
        assert "Deleted" in r1
        assert not (workspace / "x.txt").exists()

        # Turn 2: continue with normal operation
        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="next", raw_message="next"),
        ]
        parser.generate = lambda sys, usr: "all good"

        r2 = agent.handle("next", model="test")
        assert "all good" in r2

    def test_concurrent_model_switches(self, workspace: Path) -> None:
        """Simulate rapid model switches to test no cross-contamination."""
        agent, parser = _make_agent(workspace)

        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="test", raw_message=f"turn {i}")
            for i in range(5)
        ]

        parser.generate = lambda sys, usr: "ok"

        models = ["model-a", "model-b", "model-a", "model-c", "model-b"]
        for i, model in enumerate(models):
            agent.handle(f"turn {i}", model=model)

        # Parser model should still be default (not any of the overrides)
        assert parser.model == ""


class TestEdgeCases:
    """Test unusual or extreme scenarios."""

    def test_empty_message(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)
        parser.intents = [
            Intent(name="unknown", confidence=0.0, reason="empty",
                   raw_message=""),
        ]

        response = agent.handle("", model="test")
        assert isinstance(response, str)

    def test_very_long_message(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)
        long_msg = "x" * 10000

        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="long", raw_message=long_msg),
        ]

        parser.generate = lambda sys, usr: "processed"
        response = agent.handle(long_msg, model="test")
        assert "processed" in response

    def test_special_characters_in_path(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)

        # Create file with spaces
        (workspace / "my file.txt").write_text("content")

        parser.intents = [
            Intent(name="read_file", confidence=1.0, target="my file.txt",
                   reason="read", raw_message="read my file.txt"),
        ]

        response = agent.handle("read my file.txt", model="test")
        assert "content" in response
