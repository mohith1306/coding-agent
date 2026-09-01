"""Shared pytest fixtures for the coding agent test harness."""

import subprocess
import sys
from pathlib import Path
from typing import Generator

import pytest

from tests.fakes import FakeLLM, FakeMemory, FakeIntentParser


# ---------------------------------------------------------------------------
# Filesystem fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Clean temporary directory for file operations."""
    return tmp_path


@pytest.fixture
def git_workspace(tmp_path: Path) -> Path:
    """Temporary directory with an initialized git repo."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.fixture
def python_bin() -> str:
    return sys.executable


# ---------------------------------------------------------------------------
# Memory / LLM fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_memory() -> FakeMemory:
    """Fresh FakeMemory instance for each test."""
    return FakeMemory()


@pytest.fixture
def fake_llm() -> FakeLLM:
    """Fresh FakeLLM with no scripted responses (returns empty string)."""
    return FakeLLM()


@pytest.fixture
def fake_intent_parser() -> FakeIntentParser:
    """Fresh FakeIntentParser with no scripted intents."""
    return FakeIntentParser()


# ---------------------------------------------------------------------------
# Agent fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def coding_agent(workspace: Path, fake_memory: FakeMemory) -> Generator:
    """Create a CodingAgent with fake dependencies for unit testing.

    Monkeypatches the IntentParser to avoid real LLM calls.
    """
    from unittest.mock import MagicMock, patch

    from coding_agent.agent import CodingAgent

    # Block real DB connections
    with patch.dict("os.environ", {"DATABASE_URL": "", "OPENROUTER_API_KEY": ""}, clear=False):
        agent = CodingAgent(memory=fake_memory, root=workspace)

        # Replace intent parser with a fake
        fake_parser = FakeIntentParser()
        agent.intent_parser = fake_parser

        yield agent
