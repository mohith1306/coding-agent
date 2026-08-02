import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class GitStatus:
    branch: str
    dirty_files: list[str]
    ahead: int
    behind: int

    @property
    def is_clean(self) -> bool:
        return not self.dirty_files and self.ahead == 0 and self.behind == 0


class GitContext:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = (root or Path.cwd()).resolve()

    def status(self) -> GitStatus:
        branch = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        status_out = self._run(["git", "status", "--porcelain"])
        ahead_behind = self._run(["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"], check=False)

        dirty = []
        if status_out:
            for line in status_out.split("\n"):
                if not line.strip():
                    continue
                filename = line[2:].strip()
                if filename:
                    dirty.append(filename)

        ahead = behind = 0
        if ahead_behind:
            try:
                parts = ahead_behind.strip().split()
                if len(parts) == 2:
                    ahead = int(parts[0])
                    behind = int(parts[1])
            except ValueError:
                pass

        return GitStatus(
            branch=branch or "unknown",
            dirty_files=dirty,
            ahead=ahead,
            behind=behind,
        )

    def stage_all(self) -> str:
        code, output = self._run_result(["git", "add", "-A"])
        if code != 0:
            return output
        return ""

    def commit(self, message: str) -> tuple[int, str]:
        return self._run_result(["git", "commit", "-m", message])

    def push(self) -> tuple[int, str]:
        return self._run_result(["git", "push"])

    def current_hash(self) -> str:
        return self._run(["git", "rev-parse", "--short", "HEAD"]) or "none"

    def _run(self, args: list[str], check: bool = True) -> str:
        code, output = self._run_result(args)
        if check and code != 0:
            return ""
        return output.strip()

    def _run_result(self, args: list[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=15,
                cwd=self.root,
            )
        except Exception as error:
            return 1, str(error)
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode, output
