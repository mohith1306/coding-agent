import difflib
import json
import logging
import os
from pathlib import Path
from typing import Optional

from .compaction import CompactionManager
from .context import AgentContext, ContextBuilder
from .events import emit, sink_active
from .intent import Intent, IntentParser
from .memory import MemoryStore
from .planner import Planner
from .tools.daytona_sandbox import DaytonaSandbox
from .tools.files import FileTools
from .tools.git import GitContext
from .tools.github import GitHubIntegration
from .tools.terminal import TerminalSandbox
from .verifier import Verifier


CODE_GEN_PROMPT = (Path(__file__).parent / "prompts" / "code_generation_prompt.md")
REPAIR_PROMPT = (Path(__file__).parent / "prompts" / "repair_prompt.md")
QUESTION_PROMPT = (Path(__file__).parent / "prompts" / "question_prompt.md")
PROJECT_MANIFEST_PROMPT = (Path(__file__).parent / "prompts" / "project_manifest_prompt.md")

MAX_REPAIR_ATTEMPTS = 3

CONFIRMATION_MARKER = "CONFIRMATION_REQUIRED"

logger = logging.getLogger(__name__)


class CodingAgent:
    def __init__(self, memory: Optional[MemoryStore] = None, root: Optional[Path] = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self.memory = memory or MemoryStore()
        self.context_builder = ContextBuilder(self.memory, root=self.root)
        self.file_tools = FileTools(self.root)
        self.intent_parser = IntentParser()
        self.terminal = self._build_terminal()
        self.verifier = Verifier(root=self.root, terminal=self.terminal)
        self.git = GitContext(root=self.root)
        self.github = GitHubIntegration(self.root)
        self.planner = Planner()
        self.compaction = CompactionManager(
            self.memory,
            generate=self._generate_summary,
            summary_key="compaction_summary",
        )
        self._pending_edits: dict[str, str] = {}
        self._pending_intents: dict[str, Intent] = {}
        self._pending_project_targets: dict[str, list[str]] = {}

    def handle(self, user_message: str, confirmed: bool = False) -> str:
        emit({"type": "phase", "message": "Parsing your request…"})
        history: list[dict[str, str]] = []
        try:
            history = self.memory.recent_turns(limit=6)
        except Exception as error:
            logger.warning("Failed to load chat history for intent parsing: %s", error)
        intent = self.intent_parser.parse(user_message, history=history)
        logger.info(
            "Intent: %s target=%r confidence=%s confirmed=%s",
            intent.name,
            intent.target,
            intent.confidence,
            confirmed,
        )

        if confirmed and intent.name == "unknown" and "Intent parser failed" in intent.reason:
            pending = self._pending_intents.pop(user_message, None)
            if pending is not None:
                logger.warning(
                    "Confirmed request parse failed; replaying pending intent %s",
                    pending.name,
                )
                intent = pending

        if intent.requires_confirmation and not confirmed:
            logger.info("Intent %s requires confirmation; asking user", intent.name)
            self._pending_intents[user_message] = intent
            return self._confirmation_prompt(intent)

        emit({"type": "intent", "name": intent.name, "target": intent.target or ""})
        emit({
            "type": "action",
            "action": intent.name,
            "target": intent.target or "",
            "bullets": self._action_bullets(intent),
        })
        emit({"type": "phase", "message": f"Performing {intent.name}…"})
        context = self.context_builder.build(user_message)
        tool_response = self._handle_intent(intent, context, confirmed=confirmed)
        logger.info("Intent %s handled (confirmed=%s)", intent.name, confirmed)

        self.memory.add_turn(
            user_message=user_message,
            agent_response=tool_response or "",
            intent=intent.name,
            target=intent.target,
        )

        self._maybe_compact()

        if tool_response is not None:
            return tool_response

        return (
            f"I received your request and created an initial plan.\n\n"
            f"Context: {self.context_builder.format_for_prompt(context)}\n\n"
            "However, I could not determine a specific action to take."
        )

    def _build_terminal(self):
        if os.getenv("DAYTONA_API_KEY"):
            try:
                return DaytonaSandbox(self.root)
            except Exception as error:
                logger.warning("Failed to initialize Daytona sandbox, falling back to local: %s", error)
        return TerminalSandbox(self.root)

    def _action_bullets(self, intent: Intent) -> list[str]:
        target = f" `{intent.target}`" if intent.target else ""
        if intent.name in {"create_file", "create_files", "create_project"}:
            return [
                f"I’ll generate the requested file content{target}.",
                "I’ll write the files into the project workspace.",
                "I’ll verify the result and run a quick test where applicable.",
            ]
        if intent.name == "modify_code":
            return [
                f"I’ll inspect the current contents of{target} first.",
                "I’ll generate the smallest change that addresses your request.",
                "I’ll verify the updated file and repair it if a check fails.",
            ]
        if intent.name in {"run_command", "run_file"}:
            return [
                "I’ll run the requested command in the project workspace.",
                "I’ll stream its output so you can see what happens.",
            ]
        if intent.name in {"read_file", "search_code", "list_files"}:
            return [
                f"I’ll inspect the project{target} to gather the relevant context.",
                "I’ll report the useful results without changing files.",
            ]
        return [
            f"I’ll handle this as a `{intent.name}` request.",
            "I’ll explain the result once the action completes.",
        ]

    def _maybe_compact(self) -> None:
        try:
            if self.compaction.should_compact():
                logger.info("Context hit %d tokens; compacting", self.compaction.current_tokens())
                self.compaction.compact()
        except Exception as error:
            logger.warning("Compaction failed: %s", error)

    def _generate_summary(self, system_prompt: str, user_prompt: str) -> str:
        try:
            return self.intent_parser.generate(system_prompt, user_prompt)
        except Exception as error:
            logger.warning("Summary generation failed: %s", error)
            return ""

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

    def _edit_confirmation_prompt(self, action: str, target: str, reason: str, preview: str, language: str = "python") -> str:
        preview = preview[:2000]
        lines = [
            CONFIRMATION_MARKER,
            f"Action: {action}",
            f"Target: {target}",
            f"Reason: {reason}",
            "",
            f"Make this change to `{target}`?",
            "",
            f"```{language}",
            preview,
            "```",
            "",
            "Reply with 'yes' to proceed, or 'no' to cancel.",
        ]
        return "\n".join(lines)

    def _handle_intent(self, intent: Intent, context: Optional[AgentContext] = None, confirmed: bool = False) -> Optional[str]:
        if intent.name == "search_files":
            return self._handle_search(intent)
        if intent.name == "read_file":
            return self._handle_read(intent)
        if intent.name == "create_file":
            return self._handle_create_file(intent, context, confirmed)
        if intent.name == "create_files":
            return self._handle_create_files(intent, context, confirmed)
        if intent.name == "create_project":
            return self._handle_create_project(intent, context, confirmed)
        if intent.name == "modify_code":
            return self._handle_modify_code(intent, context, confirmed)
        if intent.name == "delete_file":
            return self._handle_delete_file(intent)
        if intent.name == "run_command":
            return self._handle_run_command(intent)
        if intent.name == "plan":
            return self._handle_plan(intent, context, confirmed)
        if intent.name == "remember":
            return self._handle_remember(intent)
        if intent.name == "recall":
            return self._handle_recall(intent)
        if intent.name == "list_tasks":
            return self._handle_list_tasks(intent)
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
        if intent.name == "analyze_project":
            return self._handle_analyze_project(intent, context)
        if intent.name == "run_tests":
            return self._handle_run_tests(intent, context)
        if intent.name == "explain":
            return self._handle_question(intent, context)
        if intent.name == "unknown" and intent.reason:
            return self._handle_question(intent, context, fallback=f"I could not parse the intent. {intent.reason}")
        return None

    def _handle_run_command(self, intent: Intent) -> str:
        command = intent.target
        if not command:
            return "Usage: tell me which command to run, e.g. 'run python --version'"

        file_command = self._resolve_run_file(command)
        if file_command:
            emit({"type": "phase", "message": f"Running `{file_command}`…"})
            return self.terminal.run(file_command)

        if self._is_local_git_clone(command):
            emit({"type": "phase", "message": "Cloning into the local workspace…"})
            return TerminalSandbox(self.root).run(command)

        emit({"type": "phase", "message": f"Running `{command}`…"})
        return self.terminal.run(command)

    def _is_local_git_clone(self, command: str) -> bool:
        tokens = command.strip().split()
        if len(tokens) < 2 or tokens[0] != "git" or tokens[1] != "clone":
            return False
        # git clone must happen in the local workspace so the file browser can see it;
        # a remote sandbox would swallow the new files in its own filesystem.
        return any(
            token.startswith(("http://", "https://", "git@", "ssh://"))
            or token.endswith(".git")
            for token in tokens[2:]
        )

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

    def _test_python_file(self, path: Path) -> str:
        try:
            rel = str(path.resolve().relative_to(self.root))
        except ValueError:
            rel = str(path)
        result = self.terminal.run(f"python3 {rel}", timeout=30)
        passed = result.startswith("Exit code: 0")
        label = "PASS" if passed else "FAIL"
        return f"Sandbox test: [{label}] python3 {rel}\n{result}"

    def _repair_python_file(self, path: Path, content: str, error: str, context: Optional[AgentContext] = None) -> str:
        system_prompt = REPAIR_PROMPT.read_text(encoding="utf-8")
        ctx_block = ""
        if context:
            ctx_block = f"\n\nProject context:\n{self.context_builder.format_for_prompt(context)}\n"
        user_prompt = (
            f"The file `{path.name}` failed to compile or run with this error:\n\n"
            f"{error}\n\n"
            f"Current file content:\n\n```\n{content}\n```\n\n"
            f"Return ONLY the complete corrected file content.{ctx_block}"
        )
        try:
            result = self.intent_parser.generate(system_prompt, user_prompt)
            return self._strip_code_fences(result)
        except Exception:
            return content

    def _write_and_verify(
        self,
        resolved_path: Path,
        content: str,
        context: Optional[AgentContext] = None,
        max_retries: int = MAX_REPAIR_ATTEMPTS,
    ) -> tuple[str, str, str, int]:
        """Write content, verify it compiles, and run the sandbox test. On failure,
        feed the error back to the LLM to repair the file and retry. Returns
        (final_content, verification, test_output, retries_used)."""
        current = content
        attempts = 0
        rel = str(resolved_path.relative_to(self.root)) if self.root in resolved_path.parents else str(resolved_path)
        while True:
            emit({"type": "phase", "message": f"Writing {rel}…"})
            self.file_tools.write_text(resolved_path, current)
            emit({"type": "phase", "message": f"Verifying {rel}…"})
            verification = self.verifier.verify_file(resolved_path, context)
            compile_ok = "compiles clean" in verification
            test_output = ""
            if resolved_path.suffix == ".py":
                if compile_ok:
                    emit({"type": "phase", "message": f"Testing {rel}…"})
                    test_output = self._test_python_file(resolved_path)
                else:
                    test_output = ""

            passed = True
            if resolved_path.suffix == ".py":
                passed = compile_ok and test_output.startswith("Sandbox test: [PASS]")

            logger.info(
                "Write+verify %s: compile=%s sandbox_test=%s",
                rel,
                "ok" if compile_ok else "FAILED",
                "ok" if test_output.startswith("Sandbox test: [PASS]") else (test_output or "n/a"),
            )

            if passed:
                logger.info("File %s verified OK", rel)
                return current, verification, test_output, attempts
            if attempts >= max_retries:
                logger.warning("File %s still failing after %d repair attempt(s)", rel, attempts)
                return current, verification, test_output, attempts

            error_detail = verification
            if test_output:
                error_detail = f"{verification}\n{test_output}"
            attempts += 1
            emit({"type": "phase", "message": f"Repairing {rel}… (attempt {attempts}/{max_retries})"})
            logger.info("Repair attempt %d/%d for %s", attempts, max_retries, rel)
            repaired = self._repair_python_file(resolved_path, current, error_detail, context)
            if not repaired or repaired == current:
                logger.warning("Repair for %s produced no change; giving up", rel)
                return current, verification, test_output, attempts
            current = repaired

    def _retry_note(self, verification: str, test_output: str, retries: int) -> str:
        if retries <= 0:
            return ""
        passed = "compiles clean" in verification and (
            "Sandbox test: [PASS]" in test_output or not test_output
        )
        plural = "s" if retries != 1 else ""
        if passed:
            return f" (repaired after {retries} attempt{plural})"
        return f" (could not repair after {retries} attempt{plural})"

    @staticmethod
    def _strip_code_fences(content: str) -> str:
        text = content.strip()
        lines = text.splitlines()
        open_idx = next((i for i, line in enumerate(lines) if line.strip().startswith("```")), None)
        if open_idx is None:
            return content
        body = lines[open_idx + 1:]
        close_idx = next((i for i, line in enumerate(body) if line.strip().startswith("```")), None)
        if close_idx is not None:
            body = body[:close_idx]
        return "\n".join(body).strip()

    def _handle_plan(self, intent: Intent, context: Optional[AgentContext] = None, confirmed: bool = False) -> str:
        plan = self.planner.create_plan(intent.raw_message, intent.target)

        if not plan.executable or not plan.target:
            return self._handle_question(intent, context, planning=True)

        if not confirmed:
            return self._plan_confirmation_prompt(plan)

        return self._execute_plan(plan, intent, context)

    def _handle_question(
        self,
        intent: Intent,
        context: Optional[AgentContext] = None,
        planning: bool = False,
        fallback: str = "",
    ) -> str:
        system_prompt = QUESTION_PROMPT.read_text(encoding="utf-8")
        ctx_block = ""
        if context:
            ctx_block = f"\n\nProject context:\n{self.context_builder.format_for_prompt(context)}\n"
        header = "The user asked you to plan a feature or project." if planning else "The user asked you a question."
        user_prompt = f"{header}\n\nUser: {intent.raw_message}{ctx_block}"
        parts: list[str] = []
        try:
            if sink_active():
                for token in self.intent_parser.stream(system_prompt, user_prompt):
                    if token:
                        parts.append(token)
                        emit({"type": "chunk", "text": token})
            else:
                parts.append(self.intent_parser.generate(system_prompt, user_prompt))
        except Exception as error:
            logger.warning("Failed to generate answer: %s", error)
            return fallback or f"Sorry, I couldn't answer that. {error}"
        answer = "".join(parts).strip()
        if not answer:
            return fallback or "I don't have a useful answer for that right now."
        return answer

    def _plan_confirmation_prompt(self, plan) -> str:
        lines = [
            CONFIRMATION_MARKER,
            f"Action: plan_execute",
            f"Target: {plan.target or '(none)'}",
            "Reason: executing this plan will modify files.",
            "",
            "Reply with 'yes' to proceed, or anything else to cancel.",
        ]
        return "\n".join(lines)

    def _execute_plan(self, plan, intent: Intent, context: Optional[AgentContext] = None) -> str:
        outputs = []
        target = plan.target
        resolved = self._resolve_path(target)

        if resolved is None:
            create_intent = Intent(
                name="create_file",
                target=target,
                args=intent.args,
                raw_message=intent.raw_message,
                confidence=0.9,
            )
            outputs.append(self._handle_create_file(create_intent, context, confirmed=True))
        else:
            modify_intent = Intent(
                name="modify_code",
                target=target,
                args=intent.args,
                raw_message=intent.raw_message,
                confidence=0.9,
            )
            outputs.append(self._handle_modify_code(modify_intent, context, confirmed=True))

        return "Plan executed:\n\n" + "\n\n".join(outputs)

    def _handle_remember(self, intent: Intent) -> str:
        key = intent.target or ""
        value = ""
        if intent.args and isinstance(intent.args, dict):
            value = intent.args.get("value", "") or ""
        if not key or not value:
            return "Usage: remember <key> with value <value>, e.g. 'remember name with value Mohith'"
        self.memory.set_preference(key, value)
        return f"Remembered: `{key}` = `{value}`."

    def _handle_recall(self, intent: Intent) -> str:
        prefs = self.memory.list_preferences()
        if not prefs:
            return "I don't have anything stored yet."
        return "\n".join(f"{p['key']}: {p['value']}" for p in prefs)

    def _handle_list_tasks(self, intent: Intent) -> str:
        tasks = self.memory.get_by_type("task", limit=10)
        if not tasks:
            return "No tasks recorded yet."
        lines = []
        for task in tasks:
            meta = task["metadata"]
            status = meta.get("status", "unknown")
            files = meta.get("files_affected", "")
            line = f"[{status}] {meta.get('description', '')}"
            if files:
                line += f" ({files})"
            lines.append(line)
        return "\n".join(lines)

    def _handle_analyze_project(self, intent: Intent, context: Optional[AgentContext] = None) -> str:
        summary_parts = []

        # 1. Project overview from context builder
        overview = self.context_builder.build("")
        if overview:
            summary_parts.append(f"## Project Overview\n{overview}")

        # 2. Detect key files (entry points, tests, configs)
        key_files = []
        for entry in self.root.rglob("*"):
            if entry.is_file():
                suffix = entry.suffix
                name = entry.name.lower()
                # Entry points
                if suffix in {".py"} and any(kw in name for kw in {"__init__", "app", "main", "server"}):
                    key_files.append((entry, "entry point"))
                # Test files
                elif any(keyword in name for keyword in {"test", "spec"}):
                    key_files.append((entry, "test file"))
                # Config files
                elif suffix in {".json", ".yml", ".yaml", ".toml", ".cfg", ".ini"}:
                    key_files.append((entry, "config file"))
                # Markdown docs
                elif suffix == ".md":
                    key_files.append((entry, "documentation"))

        if key_files:
            summary_parts.append("## Key Files Detected")
            for path, kind in key_files[:10]:  # show first 10
                rel = str(path.relative_to(self.root))
                summary_parts.append(f"- **{rel}** ({kind})")

        # 3. Detected intent patterns from recent turns
        recent = self.memory.recent_turns(limit=3)
        if recent:
            summary_parts.append("## Recent Activity")
            for turn in recent:
                role = turn.get("role", "user")
                msg = turn.get("message", "")[:80]
                summary_parts.append(f"- **{role}**: {msg}")

        if not summary_parts:
            return "I couldn't detect any project structure or recent activity. Ensure the project has recognizable files (Python files, tests, configs, or markdown docs)."

        return "\n".join(summary_parts)

    def _handle_run_tests(self, intent: Intent, context: Optional[AgentContext] = None) -> str:
        # Find test files in the project
        test_files = sorted(self.root.rglob("*test*.py")) + sorted(self.root.rglob("*_test.py"))
        if not test_files:
            return "No test files found in the project root. Add test files matching `*test*.py` or `*_test.py`."

        results = []
        all_passed = True
        for test_file in test_files[:10]:  # limit to first 10 test files
            result = self._test_python_file(test_file)
            results.append(f"**{test_file.name}**: {result}")
            if "PASS" not in result:
                all_passed = False

        summary = f"## Test Execution Results\n"
        summary += f"- **Files run**: {len(test_files)}\n"
        summary += f"- **All passed**: {all_passed}\n"
        summary += "\n".join(results)

        if all_passed:
            summary += "\n✅ All tests passed!"
        else:
            summary += "\n❌ Some tests failed."

        return summary

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

    def _canonical_path(self, candidate: Path) -> Optional[Path]:
        try:
            rel = candidate.relative_to(self.root)
        except ValueError:
            return candidate if candidate.exists() else None

        current = self.root
        for part in rel.parts:
            try:
                entries = [e for e in os.listdir(current) if e.lower() == part.lower()]
            except OSError:
                return None
            if len(entries) == 1:
                current = current / entries[0]
            else:
                return None
        return current if current.exists() else None

    def _resolve_path(self, path_str: str) -> Optional[Path]:
        candidate = Path(path_str)
        if candidate.is_absolute():
            candidate = candidate.resolve()
        else:
            candidate = (self.root / path_str).resolve()

        canonical = self._canonical_path(candidate)
        if canonical is not None and canonical.is_file():
            return canonical

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

    def _handle_create_file(self, intent: Intent, context: Optional[AgentContext] = None, confirmed: bool = False) -> str:
        target = intent.target
        if not target:
            return "Usage: tell me which file to create, e.g. 'create hello.py'"

        is_python = target.lower().endswith(".py")

        target_path = Path(target)
        file_exists = False
        try:
            file_exists = self.file_tools.exists(target_path)
        except PermissionError:
            pass

        cached = self._pending_edits.get(target)
        content = ""
        if intent.args and isinstance(intent.args, dict):
            content = intent.args.get("content", "")

        if not content:
            if confirmed and cached:
                content = cached
            else:
                generated = self._generate_file_content(target, intent.raw_message, context)
                if generated:
                    content = generated
                else:
                    return (
                        f"I can create `{target}`."
                        + (" This file already exists and will be overwritten." if file_exists else "")
                        + " Tell me what content to write."
                    )

        if is_python and not confirmed:
            self._pending_edits[target] = content
            return self._edit_confirmation_prompt(
                "create_file",
                target,
                reason=f"create the file `{target}`",
                preview=content,
            )

        self._pending_edits.pop(target, None)

        resolved_path = target_path if target_path.is_absolute() else (self.root / target_path).resolve()

        action = "Overwritten" if file_exists else "Created"
        try:
            content, verification, test_output, retries = self._write_and_verify(
                resolved_path, content, context
            )
        except PermissionError as error:
            return str(error)

        retry_note = self._retry_note(verification, test_output, retries)

        self.memory.add_file_event(target, action.lower(), content)
        self.memory.add_task(
            description=f"Create {target}",
            status="done",
            files_affected=[target],
        )

        preview = content[:500]
        truncated = len(content) > len(preview)
        body = f"{preview}\n\n[Output truncated]" if truncated else preview

        return f"{action} `{target}`{retry_note}:\n\n{body}\n\n{verification}\n\n{test_output}".strip()

    def _handle_create_files(self, intent: Intent, context: Optional[AgentContext] = None, confirmed: bool = False) -> str:
        targets = []
        if intent.args and isinstance(intent.args, dict):
            targets = intent.args.get("targets", []) or []
        if not targets:
            targets = self._infer_targets(intent)
        targets = [str(t).strip() for t in targets if str(t).strip()]
        if not targets:
            return "Tell me which files to create, e.g. 'make sliding_window.py, two_pointers.py, and binary_search.py'"

        cached = self._pending_edits

        contents: dict[str, str] = {}
        for target in targets:
            if confirmed and target in cached:
                contents[target] = cached[target]
                continue
            generated = self._generate_file_content(target, intent.raw_message, context)
            if generated:
                contents[target] = generated

        if not contents:
            return "I could not generate content for the requested files. Please be more specific."

        if not confirmed:
            for target, content in contents.items():
                self._pending_edits[target] = content
            return self._multi_edit_confirmation_prompt(targets, contents)

        for target in list(cached.keys()):
            if target not in contents:
                contents[target] = cached[target]

        parts = []
        for target in targets:
            content = contents.get(target)
            if content is None:
                continue
            target_path = Path(target)
            try:
                file_exists = self.file_tools.exists(target_path)
            except PermissionError:
                file_exists = False

            try:
                content, verification, test_output, retries = self._write_and_verify(
                    (self.root / target).resolve(), content, context
                )
            except PermissionError as error:
                parts.append(str(error))
                continue

            action = "Overwritten" if file_exists else "Created"
            retry_note = self._retry_note(verification, test_output, retries)

            preview = content[:300]
            truncated = len(content) > len(preview)
            body = f"{preview}\n\n[Output truncated]" if truncated else preview

            self.memory.add_file_event(target, action.lower(), content)
            self.memory.add_task(
                description=f"Create {target}",
                status="done",
                files_affected=[target],
            )

            parts.append(f"{action} `{target}`{retry_note}:\n\n{body}\n\n{verification}\n\n{test_output}".strip())

        for target in targets:
            self._pending_edits.pop(target, None)

        return "Created multiple files:\n\n" + "\n\n---\n\n".join(parts)

    def _generate_project_targets(self, raw_message: str, context: Optional[AgentContext] = None) -> tuple[list[str], str]:
        system_prompt = PROJECT_MANIFEST_PROMPT.read_text(encoding="utf-8")
        ctx_block = ""
        if context:
            ctx_block = f"\n\nProject context:\n{self.context_builder.format_for_prompt(context)}\n"
        try:
            result = self.intent_parser.generate(system_prompt, raw_message + ctx_block)
        except Exception as error:
            logger.warning("Failed to generate project structure: %s", error)
            return [], f"Project structure generation failed: {error}"

        try:
            parsed = json.loads(result)
            files = parsed.get("files", []) if isinstance(parsed, dict) else parsed
        except (json.JSONDecodeError, AttributeError) as error:
            logger.warning("Project manifest was not valid JSON: %s", error)
            return [], "The project planner did not return a valid file list."

        if not isinstance(files, list) or not files:
            return [], "The project planner returned no files for the request."

        return [str(f).strip() for f in files if str(f).strip()], ""

    def _handle_create_project(self, intent: Intent, context: Optional[AgentContext] = None, confirmed: bool = False) -> str:
        emit({"type": "phase", "message": "Planning project structure…"})
        if confirmed:
            cached_targets = self._pending_project_targets.get(intent.raw_message)
            targets, error = cached_targets, ""
            if not targets:
                targets, error = self._generate_project_targets(intent.raw_message, context)
        else:
            targets, error = self._generate_project_targets(intent.raw_message, context)
            if targets:
                self._pending_project_targets[intent.raw_message] = targets
        if not targets:
            return error or "I could not figure out a file structure for that project. Please name the tech stack or files you want."

        cached = self._pending_edits

        contents: dict[str, str] = {}
        for target in targets:
            if confirmed and target in cached:
                contents[target] = cached[target]
                continue
            generated = self._generate_file_content(target, intent.raw_message, context, project_files=targets)
            if generated:
                contents[target] = generated

        if not contents:
            return "I could not generate content for the project files. Please be more specific."

        if not confirmed:
            for target, content in contents.items():
                self._pending_edits[target] = content
            return self._project_confirmation_prompt(targets, contents)

        for target in list(cached.keys()):
            if target not in contents:
                contents[target] = cached[target]

        parts = []
        for target in targets:
            content = contents.get(target)
            if content is None:
                continue
            target_path = Path(target)
            try:
                file_exists = self.file_tools.exists(target_path)
            except PermissionError:
                file_exists = False

            try:
                content, verification, test_output, retries = self._write_and_verify(
                    (self.root / target).resolve(), content, context
                )
            except PermissionError as error:
                parts.append(str(error))
                continue

            action = "Overwritten" if file_exists else "Created"
            retry_note = self._retry_note(verification, test_output, retries)

            preview = content[:300]
            truncated = len(content) > len(preview)
            body = f"{preview}\n\n[Output truncated]" if truncated else preview

            self.memory.add_file_event(target, action.lower(), content)
            self.memory.add_task(
                description=f"Create {target}",
                status="done",
                files_affected=[target],
            )

            parts.append(f"{action} `{target}`{retry_note}:\n\n{body}\n\n{verification}\n\n{test_output}".strip())

        for target in targets:
            self._pending_edits.pop(target, None)

        structure = "\n".join(f"- {t}" for t in targets)
        return f"Project created with {len(targets)} files:\n\n{structure}\n\n" + "\n\n---\n\n".join(parts)

    def _project_confirmation_prompt(self, targets: list[str], contents: dict[str, str]) -> str:
        blocks = []
        for target in targets:
            content = contents.get(target, "")
            lang = "python" if target.endswith(".py") else "text"
            blocks.append(f"```{lang}\n{content[:700]}\n```")
        lines = [
            CONFIRMATION_MARKER,
            f"Action: create_project",
            f"Target: {', '.join(targets)}",
            f"Reason: scaffold a project with {len(targets)} files",
            "",
            f"Project structure:",
            "",
            "\n".join(f"- {t}" for t in targets),
            "",
            "Make these changes?",
            "",
            "\n\n".join(blocks),
            "",
            "Reply with 'yes' to proceed, or 'no' to cancel.",
        ]
        return "\n".join(lines)

    def _infer_targets(self, intent: Intent) -> list[str]:
        text = intent.raw_message.lower()
        targets = []
        topics = [
            ("sliding window", "sliding_window.py"),
            ("two pointers", "two_pointers.py"),
            ("two pointer", "two_pointers.py"),
            ("binary search", "binary_search.py"),
            ("binary-search", "binary_search.py"),
        ]
        for phrase, filename in topics:
            if phrase in text:
                targets.append(filename)
        return targets

    def _multi_edit_confirmation_prompt(self, targets: list[str], contents: dict[str, str]) -> str:
        blocks = []
        for target in targets:
            content = contents.get(target, "")
            lang = "python" if target.endswith(".py") else "text"
            blocks.append(f"```{lang}\n{content[:1000]}\n```")
        lines = [
            CONFIRMATION_MARKER,
            f"Action: create_files",
            f"Target: {', '.join(targets)}",
            f"Reason: create {len(targets)} separate files",
            "",
            f"Make these changes?",
            "",
            "\n\n".join(blocks),
            "",
            "Reply with 'yes' to proceed, or 'no' to cancel.",
        ]
        return "\n".join(lines)

    def _generate_file_content(self, target: str, raw_message: str, context: Optional[AgentContext] = None, project_files: Optional[list[str]] = None) -> str:
        ctx_block = ""
        if context:
            ctx_block = f"\n\nProject context:\n{self.context_builder.format_for_prompt(context)}\n"
        project_block = ""
        if project_files:
            project_block = "\n\nThis file is part of a project being created with these files:\n" + "\n".join(
                f"- {f}" for f in project_files
            )
        system_prompt = (
            f"You are a code generation assistant. Generate content for the file `{target}` "
            "based on the user's request. "
            "Use object-oriented programming concepts (classes, encapsulation, inheritance, "
            "methods) wherever the language and the file's role make it appropriate. "
            f"{project_block}"
            "Return ONLY the raw file content. NO markdown fences, NO triple backticks, "
            "NO explanations, NO extra text of any kind. Just the code."
            f"{ctx_block}"
        )
        try:
            emit({"type": "phase", "message": f"Generating {target}…"})
            result = self.intent_parser.generate(system_prompt, raw_message)
            return self._strip_code_fences(result).strip()
        except Exception:
            return ""

    def _handle_modify_code(self, intent: Intent, context: Optional[AgentContext] = None, confirmed: bool = False) -> str:
        target = intent.target
        if not target:
            return "Usage: tell me which file to modify, e.g. 'add a function to utils.py'"

        resolved = self._resolve_path(target)
        if resolved is None:
            return f"File not found: {target}"

        is_python = resolved.suffix == ".py"

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

        cached = self._pending_edits.get(target)
        if confirmed and cached:
            new_content = cached
        else:
            emit({"type": "phase", "message": f"Generating changes for {target}…"})
            try:
                new_content = self._strip_code_fences(self.intent_parser.generate(system_prompt, user_prompt))
            except Exception as error:
                return f"Failed to generate edit: {error}"

        if not new_content or not new_content.strip():
            return "Generated content is empty. Please try again with a more specific request."

        if new_content.strip() == current_content.strip():
            return f"File `{target}` is already up to date. No changes were needed."

        diff_text = self._compute_diff(current_content, new_content, target)

        if is_python and not confirmed:
            self._pending_edits[target] = new_content
            return self._edit_confirmation_prompt(
                "modify_code",
                target,
                reason=f"apply these changes to `{target}`",
                preview=diff_text,
                language="diff",
            )

        self._pending_edits.pop(target, None)

        try:
            new_content, verification, test_output, retries = self._write_and_verify(
                resolved, new_content, context
            )
        except PermissionError as error:
            return str(error)

        retry_note = self._retry_note(verification, test_output, retries)

        try:
            display = str(resolved.relative_to(self.root))
        except ValueError:
            display = target

        self.memory.add_file_event(display, "modified", new_content)
        self.memory.add_task(
            description=f"Modify {display}",
            status="done",
            files_affected=[display],
        )

        if new_content.strip() != current_content.strip():
            diff_text = self._compute_diff(current_content, new_content, display)

        return (
            f"Modified `{display}`{retry_note}:\n\n"
            f"```diff\n{diff_text}\n```\n\n"
            f"{verification}\n\n"
            f"{test_output}"
        ).strip()

    def _handle_delete_file(self, intent: Intent) -> str:
        target = intent.target
        if not target:
            return "Usage: tell me which file to delete, e.g. 'delete test.txt'"

        resolved = self._resolve_path(target)
        if resolved is None:
            return f"File not found: {target}"

        try:
            resolved.unlink()
            try:
                display = str(resolved.relative_to(self.root))
            except ValueError:
                display = target
            self.memory.add_file_event(display, "deleted")
            self.memory.add_task(
                description=f"Delete {display}",
                status="done",
                files_affected=[display],
            )
            return f"Deleted `{display}`."
        except Exception as error:
            return f"Failed to delete `{target}`: {error}"

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
