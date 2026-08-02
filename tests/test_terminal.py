from pathlib import Path

from coding_agent.tools.terminal import TerminalSandbox


def test_empty_command(workspace: Path) -> None:
    sandbox = TerminalSandbox(workspace)
    assert "empty" in sandbox.run("  ")


def test_blocked_destructive_commands(workspace: Path) -> None:
    sandbox = TerminalSandbox(workspace)
    for cmd in ["rm -rf /", "sudo rm file", "mkfs.ext4 /dev/sda", ":(){ :|:& };:", "shutdown now", "git push --force"]:
        result = sandbox.run(cmd)
        assert "Blocked" in result, cmd


def test_safe_command_runs(workspace: Path) -> None:
    sandbox = TerminalSandbox(workspace)
    result = sandbox.run("echo hello")
    assert result.startswith("Exit code: 0")
    assert "hello" in result


def test_python_normalized_to_python3(workspace: Path) -> None:
    sandbox = TerminalSandbox(workspace)
    result = sandbox.run("python --version")
    assert result.startswith("Exit code: 0")


def test_timeout(workspace: Path) -> None:
    sandbox = TerminalSandbox(workspace)
    result = sandbox.run("sleep 5", timeout=1)
    assert "timed out" in result
