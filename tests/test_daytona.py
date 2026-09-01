import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coding_agent.agent import CodingAgent
from coding_agent.tools.daytona_sandbox import DaytonaSandbox
from coding_agent.tools.terminal import TerminalSandbox

from tests.fakes import FakeMemory


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
    # Prevent the repo .env (found via module ancestry) from re-injecting DAYTONA_API_KEY.
    monkeypatch.setattr(
        "coding_agent.intent.IntentParser._find_dotenv_path",
        lambda self: tmp_path / ".env",
    )
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


def test_git_clone_runs_locally_even_with_daytona(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "coding_agent.intent.IntentParser._find_dotenv_path",
        lambda self: tmp_path / ".env",
    )
    fake = MagicMock()
    fake.return_value.run.side_effect = AssertionError("git clone must NOT reach the sandbox")
    monkeypatch.setattr("coding_agent.agent.DaytonaSandbox", fake)

    from coding_agent.agent import CodingAgent

    agent = CodingAgent(memory=FakeMemory(), root=tmp_path)
    assert agent.terminal is fake.return_value

    captured = {}

    def local_run(self, command, timeout=30):
        captured["command"] = command
        return "Exit code: 0\nCloning into 'sig_repo'...\n"

    monkeypatch.setattr("coding_agent.agent.TerminalSandbox.run", local_run)

    result = agent._is_local_git_clone("git clone https://github.com/u/repo.git")
    assert result is True
    assert agent._is_local_git_clone("git status") is False
    assert agent._is_local_git_clone("git clone ../local/path") is False

    out = agent._handle_run_command(
        _intent_for_clone("git clone https://github.com/mohith1306/signature_verification")
    )
    assert "Cloning into 'sig_repo'" in out
    assert captured["command"].startswith("git clone")


def _intent_for_clone(command: str):
    from coding_agent.intent import Intent

    return Intent(name="run_command", target=command, raw_message=command)
