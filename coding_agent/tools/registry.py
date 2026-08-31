"""Tool Harness — wraps existing tools as LangChain @tool instances.

Each tool has: input schema, validation, execution, structured result, error handling.
The agent node binds these tools to the LLM for function calling.
"""

import logging
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from ..context import AgentContext
from ..tools.files import FileTools
from ..tools.terminal import TerminalSandbox
from ..tools.daytona_sandbox import DaytonaSandbox
from ..tools.git import GitContext
from ..tools.github import GitHubIntegration

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Manages all LangChain tools for the agent runtime.

    Holds references to the underlying infrastructure (FileTools, TerminalSandbox, etc.)
    and exposes them as LangChain @tool instances.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.file_tools = FileTools(self.root)
        self.terminal = self._build_terminal()
        self.git = GitContext(root=self.root)
        self.github = GitHubIntegration(self.root)
        self._tools = self._build_tools()

    def _build_terminal(self):
        if __import__("os").getenv("DAYTONA_API_KEY"):
            try:
                return DaytonaSandbox(self.root)
            except Exception as error:
                logger.warning("Daytona unavailable, falling back to local: %s", error)
        return TerminalSandbox(self.root)

    def _build_tools(self) -> list:
        """Build all tool instances bound to this registry's infrastructure."""
        registry = self

        @tool
        def read_file(path: str) -> str:
            """Read the contents of a file. Returns the full file text."""
            try:
                resolved = registry._resolve_path(path)
                if resolved is None:
                    return f"File not found: {path}"
                content = registry.file_tools.read_text(resolved)
                relative = str(resolved.relative_to(registry.root))
                preview = content[:8000]
                suffix = "\n\n[Output truncated]" if len(content) > len(preview) else ""
                return f"Contents of {relative}:\n\n{preview}{suffix}"
            except Exception as error:
                return f"Error reading {path}: {error}"

        @tool
        def write_file(path: str, content: str) -> str:
            """Write content to a file. Creates parent directories if needed. Overwrites existing files."""
            try:
                target = registry._resolve_write_path(path)
                registry.file_tools.write_text(target, content)
                relative = str(target.relative_to(registry.root))
                return f"Successfully wrote {len(content)} bytes to {relative}"
            except PermissionError as error:
                return f"Permission denied: {error}"
            except Exception as error:
                return f"Error writing {path}: {error}"

        @tool
        def list_files(pattern: str = "**/*") -> str:
            """List files matching a glob pattern. Default lists all files.

            Args:
                pattern: Glob pattern like **/*.py, src/**/*.ts, *.json
            """
            try:
                matches = registry.file_tools.search(registry.root, pattern)
                if not matches:
                    return f"No files matched: {pattern}"
                relative_matches = [str(p.relative_to(registry.root)) for p in matches[:100]]
                extra = len(matches) - len(relative_matches)
                suffix = f"\n...and {extra} more" if extra else ""
                return "Matched files:\n" + "\n".join(relative_matches) + suffix
            except Exception as error:
                return f"Error searching: {error}"

        @tool
        def search_files(query: str) -> str:
            """Search for a text string across all files in the project using ripgrep-like search.

            Args:
                query: Text string to search for (exact match)
            """
            try:
                import subprocess
                result = subprocess.run(
                    ["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.ts",
                     "--include=*.tsx", "--include=*.jsx", "--include=*.go", "--include=*.rs",
                     "--include=*.rb", "--include=*.java", "--include=*.c", "--include=*.cpp",
                     "--include=*.h", "--include=*.md", "--include=*.json", "--include=*.yaml",
                     "--include=*.yml", "--include=*.toml", "--include=*.cfg", query, "."],
                    cwd=str(registry.root),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                output = result.stdout.strip()
                if not output:
                    return f"No matches found for: {query}"
                lines = output.split("\n")
                if len(lines) > 50:
                    return "\n".join(lines[:50]) + f"\n\n...and {len(lines) - 50} more matches"
                return output
            except subprocess.TimeoutExpired:
                return f"Search timed out for: {query}"
            except Exception as error:
                return f"Search error: {error}"

        @tool
        def run_command(command: str, timeout: int = 30) -> str:
            """Run a shell command in the project workspace. Returns stdout, stderr, and exit code.

            Args:
                command: Shell command to execute
                timeout: Timeout in seconds (default 30)
            """
            return registry.terminal.run(command, timeout=timeout)

        @tool
        def run_tests(test_path: str = "") -> str:
            """Find and run test files in the project. If test_path is provided, runs that specific file.

            Args:
                test_path: Optional specific test file path to run
            """
            if test_path:
                resolved = registry._resolve_path(test_path)
                if resolved is None:
                    return f"Test file not found: {test_path}"
                rel = str(resolved.relative_to(registry.root))
                return registry.terminal.run(f"python3 {rel}", timeout=60)

            test_files = sorted(registry.root.rglob("*test*.py")) + sorted(registry.root.rglob("*_test.py"))
            if not test_files:
                return "No test files found matching *test*.py or *_test.py"

            results = []
            for tf in test_files[:10]:
                rel = str(tf.relative_to(registry.root))
                result = registry.terminal.run(f"python3 {rel}", timeout=30)
                passed = result.startswith("Exit code: 0")
                label = "PASS" if passed else "FAIL"
                results.append(f"[{label}] {rel}")
            return "Test results:\n" + "\n".join(results)

        @tool
        def git_status() -> str:
            """Get the current git status: branch, dirty files, ahead/behind counts."""
            status = registry.git.status()
            lines = [
                f"Branch: {status.branch}",
                f"Ahead: {status.ahead}, Behind: {status.behind}",
                f"Clean: {status.is_clean}",
            ]
            if status.dirty_files:
                lines.append(f"Dirty files ({len(status.dirty_files)}):")
                for f in status.dirty_files[:20]:
                    lines.append(f"  - {f}")
            return "\n".join(lines)

        @tool
        def git_diff(file_path: str = "") -> str:
            """Show git diff for a specific file or all changes.

            Args:
                file_path: Optional file to diff. If empty, shows all changes.
            """
            try:
                import subprocess
                args = ["git", "diff"]
                if file_path:
                    args.append(file_path)
                result = subprocess.run(
                    args,
                    cwd=str(registry.root),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                output = result.stdout.strip()
                if not output:
                    return "No changes to diff."
                if len(output) > 8000:
                    return output[:8000] + "\n\n[Diff truncated]"
                return output
            except Exception as error:
                return f"Git diff error: {error}"

        @tool
        def git_commit(message: str) -> str:
            """Stage all changes and create a git commit.

            Args:
                message: Commit message
            """
            staged = registry.git.stage_all()
            if staged:
                return f"Failed to stage: {staged}"
            code, output = registry.git.commit(message)
            if code != 0:
                return f"Commit failed: {output}"
            return f"Committed: {message} (hash: {registry.git.current_hash()})"

        @tool
        def git_push() -> str:
            """Push committed changes to the remote origin."""
            code, output = registry.git.push()
            if code != 0:
                return f"Push failed: {output}"
            status = registry.git.status()
            return f"Pushed to {status.branch}."

        @tool
        def github_list_issues(state: str = "open", limit: int = 10) -> str:
            """List GitHub issues for the current repository.

            Args:
                state: Issue state filter (open, closed, all). Default: open.
                limit: Maximum number of issues to return. Default: 10.
            """
            issues = registry.github.list_issues(state=state, limit=limit)
            if not issues:
                return "No issues found."
            if "error" in issues[0]:
                return issues[0]["error"]
            lines = [
                f"#{issue['number']} [{issue['state']}] {issue['title']} ({issue['labels']})"
                for issue in issues
            ]
            return "Issues:\n" + "\n".join(lines)

        @tool
        def github_list_prs(state: str = "open", limit: int = 10) -> str:
            """List GitHub pull requests for the current repository.

            Args:
                state: PR state filter (open, closed, all). Default: open.
                limit: Maximum number of PRs to return. Default: 10.
            """
            prs = registry.github.list_pull_requests(state=state, limit=limit)
            if not prs:
                return "No pull requests found."
            if "error" in prs[0]:
                return prs[0]["error"]
            lines = [
                f"#{pr['number']} [{pr['state']}] {pr['title']} ({pr['branch']})"
                for pr in prs
            ]
            return "Pull requests:\n" + "\n".join(lines)

        return [
            read_file,
            write_file,
            list_files,
            search_files,
            run_command,
            run_tests,
            git_status,
            git_diff,
            git_commit,
            git_push,
            github_list_issues,
            github_list_prs,
        ]

    def get_tools(self) -> list:
        """Return all LangChain tool instances."""
        return self._tools

    def get_tool_by_name(self, name: str):
        """Get a specific tool by name."""
        for t in self._tools:
            if t.name == name:
                return t
        return None

    def close(self) -> None:
        """Clean up sandbox resources."""
        try:
            self.terminal.close()
        except Exception:
            pass

    # ── Path resolution (mirrors CodingAgent._resolve_path) ──────

    def _resolve_path(self, path_str: str) -> Optional[Path]:
        candidate = Path(path_str)
        if candidate.is_absolute():
            candidate = candidate.resolve()
        else:
            candidate = (self.root / path_str).resolve()

        if candidate.is_file():
            return candidate

        folded = candidate.name.lower()
        for m in sorted(self.root.rglob("*")):
            if m.is_file() and m.name.lower() == folded:
                try:
                    resolved = m.resolve()
                    if self.file_tools.exists(resolved):
                        return resolved
                except PermissionError:
                    continue
        return None

    def _resolve_write_path(self, path_str: str) -> Path:
        candidate = Path(path_str)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.root / path_str).resolve()
