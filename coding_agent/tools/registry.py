"""Tool Harness — wraps existing tools as LangChain @tool instances.

Each tool has: input schema, validation, execution, structured result, error handling.
The agent node binds these tools to the LLM for function calling.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from ..context import AgentContext
from ..tools.files import FileTools
from ..tools.terminal import TerminalSandbox
from ..tools.docker_sandbox import DockerSandbox
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
        """Build terminal sandbox with Docker support."""
        # Priority: Docker > Daytona > Local
        if os.getenv("USE_DOCKER_SANDBOX", "true").lower() == "true":
            try:
                return DockerSandbox(self.root)
            except Exception as error:
                logger.warning("Docker unavailable, trying Daytona: %s", error)

        if os.getenv("DAYTONA_API_KEY"):
            try:
                return DaytonaSandbox(self.root)
            except Exception as error:
                logger.warning("Daytona unavailable, falling back to local: %s", error)

        return TerminalSandbox(self.root)

    def _build_tools(self) -> list:
        """Build all tool instances bound to this registry's infrastructure."""
        registry = self

        # ==================== FILE TOOLS ====================

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

        # ==================== EXECUTION TOOLS ====================

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

        # ==================== GIT TOOLS ====================

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
        def git_push(upstream: bool = False) -> str:
            """Push committed changes to the remote origin.

            Args:
                upstream: If True, set upstream branch. Default: False.
            """
            code, output = registry.git.push(upstream=upstream)
            if code != 0:
                return f"Push failed: {output}"
            status = registry.git.status()
            return f"Pushed to {status.branch}."

        @tool
        def git_create_branch(branch_name: str) -> str:
            """Create a new git branch.

            Args:
                branch_name: Name of the new branch
            """
            code, output = registry.git.create_branch(branch_name)
            if code != 0:
                return f"Failed to create branch: {output}"
            return f"Created branch: {branch_name}"

        @tool
        def git_checkout(branch_name: str) -> str:
            """Checkout to a git branch.

            Args:
                branch_name: Name of the branch to checkout
            """
            code, output = registry.git.checkout(branch_name)
            if code != 0:
                return f"Failed to checkout: {output}"
            return f"Checked out to branch: {branch_name}"

        @tool
        def git_create_and_checkout(branch_name: str) -> str:
            """Create a new branch and checkout to it.

            Args:
                branch_name: Name of the new branch
            """
            code, output = registry.git.create_and_checkout(branch_name)
            if code != 0:
                return f"Failed to create and checkout: {output}"
            return f"Created and checked out branch: {branch_name}"

        @tool
        def git_delete_branch(branch_name: str) -> str:
            """Delete a git branch.

            Args:
                branch_name: Name of the branch to delete
            """
            code, output = registry.git.delete_branch(branch_name)
            if code != 0:
                return f"Failed to delete branch: {output}"
            return f"Deleted branch: {branch_name}"

        @tool
        def git_list_branches() -> str:
            """List all local git branches."""
            branches = registry.git.list_branches()
            if not branches:
                return "No branches found."
            current = registry.git.current_branch()
            lines = []
            for b in branches:
                prefix = "* " if b == current else "  "
                lines.append(f"{prefix}{b}")
            return "Branches:\n" + "\n".join(lines)

        @tool
        def git_merge(branch_name: str) -> str:
            """Merge a branch into the current branch.

            Args:
                branch_name: Branch to merge
            """
            code, output = registry.git.merge(branch_name)
            if code != 0:
                return f"Merge failed: {output}"
            return f"Merged branch: {branch_name}"

        @tool
        def git_stash(message: str = "") -> str:
            """Stash current changes.

            Args:
                message: Optional stash message
            """
            code, output = registry.git.stash(message=message if message else None)
            if code != 0:
                return f"Stash failed: {output}"
            return "Changes stashed."

        @tool
        def git_stash_pop() -> str:
            """Pop the most recent stash."""
            code, output = registry.git.stash_pop()
            if code != 0:
                return f"Stash pop failed: {output}"
            return "Stash popped."

        # ==================== GITHUB TOOLS ====================

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
            if isinstance(issues, dict) and "error" in issues:
                return issues["error"]
            if isinstance(issues, list) and issues and isinstance(issues[0], dict) and "error" in issues[0]:
                return issues[0]["error"]
            lines = [
                f"#{issue['number']} [{issue['state']}] {issue['title']} ({issue.get('labels', '')})"
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
            if isinstance(prs, dict) and "error" in prs:
                return prs["error"]
            if isinstance(prs, list) and prs and isinstance(prs[0], dict) and "error" in prs[0]:
                return prs[0]["error"]
            lines = [
                f"#{pr['number']} [{pr['state']}] {pr['title']} ({pr.get('branch', '')})"
                for pr in prs
            ]
            return "Pull requests:\n" + "\n".join(lines)

        @tool
        def github_create_pr(title: str, body: str, head: str, base: str = "main") -> str:
            """Create a new pull request on GitHub.

            Args:
                title: PR title
                body: PR description
                head: Branch with changes (e.g., 'feature/my-fix')
                base: Branch to merge into (default: 'main')
            """
            result = registry.github.create_pull_request(title, body, head, base)
            if "error" in result:
                return f"Failed to create PR: {result['error']}"
            return f"Created PR: {result.get('html_url', result.get('number', 'unknown'))}"

        @tool
        def github_create_issue(title: str, body: str = "", labels: str = "") -> str:
            """Create a new issue on GitHub.

            Args:
                title: Issue title
                body: Issue description
                labels: Comma-separated list of labels (e.g., 'bug,enhancement')
            """
            label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
            result = registry.github.create_issue(title, body, labels=label_list if label_list else None)
            if "error" in result:
                return f"Failed to create issue: {result['error']}"
            return f"Created issue: {result.get('html_url', result.get('number', 'unknown'))}"

        @tool
        def github_add_comment(issue_number: int, body: str) -> str:
            """Add a comment to a GitHub issue or pull request.

            Args:
                issue_number: Issue or PR number
                body: Comment content
            """
            result = registry.github.add_comment(issue_number, body)
            if "error" in result:
                return f"Failed to add comment: {result['error']}"
            return f"Added comment to #{issue_number}"

        @tool
        def github_close_issue(issue_number: int) -> str:
            """Close a GitHub issue.

            Args:
                issue_number: Issue number to close
            """
            result = registry.github.close_issue(issue_number)
            if "error" in result:
                return f"Failed to close issue: {result['error']}"
            return f"Closed issue #{issue_number}"

        @tool
        def github_assign_reviewers(pr_number: int, reviewers: str) -> str:
            """Assign reviewers to a pull request.

            Args:
                pr_number: PR number
                reviewers: Comma-separated list of GitHub usernames
            """
            reviewer_list = [r.strip() for r in reviewers.split(",") if r.strip()]
            if not reviewer_list:
                return "No reviewers provided."
            result = registry.github.assign_reviewers(pr_number, reviewer_list)
            if "error" in result:
                return f"Failed to assign reviewers: {result['error']}"
            return f"Assigned reviewers to PR #{pr_number}: {', '.join(reviewer_list)}"

        @tool
        def github_merge_pr(pr_number: int, merge_method: str = "merge") -> str:
            """Merge a pull request.

            Args:
                pr_number: PR number to merge
                merge_method: Merge method (merge, squash, rebase). Default: merge.
            """
            result = registry.github.merge_pull_request(pr_number, merge_method)
            if "error" in result:
                return f"Failed to merge PR: {result['error']}"
            return f"Merged PR #{pr_number}"

        @tool
        def github_get_file(path: str, ref: str = "main") -> str:
            """Get file content from GitHub repository.

            Args:
                path: File path in repository
                ref: Branch or commit ref (default: main)
            """
            result = registry.github.get_file_content(path, ref)
            if "error" in result:
                return f"Failed to get file: {result['error']}"
            content = result.get("content", "")
            if len(content) > 8000:
                content = content[:8000] + "\n\n[Content truncated]"
            return f"File: {path} (ref: {ref})\n\n{content}"

        @tool
        def github_list_branches() -> str:
            """List all branches in the GitHub repository."""
            branches = registry.github.list_branches()
            if not branches:
                return "No branches found."
            if isinstance(branches, dict) and "error" in branches:
                return branches["error"]
            lines = [f"{b['name']} ({b['sha'][:8]})" for b in branches]
            return "Remote branches:\n" + "\n".join(lines)

        return [
            # File tools
            read_file,
            write_file,
            list_files,
            search_files,
            # Execution tools
            run_command,
            run_tests,
            # Git tools
            git_status,
            git_diff,
            git_commit,
            git_push,
            git_create_branch,
            git_checkout,
            git_create_and_checkout,
            git_delete_branch,
            git_list_branches,
            git_merge,
            git_stash,
            git_stash_pop,
            # GitHub tools
            github_list_issues,
            github_list_prs,
            github_create_pr,
            github_create_issue,
            github_add_comment,
            github_close_issue,
            github_assign_reviewers,
            github_merge_pr,
            github_get_file,
            github_list_branches,
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
