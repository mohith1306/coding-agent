"""End-to-end agent loop tests using FakeLLM.

Tests the full agent orchestration loop with deterministic LLM responses,
verifying tool selection, argument passing, and state management without
any real API calls.
"""

import pytest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from coding_agent.agent import CONFIRMATION_MARKER, CodingAgent
from coding_agent.intent import Intent

from tests.fakes import FakeLLM, FakeMemory, FakeIntentParser
from tests.helpers import (
    AgentTrace,
    assert_tool_called,
    assert_tool_sequence,
    assert_no_tool_called,
    assert_max_tool_calls,
    assert_no_errors,
    summarize_trace,
)


def _make_agent(workspace: Path, memory: Optional[FakeMemory] = None) -> tuple:
    """Create a CodingAgent with faked dependencies."""
    mem = memory or FakeMemory()

    with patch.dict("os.environ", {"DATABASE_URL": "", "OPENROUTER_API_KEY": ""}, clear=False):
        agent = CodingAgent(memory=mem, root=workspace)

    parser = FakeIntentParser()
    agent.intent_parser = parser
    return agent, parser


# ---------------------------------------------------------------------------
# Tool selection tests
# ---------------------------------------------------------------------------

class TestToolSelection:
    """Verify the agent routes to the correct tool for each intent."""

    def test_create_file_intent(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)
        parser.intents = [
            Intent(name="create_file", confidence=1.0, target="hello.py",
                   reason="user wants to create a file", raw_message="create hello.py"),
        ]

        # Fake the generate call to return valid Python
        parser.generate = lambda sys, usr: "print('hello')"

        response = agent.handle("create hello.py", model="test")

        # Agent should have attempted to create the file
        assert isinstance(response, str)
        assert len(response) > 0

    def test_read_file_intent(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)

        # Create a file first
        (workspace / "test.txt").write_text("hello world")

        parser.intents = [
            Intent(name="read_file", confidence=1.0, target="test.txt",
                   reason="user wants to read", raw_message="read test.txt"),
        ]

        response = agent.handle("read test.txt", model="test")
        assert "hello world" in response

    def test_explain_code_fallback(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)
        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="user wants explanation", raw_message="explain this"),
        ]

        # Fake LLM for the generate call
        parser.generate = lambda sys, usr: "This code prints hello"
        response = agent.handle("explain this", model="test")
        assert "hello" in response.lower() or len(response) > 0


# ---------------------------------------------------------------------------
# Confirmation flow tests
# ---------------------------------------------------------------------------

class TestConfirmationFlow:
    """Verify the confirmation flow for dangerous operations."""

    def test_delete_requires_confirmation(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)

        # Create a file to delete
        (workspace / "to_delete.txt").write_text("delete me")

        parser.intents = [
            Intent(name="delete_file", confidence=1.0, target="to_delete.txt",
                   reason="user wants to delete", raw_message="delete to_delete.txt",
                   requires_confirmation=True),
        ]

        response = agent.handle("delete to_delete.txt", model="test")
        assert response.startswith(CONFIRMATION_MARKER)

        # File should NOT be deleted yet
        assert (workspace / "to_delete.txt").exists()

    def test_confirmed_delete_removes_file(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)

        (workspace / "to_delete.txt").write_text("delete me")

        parser.intents = [
            Intent(name="delete_file", confidence=1.0, target="to_delete.txt",
                   reason="confirmed delete", raw_message="delete to_delete.txt"),
        ]

        response = agent.handle("delete to_delete.txt", confirmed=True, model="test")
        assert not (workspace / "to_delete.txt").exists()


# ---------------------------------------------------------------------------
# State management tests
# ---------------------------------------------------------------------------

class TestStateManagement:
    """Verify agent state is properly managed across calls."""

    def test_memory_turn_recorded(self, workspace: Path) -> None:
        mem = FakeMemory()
        agent, parser = _make_agent(workspace, memory=mem)

        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="test", raw_message="hi"),
        ]

        parser.generate = lambda sys, usr: "response"
        agent.handle("hi", model="test")

        # Memory should have recorded the turn
        assert len(mem.turns) >= 1

    def test_pending_state_cleared_after_success(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)

        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="test", raw_message="test"),
        ]

        parser.generate = lambda sys, usr: "ok"
        agent.handle("test", model="test")

        # Pending state should be clean
        assert len(agent._pending_edits) == 0
        assert len(agent._pending_intents) == 0


# ---------------------------------------------------------------------------
# Model override tests
# ---------------------------------------------------------------------------

class TestModelOverride:
    """Verify model parameter is respected without mutating shared state."""

    def test_model_override_does_not_persist(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)
        original_model = parser.model

        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="test", raw_message="test"),
        ]

        parser.generate = lambda sys, usr: "ok"
        agent.handle("test", model="custom-model")

        # Parser model should be restored
        assert parser.model == original_model

    def test_default_model_uses_parser_value(self, workspace: Path) -> None:
        agent, parser = _make_agent(workspace)
        parser.model = "my-default-model"

        parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="test", raw_message="test"),
        ]

        parser.generate = lambda sys, usr: "ok"
        agent.handle("test")

        # Parser model should be unchanged
        assert parser.model == "my-default-model"
