import logging
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Optional

from .context_budget import SECTION_CAPS, ContextSection, assemble, truncate_to_tokens
from .file_context import collect_relevant_files, normalize_target
from .memory import MemoryStore
from .project_context import ProjectContext
from .project_scan import ProjectIdentity, detect_identity, get_tracked_files


logger = logging.getLogger(__name__)


# Intents whose prompts benefit from inlined file bodies (target file
# plus recently touched files). Other intents keep paths-only context.
CODE_INTENTS = frozenset({
    "create_file",
    "create_files",
    "modify_code",
    "explain",
    "unknown",
    "analyze_project",
    "read_file",
})


@dataclass(frozen=True)
class AgentContext:
    chat_history: list[dict[str, str]]
    similar_context: list[dict]
    last_intent: str
    last_target: str

    branch: str
    has_dirty_files: bool
    dirty_files: list[str]

    language: str
    has_test_config: bool
    has_lint_config: bool
    has_typecheck_config: bool

    session_summary: str = ""
    project_context: str = ""
    target_path: str = ""
    relevant_file_contents: list[dict] = field(default_factory=list)


class ContextBuilder:
    def __init__(self, memory: MemoryStore, root: Optional[Path] = None) -> None:
        self.memory = memory
        self.root = (root or Path.cwd()).resolve()
        self.project_context = ProjectContext(self.root, memory)
        # Instance-level caches: scan results are root-specific, so sharing
        # them across builders (module globals) leaks one project's identity
        # into another when multiple sessions are active.
        self._identity_cache: Optional[ProjectIdentity] = None
        self._tracked_files_cache: Optional[list[str]] = None

    def _reset_caches(self) -> None:
        """Reset this builder's caches (e.g. when its workspace changes)."""
        self._identity_cache = None
        self._tracked_files_cache = None

    def get_or_create_project_context(self) -> str:
        """Get existing project context or create initial context for new project."""
        # Clear any stale content first
        self.project_context.clear_stale_content()

        if not self.project_context.exists():
            initial_context = self.project_context.generate_initial_context(self)
            self.project_context.save(initial_context)
            return ""

        # Check if context is stale (path mismatch)
        existing = self.project_context.load()
        if existing:
            for line in existing.split("\n"):
                if line.startswith("**Path**:"):
                    context_path = line.replace("**Path**:", "").strip().strip("`")
                    if context_path != str(self.root):
                        logger.info("Context is stale (path mismatch: %s vs %s), regenerating", context_path, self.root)
                        self.project_context.context_file.unlink(missing_ok=True)
                        initial_context = self.project_context.generate_initial_context(self)
                        self.project_context.save(initial_context)
                        return ""
                    break

        return self.project_context.get_context_for_prompt()

    def build(
        self,
        user_message: str,
        load_context: bool = False,
        intent_name: str = "",
        intent_target: str = "",
    ) -> AgentContext:
        chat_history = self.memory.recent_turns(5)
        last_turn = chat_history[-1] if chat_history else {}
        last_intent = last_turn.get("intent", "")
        last_target = last_turn.get("target", "")
        session_summary = self.memory.get_preference("compaction_summary") or ""

        logger.info("Building context for: %s", user_message[:80])
        similar_context = self.memory.retrieve_similar(user_message, k=5)
        if not similar_context:
            recent_files = self.memory.get_by_type("file", limit=3)
            if recent_files:
                logger.info("Vector search empty; falling back to %d recent file events", len(recent_files))
                similar_context = recent_files

        branch, dirty_files = self._git_status()
        identity = self._detect_project_identity()

        # Only load/create project context when explicitly requested
        project_context = ""
        if load_context:
            project_context = self.get_or_create_project_context()

        # Inline bodies of the target + recently touched files for code intents.
        # Recent file events are queried independently: semantic results may
        # contain only chats, which must not suppress file injection.
        target_path = ""
        relevant_file_contents: list[dict] = []
        if intent_name in CODE_INTENTS:
            memory_paths = [
                item.get("metadata", {}).get("path", "")
                for item in similar_context
                if item.get("metadata", {}).get("doc_type") == "file"
            ]
            recent_paths = [
                item.get("metadata", {}).get("path", "")
                for item in self.memory.get_by_type("file", limit=3)
            ]
            candidates = ([intent_target] if intent_target else []) + memory_paths + recent_paths
            relevant_file_contents = collect_relevant_files(self.root, candidates)
            canonical_target = normalize_target(self.root, intent_target)
            if canonical_target and any(f["path"] == canonical_target for f in relevant_file_contents):
                target_path = canonical_target

        return AgentContext(
            chat_history=chat_history,
            similar_context=similar_context,
            last_intent=last_intent,
            last_target=last_target,
            session_summary=session_summary,
            branch=branch,
            has_dirty_files=len(dirty_files) > 0,
            dirty_files=dirty_files,
            language=identity.language,
            has_test_config=identity.has_test_config,
            has_lint_config=identity.has_lint_config,
            has_typecheck_config=identity.has_typecheck_config,
            project_context=project_context,
            target_path=target_path,
            relevant_file_contents=relevant_file_contents,
        )

    def format_for_prompt(self, ctx: AgentContext) -> str:
        """Assemble the prompt context within the token budget (priority-ordered)."""
        header_lines = [f"Project: {ctx.language} | branch: {ctx.branch}"]

        configs = []
        if ctx.has_test_config:
            configs.append("tests")
        if ctx.has_lint_config:
            configs.append("lint")
        if ctx.has_typecheck_config:
            configs.append("typecheck")
        if configs:
            header_lines.append(f"Config: {' '.join(configs)}")

        if ctx.has_dirty_files:
            files_str = ", ".join(ctx.dirty_files[:5])
            dirty = f"Dirty: {files_str}"
            if len(ctx.dirty_files) > 5:
                dirty += f" (+{len(ctx.dirty_files)-5} more)"
            header_lines.append(dirty)

        sections = [ContextSection("identity", "", "\n".join(header_lines))]

        # Target file body first (highest priority), then other relevant files.
        # Bodies are pre-budgeted per file so cuts land between files with
        # fences intact; the assembler re-closes fences as a backstop.
        target_items = [f for f in ctx.relevant_file_contents if f["path"] == ctx.target_path] if ctx.target_path else []
        other_items = [f for f in ctx.relevant_file_contents if f not in target_items]
        if target_items:
            sections.append(ContextSection(
                "target",
                "--- Target File ---",
                self._format_files(target_items, SECTION_CAPS["target"]),
                fence_aware=True,
            ))
        if other_items:
            sections.append(ContextSection(
                "files",
                "--- Relevant Files ---",
                self._format_files(other_items, SECTION_CAPS["files"]),
                fence_aware=True,
            ))

        if ctx.project_context:
            sections.append(ContextSection("project", "--- Project Context ---", ctx.project_context))

        if ctx.similar_context:
            ctx_lines = []
            for item in ctx.similar_context:
                meta = item["metadata"]
                if meta.get("doc_type") == "chat":
                    ctx_lines.append(f"[Related] {meta.get('content', '')}")
                elif meta.get("doc_type") == "file":
                    ctx_lines.append(
                        f"[File: {meta['path']}] ({meta.get('operation', '')}) "
                        f"{meta.get('content_preview', '')}"
                    )
            if ctx_lines:
                logger.info("Injecting %d related context items into prompt", len(ctx_lines))
                sections.append(ContextSection("related", "--- Related Context ---", "\n".join(ctx_lines)))
            else:
                logger.info("Similar context found but all filtered out (distance threshold)")

        if ctx.chat_history:
            history_lines = []
            for turn in reversed(ctx.chat_history[:5]):
                user_text = turn.get("user", "")
                agent_text = turn.get("agent", "")
                if user_text:
                    history_lines.append(f"User: {user_text}")
                if agent_text:
                    history_lines.append(f"Agent: {agent_text}")
            if history_lines:
                sections.append(ContextSection("history", "Chat history:", "\n".join(history_lines)))

        if ctx.session_summary:
            sections.append(ContextSection("summary", "--- Session Summary ---", ctx.session_summary))

        return assemble(sections)

    @staticmethod
    def _format_files(items: list[dict], cap_tokens: int) -> str:
        """Render collected file bodies as fenced blocks.

        Each file body is truncated to an equal share of cap_tokens
        BEFORE fencing, so budget cuts land between files and every
        block keeps balanced fences.
        """
        from .context_budget import truncate_to_tokens

        per_file = max(1, cap_tokens // max(1, len(items)))
        blocks = []
        for item in items:
            body = truncate_to_tokens(item["content"], per_file)
            blocks.append(f"### {item['path']}\n```\n{body}\n```")
        return "\n\n".join(blocks)

    def _git_status(self) -> tuple[str, list[str]]:
        try:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            branch = "unknown"

        try:
            status_out = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            return branch, []

        dirty = []
        if status_out:
            for line in status_out.split("\n"):
                line = line.strip()
                if not line:
                    continue
                filename = line[3:] if len(line) > 3 else line
                if filename:
                    dirty.append(filename)

        return branch, dirty

    def _detect_project_identity(self) -> ProjectIdentity:
        if self._identity_cache is not None:
            return self._identity_cache

        tracked = self._get_tracked_files()
        identity = detect_identity(self.root, tracked)
        self._identity_cache = identity
        return identity

    def _get_tracked_files(self) -> list[str]:
        if self._tracked_files_cache is not None:
            return self._tracked_files_cache

        tracked = get_tracked_files(self.root)
        self._tracked_files_cache = tracked
        return tracked
