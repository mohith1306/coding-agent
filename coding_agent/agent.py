import difflib
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .context import AgentContext, ContextBuilder
from .intent import Intent, IntentParser
from .memory import MemoryStore
from .planner import Planner
from .tools.files import FileTools
from .tools.git import GitContext
from .tools.github import GitHubIntegration
from .tools.terminal import TerminalSandbox
from .verifier import Verifier


CODE_GEN_PROMPT = (Path(__file__).parent / "prompts" / "code_generation_prompt.md")

CONFIRMATION_MARKER = "CONFIRMATION_REQUIRED"


class CodingAgent:
    def __init__(self) -> None:
        self.root = Path.cwd()
        self.memory = MemoryStore()
        self.context_builder = ContextBuilder(self.memory)
        self.file_tools = FileTools(self.root)
        self.intent_parser = IntentParser()
        self.verifier = Verifier()
        self.terminal = TerminalSandbox(self.root)
        self.git = GitContext()
        self.github = GitHubIntegration(self.root)
        self.planner = Planner()

    def handle(self, user_message: str, confirmed: bool = False) -> str:
        intent = self.intent_parser.parse(user_message)

        if intent.requires_confirmation and not confirmed:
            return self._confirmation_prompt(intent)

        context = self.context_builder.build(user_message)
        tool_response = self._handle_intent(intent, context)

        self.memory.add_turn(
            user_message=user_message,
            agent_response=tool_response or "",
            intent=intent.name,
            target=intent.target,
        )

        if tool_response is not None:
            return tool_response

        return (
            f"I received your request and created an initial plan.\n\n"
            f"Context: {self.context_builder.format_for_prompt(context)}\n\n"
            "However, I could not determine a specific action to take."
        )

    def _confirmation_prompt(self, intent: Intent) -> str:
        lines = [
            CONFIRMATION_MARKER,
            f"Action: {intent.name}",
            f"Target: {intent.target or '(none)'}",
            f"Reason: {intent.reason or 'risky operation'}",
            "",
            "Reply with 'yes' to proceed, or anything else to cancel.",
        ]
        return "\n".join(lines)

    def _handle_intent(self, intent: Intent, context: Optional[AgentContext] = None) -> Optional[str]:
        if intent.name == "search_files":
            return self._handle_search(intent)
        if intent.name == "read_file":
            return self._handle_read(intent)
        if intent.name == "create_file":
            return self._handle_create_file(intent, context)
        if intent.name == "modify_code":
            return self._handle_modify_code(intent, context)
        if intent.name == "delete_file":
            return self._handle_delete_file(intent)
        if intent.name == "run_command":
            return self._handle_run_command(intent)
        if intent.name == "plan":
            return self._handle_plan(intent)
        if intent.name == "commit":
            return self._handle_commit(intent)
        if intent.name == "push":
            return self._handle_push(intent)
        if intent.name == "commit_and_push":
            return self._handle_commit(intent, push=True)
        if intent.name == "list_issues":
            return self._handle_list_issues(intent)
        if intent.name == "list_prs":
            return self._handle_list_prs(intent)
        if intent.name == "explain":
            ctx_str = self.context_builder.format_for_prompt(context) if context else ""
            parts = [f"Intent detected: explain.\nReason: {intent.reason}"]
            if ctx_str:
                parts.append(f"\n{ctx_str}")
            return "\n".join(parts)
        if intent.name == "unknown" and intent.reason:
            return f"I could not parse the intent. {intent.reason}"
        return None

    def _handle_run_command(self, intent: Intent) -> str:
        command = intent.target
        if not command:
            return "Usage: tell me which command to run, e.g. 'run python --version'"

        file_command = self._resolve_run_file(command)
        if file_command:
            return self.terminal.run(file_command)

        return self.terminal.run(command)

    def _resolve_run_file(self, command: str) -> Optional[str]:
        candidate = Path(command)
        if candidate.suffix:
            name = candidate.name
        else:
            name = f"{candidate.name}.py"

        matches = sorted(self.root.rglob(name))
        for match in matches:
            if match.is_file():
                try:
                    resolved = match.resolve()
                    if self.file_tools.exists(resolved):
                        relative = str(resolved.relative_to(self.root))
                        if resolved.suffix == ".py":
                            return f"python3 {relative}"
                        return f"{relative}"
                except PermissionError:
                    continue
        return None

    def _handle_plan(self, intent: Intent) -> str:
        plan = self.planner.create_plan(intent.raw_message)
        return f"Here's a plan:\n\n{plan.summary}"

    def _handle_commit(self, intent: Intent, push: bool = False) -> str:
        status = self.git.status()
        if status.is_clean:
            return "Nothing to commit. Working tree is clean."

        message = self._commit_message(intent, status)
        if not message:
            return "No commit message could be determined. Try 'commit <message>'."

        staged = self.git.stage_all()
        if staged:
            return f"Failed to stage changes:\n{staged}"

        code, output = self.git.commit(message)
        if code != 0:
            return f"Commit failed:\n{output}"

        lines = [f"Committed: `{message}` (hash: {self.git.current_hash()})"]
        if push:
            push_code, push_output = self.git.push()
            if push_code != 0:
                lines.append(f"Push failed:\n{self._short_error(push_output)}")
            else:
                lines.append("Pushed to origin.")
        return "\n".join(lines)

    def _commit_message(self, intent: Intent, status) -> str:
        if intent.target:
            return intent.target
        if status.dirty_files:
            names = ", ".join(status.dirty_files[:5])
            return f"Update {names}"
        return ""

    def _handle_push(self, intent: Intent) -> str:
        status = self.git.status()
        code, output = self.git.push()
        if code != 0:
            return f"Push failed:\n{self._short_error(output)}"
        lines = [f"Pushed to {status.branch}."]
        if status.ahead:
            lines.append(f"{status.ahead} commit(s) pushed.")
        return "\n".join(lines)

    def _short_error(self, output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return "\n".join(lines[:3]) if lines else output

    def _handle_list_issues(self, intent: Intent) -> str:
        state = intent.target or "open"
        issues = self.github.list_issues(state=state)
        if not issues:
            return "No issues found."
        if "error" in issues[0]:
            return issues[0]["error"]
        return "\n".join(
            f"#{issue['number']} [{issue['state']}] {issue['title']} ({issue['labels']})"
            for issue in issues
        )

    def _handle_list_prs(self, intent: Intent) -> str:
        state = intent.target or "open"
        prs = self.github.list_pull_requests(state=state)
        if not prs:
            return "No pull requests found."
        if "error" in prs[0]:
            return prs[0]["error"]
        return "\n".join(
            f"#{pr['number']} [{pr['state']}] {pr['title']} ({pr['branch']})"
            for pr in prs
        )

    def _handle_search(self, intent: Intent) -> str:
        argument = intent.target
        if not argument:
            return "Usage: search <glob-pattern>. Example: search **/*.py or search for .md file"

        try:
            matches = self.file_tools.search(self.root, argument)
        except PermissionError as error:
            return str(error)

        if not matches:
            return f"No files matched: {argument}"

        relative_matches = [str(path.relative_to(self.root)) for path in matches[:50]]
        extra_count = len(matches) - len(relative_matches)
        suffix = f"\n...and {extra_count} more" if extra_count else ""

        return "Matched files:\n" + "\n".join(relative_matches) + suffix

    def _handle_read(self, intent: Intent) -> str:
        argument = intent.target
        if not argument:
            return "Usage: read <file-path>. Example: read README.md or read README.md file"

        if "*" in argument:
            return self._read_glob(argument)

        resolved = self._resolve_path(argument)
        if resolved is None:
            return f"File not found: {argument}"

        try:
            content = self.file_tools.read_text(resolved)
        except Exception as error:
            return f"{error}\nTip: use `search **/*.md` to find markdown files."

        relative = str(resolved.relative_to(self.root))
        preview = content[:4000]
        suffix = "\n\n[Output truncated]" if len(content) > len(preview) else ""
        return f"Contents of {relative}:\n\n{preview}{suffix}"

    def _read_glob(self, pattern: str) -> str:
        matches = self.file_tools.search(self.root, pattern)
        if not matches:
            return f"No files matched: {pattern}"

        parts = []
        for match in matches[:15]:
            relative = str(match.relative_to(self.root))
            try:
                content = self.file_tools.read_text(match)
            except Exception:
                parts.append(f"## {relative}\n[Skipped: could not read as text]")
                continue

            preview = content[:3000]
            truncated = len(content) > len(preview)
            body = f"{preview}\n\n[Output truncated]" if truncated else preview
            parts.append(f"## {relative}\n\n{body}")

        extra = len(matches) - 15
        if extra > 0:
            parts.append(f"\n\n...and {extra} more file(s) matched but not shown.")

        return "\n\n---\n\n".join(parts)

    def _resolve_path(self, path_str: str) -> Optional[Path]:
        candidate = Path(path_str)
        if candidate.is_absolute():
            candidate = candidate.resolve()
        else:
            candidate = (self.root / path_str).resolve()

        try:
            if self.file_tools.exists(candidate):
                return candidate if candidate.is_file() else None
        except PermissionError:
            pass

        name = candidate.name
        matches = sorted(self.root.rglob(name))
        for m in matches:
            if m.is_file():
                try:
                    resolved = m.resolve()
                    if self.file_tools.exists(resolved):
                        return resolved
                except PermissionError:
                    continue

        return None

    def _handle_create_file(self, intent: Intent, context: Optional[AgentContext] = None) -> str:
        target = intent.target
        if not target:
            return "Usage: tell me which file to create, e.g. 'create hello.py'"

        target_path = Path(target)
        file_exists = False
        try:
            file_exists = self.file_tools.exists(target_path)
        except PermissionError:
            pass

        content = ""
        if intent.args and isinstance(intent.args, dict):
            content = intent.args.get("content", "")

        if not content:
            generated = self._generate_file_content(target, intent.raw_message, context)
            if generated:
                content = generated
            else:
                return (
                    f"I can create `{target}`."
                    + (" This file already exists and will be overwritten." if file_exists else "")
                    + " Tell me what content to write."
                )

        try:
            self.file_tools.write_text(target_path, content)
        except PermissionError as error:
            return str(error)

        action = "Overwritten" if file_exists else "Created"
        verification = self._verify_file(target_path, context)

        self.memory.add_file_event(target, action.lower(), content)

        preview = content[:500]
        truncated = len(content) > len(preview)
        body = f"{preview}\n\n[Output truncated]" if truncated else preview

        return f"{action} `{target}`:\n\n{body}\n\n{verification}"

    def _generate_file_content(self, target: str, raw_message: str, context: Optional[AgentContext] = None) -> str:
        ctx_block = ""
        if context:
            ctx_block = f"\n\nProject context:\n{self.context_builder.format_for_prompt(context)}\n"
        system_prompt = (
            f"You are a code generation assistant. Generate content for the file `{target}` "
            "based on the user's request. "
            "Return ONLY the raw file content. NO markdown fences, NO triple backticks, "
            "NO explanations, NO extra text of any kind. Just the code."
            f"{ctx_block}"
        )
        try:
            result = self.intent_parser.generate(system_prompt, raw_message)
            return result.strip()
        except Exception:
            return ""

    def _handle_modify_code(self, intent: Intent, context: Optional[AgentContext] = None) -> str:
        target = intent.target
        if not target:
            return "Usage: tell me which file to modify, e.g. 'add a function to utils.py'"

        resolved = self._resolve_path(target)
        if resolved is None:
            return f"File not found: {target}"

        try:
            current_content = self.file_tools.read_text(resolved)
        except Exception as error:
            return f"Could not read {target}: {error}"

        system_prompt = CODE_GEN_PROMPT.read_text(encoding="utf-8")
        ctx_block = ""
        if context:
            ctx_block = f"\n\nProject context:\n{self.context_builder.format_for_prompt(context)}\n"
        user_prompt = (
            f"Current file ({target}):\n\n```\n{current_content}\n```\n\n"
            f"User request: {intent.raw_message}{ctx_block}\n\n"
            "Return ONLY the complete new file content."
        )

        try:
            new_content = self.intent_parser.generate(system_prompt, user_prompt)
        except Exception as error:
            return f"Failed to generate edit: {error}"

        if not new_content or not new_content.strip():
            return "Generated content is empty. Please try again with a more specific request."

        if new_content.strip() == current_content.strip():
            return f"File `{target}` is already up to date. No changes were needed."

        try:
            self.file_tools.write_text(resolved, new_content)
        except PermissionError as error:
            return str(error)

        self.memory.add_file_event(target, "modified", new_content)

        diff_text = self._compute_diff(current_content, new_content, target)
        verification = self._verify_file(resolved, context)

        return (
            f"Modified `{target}`:\n\n"
            f"```diff\n{diff_text}\n```\n\n"
            f"{verification}"
        )

    def _handle_delete_file(self, intent: Intent) -> str:
        target = intent.target
        if not target:
            return "Usage: tell me which file to delete, e.g. 'delete test.txt'"

        resolved = self._resolve_path(target)
        if resolved is None:
            return f"File not found: {target}"

        try:
            resolved.unlink()
            self.memory.add_file_event(target, "deleted")
            return f"Deleted `{target}`."
        except Exception as error:
            return f"Failed to delete `{target}`: {error}"

    def _verify_file(self, path: Path, context: Optional[AgentContext] = None) -> str:
        parts = []
        if path.suffix == ".py":
            parts.append(self._verify_python(path))
        else:
            parts.append("File written successfully.")

        if context is not None:
            project_check = self._run_project_checks(context)
            if project_check:
                parts.append(project_check)

        return "\n".join(parts)

    def _run_project_checks(self, context: AgentContext) -> str:
        checks = []

        if context.has_lint_config:
            lint_cmd = self._lint_command(context.language)
            if lint_cmd:
                checks.append(("lint", lint_cmd, 20))

        if context.has_test_config:
            test_cmd = self._test_command(context.language)
            if test_cmd:
                checks.append(("test", test_cmd, 60))

        if not checks:
            return ""

        results = []
        for label, command, timeout in checks:
            result = self.terminal.run(command, timeout=timeout)
            passed = result.startswith("Exit code: 0")
            results.append(f"{'PASS' if passed else 'FAIL'} {label}: {command}")

        return "\n".join(results)

    def _lint_command(self, language: str) -> Optional[str]:
        if language == "python":
            return "python3 -m ruff check ."
        if language == "javascript":
            return "npx eslint ."
        if language == "typescript":
            return "npx eslint ."
        return None

    def _test_command(self, language: str) -> Optional[str]:
        if language == "python":
            return "python3 -m pytest"
        if language == "javascript":
            return "npm test"
        if language == "typescript":
            return "npm test"
        if language == "rust":
            return "cargo test"
        if language == "go":
            return "go test ./..."
        if language == "ruby":
            return "bundle exec rspec"
        return None

    def _verify_python(self, path: Path) -> str:
        abs_path = path.resolve()
        if not abs_path.is_file():
            return "File does not exist. Could not verify."

        rel_path = str(abs_path.relative_to(self.root))
        result = subprocess.run(
            [sys.executable, "-m", "compileall", str(abs_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return f"Verified `{rel_path}`: compiles clean."
        else:
            errors = result.stderr[:500] or result.stdout[:500]
            return f"Warning: `{rel_path}` has issues:\n{errors}"

    def _compute_diff(self, old: str, new: str, filename: str) -> str:
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3,
        )
        return "".join(diff)
