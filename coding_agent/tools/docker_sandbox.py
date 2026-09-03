"""Docker-based sandbox for secure code execution."""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 8000
DEFAULT_TIMEOUT_SECONDS = 30
IDLE_TIMEOUT_SECONDS = 300  # 5 minutes
CONTAINER_PREFIX = "coding-agent-sandbox"

BLOCKED_PREFIXES = (
    "rm -rf /",
    "sudo",
    "mkfs",
    "dd ",
    ":(){",
    "shutdown",
    "reboot",
    "poweroff",
    "git push --force",
    "git push -f",
    "> /dev/sda",
)


class DockerSandbox:
    """Docker-based sandbox for secure code execution.
    
    Features:
    - Real container isolation
    - No network access (fully isolated)
    - Memory limit: 512MB
    - CPU limit: 1 core
    - Auto-cleanup after idle timeout
    """

    def __init__(
        self,
        root: Path,
        image: str = "coding-agent-sandbox",
        memory_limit: str = "512m",
        cpu_limit: float = 1.0,
    ) -> None:
        self.root = root.resolve()
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self._container_id: Optional[str] = None
        self._last_activity: float = time.time()
        self._ensure_image()

    def _ensure_image(self) -> None:
        """Build sandbox image if it doesn't exist.

        Raises on failure so callers can fall back to Daytona/local.
        """
        result = subprocess.run(
            ["docker", "image", "inspect", self.image],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            self._build_image()

    def _build_image(self) -> None:
        """Build the sandbox Docker image.

        Raises RuntimeError on failure so terminal factory can fallback.
        """
        dockerfile = Path(__file__).parent / "sandbox.Dockerfile"
        if not dockerfile.exists():
            raise RuntimeError(f"Dockerfile not found: {dockerfile}")

        logger.info("Building sandbox image: %s", self.image)
        result = subprocess.run(
            ["docker", "build", "-t", self.image, "-f", str(dockerfile), "."],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(dockerfile.parent.parent.parent),
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to build image: {result.stderr[:500]}")

    def _get_or_create_container(self) -> str:
        """Get existing container or create new one (handles idle timeout)."""
        if self._container_id:
            if self._check_idle_timeout():
                logger.info("Container idle timeout exceeded, cleaning up: %s", self._container_id[:12])
                self.cleanup()
            else:
                # Check if container is still running
                try:
                    result = subprocess.run(
                        ["docker", "inspect", "-f", "{{.State.Running}}", self._container_id],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.stdout.strip() == "true":
                        self._last_activity = time.time()
                        return self._container_id
                except Exception:
                    pass

        # Create new container
        return self._create_container()

    def _create_container(self) -> str:
        """Create a new sandbox container."""
        container_name = f"{CONTAINER_PREFIX}-{int(time.time())}"
        
        cmd = [
            "docker", "run",
            "-d",
            "--name", container_name,
            "--memory", self.memory_limit,
            "--cpus", str(self.cpu_limit),
            "--network", "none",  # No network access
            "--read-only",  # Read-only rootfs
            "--tmpfs", "/tmp:size=100m",  # Writable tmp
            "-v", f"{self.root}:/workspace:rw",  # Mount project
            self.image,
            "sleep", "infinity",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create container: {result.stderr}")
            
            self._container_id = result.stdout.strip()
            self._last_activity = time.time()
            logger.info("Created sandbox container: %s", self._container_id[:12])
            return self._container_id
        except Exception as e:
            raise RuntimeError(f"Failed to create Docker container: {e}")

    def run(self, command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
        """Run a command in the sandbox container."""
        command = command.strip()
        if not command:
            return "Error: empty command."

        block_reason = self._check_blocked(command)
        if block_reason:
            logger.warning("Blocked command: %s", command)
            return block_reason

        command = self._normalize_python_command(command)
        logger.info("$ %s (timeout=%ss)", command, timeout)

        try:
            container_id = self._get_or_create_container()
            
            # Execute command in container
            exec_cmd = [
                "docker", "exec",
                "-w", "/workspace",
                container_id,
                "bash", "-c", command,
            ]
            
            result = subprocess.run(
                exec_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            self._last_activity = time.time()
            
            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(result.stderr)

            output = "".join(output_parts).strip()
            if not output:
                output = "(no output)"

            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n\n[Output truncated]"

            logger.info("$ %s → exit %s", command, result.returncode)
            status = f"Exit code: {result.returncode}"
            return f"{status}\n{output}"

        except subprocess.TimeoutExpired:
            logger.warning("Command timed out after %ss: %s", timeout, command[:120])
            # Recreate container so timed-out process doesn't linger
            try:
                self.cleanup()
            except Exception:
                pass
            return f"Command timed out after {timeout}s: {command[:120]}"
        except Exception as error:
            return f"Failed to run command: {error}"

    def cleanup(self) -> None:
        """Stop and remove the sandbox container."""
        if not self._container_id:
            return

        try:
            subprocess.run(
                ["docker", "stop", self._container_id],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                ["docker", "rm", "-f", self._container_id],
                capture_output=True,
                timeout=10,
            )
            logger.info("Cleaned up sandbox container: %s", self._container_id[:12])
        except Exception as e:
            logger.warning("Failed to cleanup container: %s", e)
        finally:
            self._container_id = None

    def _check_idle_timeout(self) -> bool:
        """Check if container has been idle too long."""
        if not self._container_id:
            return False
        return (time.time() - self._last_activity) > IDLE_TIMEOUT_SECONDS

    def _check_blocked(self, command: str) -> Optional[str]:
        """Check if command is blocked."""
        lowered = command.lower()
        for prefix in BLOCKED_PREFIXES:
            if lowered.startswith(prefix):
                return f"Blocked: command `{command}` is not allowed in the sandbox."
        return None

    def _normalize_python_command(self, command: str) -> str:
        """Normalize python command to python3."""
        if not command.startswith("python "):
            return command
        return "python3" + command[len("python"):]

    def __del__(self) -> None:
        """Cleanup on object destruction."""
        self.cleanup()
