import subprocess
from dataclasses import dataclass
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
    def status(self) -> GitStatus:
        branch = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        status_out = self._run(["git", "status", "--porcelain"])
        ahead_behind = self._run(["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"], check=False)

        dirty = []
        if status_out:
            for line in status_out.split("\n"):
                line = line.strip()
                if not line:
                    continue
                filename = line[3:] if len(line) > 3 else line
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

    def _run(self, args: list[str], check: bool = True) -> str:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return ""
        if check and result.returncode != 0:
            return ""
        return result.stdout.strip()
