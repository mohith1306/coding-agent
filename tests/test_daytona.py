import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coding_agent.agent import CodingAgent
from coding_agent.tools.daytona_sandbox import DaytonaSandbox
from coding_agent.tools.terminal import TerminalSandbox


class FakeMemory:
    def __init__(self) -> None:
        self.turns = []

    def add_turn(self, user_message, agent_response, intent="", target=""):
        self.turns.append({"id": f"id{len(self.turns)}", "document": "x", "metadata": {"timestamp": len(self.turns)}})

    def recent_turns(self, limit=5):
        return []

    def retrieve_similar(self, query, k=5, doc_type=None, max_distance=0.95):
        return []

    def get_by_type(self, doc_type, limit=20):
        return []

    def get_all_by_type(self, doc_type):
        return []

    def delete_by_ids(self, ids):
        pass

    def add_task(self, description, status="pending", files_affected=None):
        pass

    def add_file_event(self, path, operation, content=""):
        pass

    def set_preference(self, key, value):
        pass

    def get_preference(self, key):
        return None

    def list_preferences(self):
        return []


def test_daytona_requires_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with patch.dict(sys.modules, {"daytona": MagicMock()}):
        with pytest.raises(RuntimeError):
            DaytonaSandbox(tmp_path)


def test_daytona_sandbox_created_when_key_set(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"DAYTONA_API_KEY": "test-key"}, clear=False):
        sb = DaytonaSandbox(tmp_path)
        assert sb.root == tmp_path.resolve()


def test_agent_uses_daytona_when_key_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    mock_sandbox = MagicMock()
    monkeypatch.setattr("coding_agent.agent.DaytonaSandbox", mock_sandbox)
    agent = CodingAgent(memory=FakeMemory(), root=tmp_path)
    assert agent.terminal is mock_sandbox.return_value


def test_agent_uses_local_without_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    agent = CodingAgent(memory=FakeMemory(), root=tmp_path)
    assert isinstance(agent.terminal, TerminalSandbox)


def _mock_daytona_modules(monkeypatch, fake_sandbox):
    import sys

    fake_daytona = MagicMock()
    fake_daytona.Daytona = MagicMock()
    fake_daytona.CreateSandboxFromSnapshotParams = MagicMock()
    fake_daytona.Daytona.return_value.create.return_value = fake_sandbox
    monkeypatch.setitem(sys.modules, "daytona", fake_daytona)
    return fake_daytona


def test_daytona_run_syncs_and_execs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    (tmp_path / "main.py").write_text("print('hi')\n")

    fake_fs = MagicMock()
    fake_process = MagicMock()
    fake_process.exec.return_value = MagicMock(result="hi", exit_code=0)
    fake_sandbox = MagicMock()
    fake_sandbox.fs = fake_fs
    fake_sandbox.process = fake_process
    fake_sandbox.get_work_dir.return_value = "/workspace"

    fake_daytona = _mock_daytona_modules(monkeypatch, fake_sandbox)

    import coding_agent.tools.daytona_sandbox as ds

    sb = ds.DaytonaSandbox(tmp_path)
    result = sb.run("python3 main.py")
    assert "Exit code: 0" in result
    assert "hi" in result
    fake_daytona.Daytona.return_value.create.assert_called_once()
    fake_fs.upload_file.assert_called_once()
    fake_process.exec.assert_called_once_with("python3 main.py", cwd="/workspace", timeout=30)


def test_daytona_skips_uploaded_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    (tmp_path / "main.py").write_text("print('hi')\n")

    fake_fs = MagicMock()
    fake_process = MagicMock()
    fake_process.exec.return_value = MagicMock(result="hi", exit_code=0)
    fake_sandbox = MagicMock()
    fake_sandbox.fs = fake_fs
    fake_sandbox.process = fake_process
    fake_sandbox.get_work_dir.return_value = "/workspace"

    _mock_daytona_modules(monkeypatch, fake_sandbox)

    import coding_agent.tools.daytona_sandbox as ds

    sb = ds.DaytonaSandbox(tmp_path)
    sb.run("python3 main.py")
    first_calls = fake_fs.upload_file.call_count
    sb.run("python3 main.py")
    assert fake_fs.upload_file.call_count == first_calls


def test_blocked_command_returns_reason(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    fake = MagicMock()
    fake.return_value.run.return_value = "Blocked: command `rm -rf /` is not allowed in the sandbox."
    monkeypatch.setattr("coding_agent.agent.DaytonaSandbox", fake)
    agent = CodingAgent(memory=FakeMemory(), root=tmp_path)
    result = agent.terminal.run("rm -rf /")
    assert "Blocked" in result
