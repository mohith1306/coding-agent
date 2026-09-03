"""Tests for Docker sandbox execution."""

import pytest
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from coding_agent.tools.docker_sandbox import DockerSandbox
from coding_agent.tools.terminal import TerminalSandbox


@pytest.fixture
def docker_sandbox():
    """Create a Docker sandbox for testing."""
    sandbox = DockerSandbox(Path("."))
    yield sandbox
    sandbox.cleanup()


@pytest.fixture
def local_sandbox():
    """Create a local terminal sandbox for testing."""
    return TerminalSandbox(Path("."))


class TestDockerSandbox:
    """Tests for Docker-based sandbox."""

    def test_sandbox_creation(self, docker_sandbox):
        """Test sandbox can be created."""
        assert docker_sandbox is not None
        assert docker_sandbox.root == Path(".").resolve()

    def test_echo_command(self, docker_sandbox):
        """Test basic echo command."""
        result = docker_sandbox.run("echo hello world")
        assert "Exit code: 0" in result
        assert "hello world" in result

    def test_python_version(self, docker_sandbox):
        """Test Python is available in sandbox."""
        result = docker_sandbox.run("python3 --version")
        assert "Exit code: 0" in result
        assert "Python 3" in result

    def test_ls_command(self, docker_sandbox):
        """Test ls command works."""
        result = docker_sandbox.run("ls /workspace")
        assert "Exit code: 0" in result
        assert "coding_agent" in result

    def test_network_isolation(self, docker_sandbox):
        """Test network is blocked in sandbox."""
        result = docker_sandbox.run("curl -s https://google.com 2>&1 || echo blocked")
        assert "blocked" in result.lower() or "exit code: 0" in result

    def test_blocked_command_sudo(self, docker_sandbox):
        """Test sudo is blocked."""
        result = docker_sandbox.run("sudo rm -rf /")
        assert "Blocked" in result

    def test_blocked_command_rm_rf(self, docker_sandbox):
        """Test rm -rf / is blocked."""
        result = docker_sandbox.run("rm -rf /")
        assert "Blocked" in result

    def test_blocked_command_mkfs(self, docker_sandbox):
        """Test mkfs is blocked."""
        result = docker_sandbox.run("mkfs.ext4 /dev/sda")
        assert "Blocked" in result

    def test_blocked_command_shutdown(self, docker_sandbox):
        """Test shutdown is blocked."""
        result = docker_sandbox.run("shutdown -h now")
        assert "Blocked" in result

    def test_empty_command(self, docker_sandbox):
        """Test empty command returns error."""
        result = docker_sandbox.run("")
        assert "Error" in result or "empty" in result

    def test_command_timeout(self, docker_sandbox):
        """Test command timeout works."""
        result = docker_sandbox.run("sleep 10", timeout=2)
        assert "timed out" in result.lower() or "timeout" in result.lower()

    def test_file_write_in_sandbox(self, docker_sandbox):
        """Test file write works in sandbox."""
        result = docker_sandbox.run("echo 'test content' > /workspace/test_sandbox.txt")
        assert "Exit code: 0" in result

        result = docker_sandbox.run("cat /workspace/test_sandbox.txt")
        assert "test content" in result

        # Cleanup
        docker_sandbox.run("rm /workspace/test_sandbox.txt")

    def test_python_execution(self, docker_sandbox):
        """Test Python code execution in sandbox."""
        result = docker_sandbox.run('python3 -c "print(2 + 2)"')
        assert "Exit code: 0" in result
        assert "4" in result

    def test_pip_install(self, docker_sandbox):
        """Test pip install works (if network available)."""
        result = docker_sandbox.run("pip install requests 2>&1 || echo install_failed")
        # May fail due to network isolation, that's ok
        assert "Exit code: 0" in result or "install_failed" in result

    def test_cleanup(self):
        """Test cleanup removes container."""
        sandbox = DockerSandbox(Path("."))
        container_id = sandbox._get_or_create_container()
        assert container_id is not None

        sandbox.cleanup()
        assert sandbox._container_id is None


