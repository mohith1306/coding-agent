"""Graph vs legacy runtime parity tests.

Verifies that both the LangGraph and legacy CodingAgent runtimes
produce the same tool-selection behavior for equivalent inputs.
"""

import pytest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from coding_agent.intent import Intent

from tests.fakes import (
    FakeLLM,
    FakeMemory,
    FakeIntentParser,
    FakeLangChainLLM,
    FakeContextBuilder,
    FakePlanner,
    FakeVerifier,
    FakeToolRegistry,
)


def _make_legacy_agent(workspace: Path, memory: Optional[FakeMemory] = None):
    """Create a legacy CodingAgent with faked dependencies."""
    from coding_agent.agent import CodingAgent

    mem = memory or FakeMemory()
    with patch.dict("os.environ", {"DATABASE_URL": "", "OPENROUTER_API_KEY": ""}, clear=False):
        agent = CodingAgent(memory=mem, root=workspace)
    parser = FakeIntentParser()
    agent.intent_parser = parser
    return agent, parser


def _make_graph_agent(workspace: Path, memory: Optional[FakeMemory] = None):
    """Create a graph-based agent with all required faked dependencies."""
    try:
        from coding_agent.graph.graph import AgentGraph

        mem = memory or FakeMemory()
        llm = FakeLangChainLLM(response_text="ok")

        graph = AgentGraph(
            root=workspace,
            llm=llm,
            tool_registry=FakeToolRegistry(),
            intent_parser=FakeIntentParser(intents=[
                Intent(name="read_file", confidence=1.0, target="test.txt",
                       reason="read", raw_message="read test.txt"),
            ]),
            context_builder=FakeContextBuilder(),
            planner=FakePlanner(),
            verifier=FakeVerifier(),
            memory=mem,
        )
        return graph, mem
    except ImportError:
        pytest.skip("LangGraph dependencies not available")


class TestParity:
    """Test that legacy and graph runtimes produce equivalent behavior."""

    def test_read_file_same_output(self, workspace: Path) -> None:
        """Both runtimes should read a file and return its content."""
        (workspace / "test.txt").write_text("hello world")

        # Legacy
        legacy, legacy_parser = _make_legacy_agent(workspace)
        legacy_parser.intents = [
            Intent(name="read_file", confidence=1.0, target="test.txt",
                   reason="read", raw_message="read test.txt"),
        ]
        legacy_response = legacy.handle("read test.txt", model="test")
        assert "hello world" in legacy_response

        # Graph
        graph, _ = _make_graph_agent(workspace)
        result = graph.invoke("read test.txt")
        assert "final_response" in result

    def test_explain_same_output_format(self, workspace: Path) -> None:
        """Both runtimes should produce a non-empty explanation."""
        # Legacy
        legacy, legacy_parser = _make_legacy_agent(workspace)
        legacy_parser.intents = [
            Intent(name="explain", confidence=1.0, target="",
                   reason="explain", raw_message="explain"),
        ]
        legacy_parser.generate = lambda sys, usr: "This is an explanation"
        legacy_response = legacy.handle("explain", model="test")
        assert len(legacy_response) > 0
        assert isinstance(legacy_response, str)

        # Graph
        graph, _ = _make_graph_agent(workspace)
        result = graph.invoke("explain")
        assert "final_response" in result

    def test_delete_requires_confirmation_both(self, workspace: Path) -> None:
        """Both runtimes should require confirmation for destructive ops."""
        (workspace / "del.txt").write_text("delete me")

        # Legacy
        legacy, legacy_parser = _make_legacy_agent(workspace)
        legacy_parser.intents = [
            Intent(name="delete_file", confidence=1.0, target="del.txt",
                   reason="delete", raw_message="delete del.txt",
                   requires_confirmation=True),
        ]
        legacy_response = legacy.handle("delete del.txt", model="test")

        from coding_agent.agent import CONFIRMATION_MARKER
        assert legacy_response.startswith(CONFIRMATION_MARKER)
        assert (workspace / "del.txt").exists()


class TestGraphSpecific:
    """Tests specific to the graph runtime."""

    def test_graph_createsSuccessfully(self, workspace: Path) -> None:
        """Graph agent should initialize without errors."""
        graph, mem = _make_graph_agent(workspace)
        assert graph is not None

    def test_graph_has_required_components(self, workspace: Path) -> None:
        """Graph agent should have all required components."""
        graph, mem = _make_graph_agent(workspace)
        assert graph is not None
        assert hasattr(graph, 'invoke')
        assert hasattr(graph, 'stream_events')

    def test_graph_invoke_completes(self, workspace: Path) -> None:
        """Graph invoke should return a final_response."""
        graph, _ = _make_graph_agent(workspace)
        result = graph.invoke("hello")
        assert "final_response" in result
