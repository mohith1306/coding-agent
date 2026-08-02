import shlex
import subprocess
from pathlib import Path
from typing import Optional


MAX_OUTPUT_CHARS = 8000
DEFAULT_TIMEOUT_SECONDS = 30

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


class TerminalSandbox:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self, command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
        command = command.strip()
        if not command:
            return "Error: empty command."

        block_reason = self._check_blocked(command)
        if block_reason:
            return block_reason

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s: {command[:120]}"
        except FileNotFoundError:
            return f"Command not found: {command}"
        except Exception as error:
            return f"Failed to run command: {error}"

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

        status = f"Exit code: {result.returncode}"
        return f"{status}\n{output}"

    def _check_blocked(self, command: str) -> Optional[str]:
        lowered = command.lower()
        for prefix in BLOCKED_PREFIXES:
            if lowered.startswith(prefix):
                return f"Blocked: command `{command}` is not allowed in the sandbox."
        return None
