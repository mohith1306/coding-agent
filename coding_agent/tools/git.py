"""Git operations with full branch support."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class GitStatus:
    """Git repository status."""
    branch: str
    dirty_files: list[str]
    ahead: int
    behind: int

    @property
    def is_clean(self) -> bool:
        return not self.dirty_files and self.ahead == 0 and self.behind == 0


class GitContext:
    """Full git operations including branching, merging, and stashing."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = (root or Path.cwd()).resolve()

    # ==================== STATUS OPERATIONS ====================

    def status(self) -> GitStatus:
        """Get repository status."""
        branch = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        status_out = self._run(["git", "status", "--porcelain"])
        ahead_behind = self._run(
            ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
            check=False,
        )

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

    def current_branch(self) -> str:
        """Get current branch name."""
        return self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"

    def list_branches(self) -> list[str]:
        """List all local branches."""
        output = self._run(["git", "branch", "--list"])
        if not output:
            return []
        return [line.strip().lstrip("* ") for line in output.split("\n") if line.strip()]

    def list_remote_branches(self) -> list[str]:
        """List all remote branches."""
        output = self._run(["git", "branch", "-r", "--list"])
        if not output:
            return []
        branches = []
        for line in output.split("\n"):
            line = line.strip()
            if line and not line.startswith("HEAD ->"):
                # Remove "origin/" prefix
                branch = line.split("/")[-1] if "/" in line else line
                branches.append(branch)
        return branches

    # ==================== BRANCH OPERATIONS ====================

    def create_branch(self, name: str) -> tuple[int, str]:
        """Create a new branch."""
        return self._run_result(["git", "branch", name])

    def checkout(self, branch: str) -> tuple[int, str]:
        """Checkout an existing branch."""
        return self._run_result(["git", "checkout", branch])

    def create_and_checkout(self, name: str) -> tuple[int, str]:
        """Create a new branch and checkout to it."""
        return self._run_result(["git", "checkout", "-b", name])

    def delete_branch(self, name: str, force: bool = False) -> tuple[int, str]:
        """Delete a branch."""
        cmd = ["git", "branch"]
        if force:
            cmd.append("-D")
        else:
            cmd.append("-d")
        cmd.append(name)
        return self._run_result(cmd)

    def rename_branch(self, new_name: str) -> tuple[int, str]:
        """Rename current branch."""
        return self._run_result(["git", "branch", "-m", new_name])

    # ==================== STAGE OPERATIONS ====================

    def stage_all(self) -> str:
        """Stage all changes."""
        code, output = self._run_result(["git", "add", "-A"])
        if code != 0:
            return output
        return ""

    def stage_files(self, files: list[str]) -> tuple[int, str]:
        """Stage specific files."""
        return self._run_result(["git", "add"] + files)

    def unstage_all(self) -> tuple[int, str]:
        """Unstage all changes."""
        return self._run_result(["git", "reset", "HEAD"])

    def unstage_file(self, file: str) -> tuple[int, str]:
        """Unstage a specific file."""
        return self._run_result(["git", "reset", "HEAD", file])

    # ==================== COMMIT OPERATIONS ====================

    def commit(self, message: str) -> tuple[int, str]:
        """Commit staged changes."""
        return self._run_result(["git", "commit", "-m", message])

    def amend_commit(self, message: Optional[str] = None) -> tuple[int, str]:
        """Amend the last commit."""
        cmd = ["git", "commit", "--amend"]
        if message:
            cmd.extend(["-m", message])
        return self._run_result(cmd)

    def get_last_commit_message(self) -> str:
        """Get the last commit message."""
        return self._run(["git", "log", "-1", "--pretty=%B"])

    # ==================== PUSH/PULL OPERATIONS ====================

    def push(self, upstream: bool = False) -> tuple[int, str]:
        """Push changes to remote."""
        if upstream:
            return self._run_result(["git", "push", "-u", "origin", self.current_branch()])
        return self._run_result(["git", "push"])

    def push_force(self) -> tuple[int, str]:
        """Force push changes (use with caution)."""
        return self._run_result(["git", "push", "--force-with-lease"])

    def pull(self) -> tuple[int, str]:
        """Pull changes from remote."""
        return self._run_result(["git", "pull"])

    # ==================== MERGE/REBASE OPERATIONS ====================

    def merge(self, branch: str) -> tuple[int, str]:
        """Merge a branch into current branch."""
        return self._run_result(["git", "merge", branch])

    def rebase(self, branch: str) -> tuple[int, str]:
        """Rebase current branch onto another branch."""
        return self._run_result(["git", "rebase", branch])

    def abort_merge(self) -> tuple[int, str]:
        """Abort a merge in progress."""
        return self._run_result(["git", "merge", "--abort"])

    def abort_rebase(self) -> tuple[int, str]:
        """Abort a rebase in progress."""
        return self._run_result(["git", "rebase", "--abort"])

    # ==================== STASH OPERATIONS ====================

    def stash(self, message: Optional[str] = None) -> tuple[int, str]:
        """Stash current changes."""
        cmd = ["git", "stash"]
        if message:
            cmd.extend(["push", "-m", message])
        return self._run_result(cmd)

    def stash_pop(self) -> tuple[int, str]:
        """Pop the most recent stash."""
        return self._run_result(["git", "stash", "pop"])

    def stash_list(self) -> list[dict[str, str]]:
        """List all stashes."""
        output = self._run(["git", "stash", "list"])
        if not output:
            return []
        
        stashes = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            # Parse stash entry: stash@{0}: On branch: message
            parts = line.split(": ", 1)
            if len(parts) == 2:
                stashes.append({
                    "ref": parts[0].strip(),
                    "message": parts[1].strip(),
                })
        return stashes

    def stash_drop(self, stash_ref: str = "stash@{0}") -> tuple[int, str]:
        """Drop a stash entry."""
        return self._run_result(["git", "stash", "drop", stash_ref])

    # ==================== DIFF OPERATIONS ====================

    def diff(self, staged: bool = False) -> str:
        """Get diff of changes."""
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        return self._run(cmd, check=False)

    def diff_files(self, file1: str, file2: str) -> str:
        """Diff two specific files."""
        return self._run(["git", "diff", file1, file2], check=False)

    # ==================== LOG OPERATIONS ====================

    def log(self, limit: int = 10) -> list[dict[str, str]]:
        """Get commit log."""
        output = self._run(
            ["git", "log", f"--max-count={limit}", "--pretty=format:%H|%h|%s|%an|%ai"],
            check=False,
        )
        if not output:
            return []
        
        commits = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append({
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "message": parts[2],
                    "author": parts[3],
                    "date": parts[4],
                })
        return commits

    # ==================== UTILITY METHODS ====================

    def current_hash(self) -> str:
        """Get current commit hash."""
        return self._run(["git", "rev-parse", "--short", "HEAD"]) or "none"

    def _run(self, args: list[str], check: bool = True) -> str:
        """Run a git command and return output."""
        code, output = self._run_result(args)
        if check and code != 0:
            return ""
        return output.strip()

    def _run_result(self, args: list[str]) -> tuple[int, str]:
        """Run a git command and return (exit_code, output)."""
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