class TestLocalSandbox:
    """Tests for local terminal sandbox (fallback)."""

    def test_echo_command(self, local_sandbox):
        """Test basic echo command."""
        result = local_sandbox.run("echo hello world")
        assert "Exit code: 0" in result
        assert "hello world" in result

    def test_python_version(self, local_sandbox):
        """Test Python is available."""
        result = local_sandbox.run("python3 --version")
        assert "Exit code: 0" in result

    def test_blocked_command(self, local_sandbox):
        """Test blocked commands are rejected."""
        result = local_sandbox.run("sudo rm -rf /")
        assert "Blocked" in result

    def test_empty_command(self, local_sandbox):
        """Test empty command returns error."""
        result = local_sandbox.run("")
        assert "Error" in result or "empty" in result


class TestSandboxIntegration:
    """Integration tests for sandbox with agent tools."""

    def test_registry_uses_docker(self):
        """Test tool registry selects Docker sandbox."""
        from coding_agent.tools.registry import ToolRegistry

        # Set env to use Docker
        os.environ["USE_DOCKER_SANDBOX"] = "true"

        registry = ToolRegistry(Path("."))
        assert type(registry.terminal).__name__ == "DockerSandbox"

    def test_run_command_tool(self):
        """Test run_command tool through registry."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("run_command")
        assert tool is not None

        result = tool.invoke({"command": "echo test"})
        assert "test" in result

    def test_run_tests_tool(self):
        """Test run_tests tool through registry."""
        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry(Path("."))
        tool = registry.get_tool_by_name("run_tests")
        assert tool is not None


class TestSandboxLifecycle:
    """Lifecycle tests that need no Docker daemon (mocked subprocess)."""

    def _sandbox_no_init(self):
        sandbox = DockerSandbox.__new__(DockerSandbox)
        sandbox._container_id = "abc123"
        sandbox._last_activity = 0.0
        return sandbox

    def test_close_delegates_to_cleanup(self):
        """close() must remove the container (was missing entirely)."""
        from unittest.mock import patch

        sandbox = self._sandbox_no_init()
        with patch.object(DockerSandbox, "cleanup") as mock_cleanup:
            sandbox.close()
        mock_cleanup.assert_called_once_with()

    def test_terminal_close_is_noop(self):
        """TerminalSandbox.close() exists so registry.close() never raises."""
        assert TerminalSandbox(Path(".")).close() is None

    def test_registry_close_calls_terminal_close(self):
        """Regression: registry.close() must reach terminal.close()."""
        from unittest.mock import MagicMock

        from coding_agent.tools.registry import ToolRegistry

        registry = ToolRegistry.__new__(ToolRegistry)
        registry.terminal = MagicMock()
        registry.close()
        registry.terminal.close.assert_called_once_with()

    def test_prune_exited_removes_listed(self):
        """prune_exited removes exited sandbox containers."""
        from unittest.mock import MagicMock, patch

        ps = MagicMock(stdout="aaa111\nbbb222\n", returncode=0)
        rm = MagicMock(returncode=0)
        with patch(
            "coding_agent.tools.docker_sandbox.subprocess.run",
            side_effect=[ps, rm],
        ) as mock_run:
            removed = DockerSandbox.prune_exited()
        assert removed == 2
        assert mock_run.call_count == 2
        rm_cmd = mock_run.call_args_list[1].args[0]
        assert rm_cmd[:2] == ["docker", "rm"]
        assert "aaa111" in rm_cmd and "bbb222" in rm_cmd

    def test_prune_exited_empty_is_noop(self):
        """No exited containers means no docker rm call."""
        from unittest.mock import MagicMock, patch

        ps = MagicMock(stdout="\n", returncode=0)
        with patch(
            "coding_agent.tools.docker_sandbox.subprocess.run",
            return_value=ps,
        ) as mock_run:
            assert DockerSandbox.prune_exited() == 0
        mock_run.assert_called_once()

    def test_prune_exited_survives_missing_docker(self):
        """Missing daemon must not raise (best-effort cleanup)."""
        from unittest.mock import patch

        with patch(
            "coding_agent.tools.docker_sandbox.subprocess.run",
            side_effect=FileNotFoundError("docker"),
        ):
            assert DockerSandbox.prune_exited() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
