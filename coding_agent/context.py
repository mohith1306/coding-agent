import logging
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Optional

from .memory import MemoryStore
from .project_context import ProjectContext
from .project_scan import ProjectIdentity, detect_identity, get_tracked_files


logger = logging.getLogger(__name__)


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

    def build(self, user_message: str, load_context: bool = False) -> AgentContext:
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
        )

    def format_for_prompt(self, ctx: AgentContext) -> str:
        parts = [f"Project: {ctx.language} | branch: {ctx.branch}"]

        configs = []
        if ctx.has_test_config:
            configs.append("tests")
        if ctx.has_lint_config:
            configs.append("lint")
        if ctx.has_typecheck_config:
            configs.append("typecheck")
        if configs:
            parts.append(f"Config: {' '.join(configs)}")

        if ctx.has_dirty_files:
            files_str = ", ".join(ctx.dirty_files[:5])
            parts.append(f"Dirty: {files_str}")
            if len(ctx.dirty_files) > 5:
                parts[-1] += f" (+{len(ctx.dirty_files)-5} more)"

        if ctx.project_context:
            parts.append(f"\n--- Project Context ---\n{ctx.project_context[:4000]}")

        if ctx.session_summary:
            parts.append(f"\n--- Session Summary ---\n{ctx.session_summary[:4000]}")

        if ctx.chat_history:
            history_lines = []
            for turn in reversed(ctx.chat_history[:5]):
                user_text = turn.get("user", "")
                agent_text = turn.get("agent", "")
                if user_text:
                    history_lines.append(f"User: {user_text[:500]}")
                if agent_text:
                    history_lines.append(f"Agent: {agent_text[:1200]}")
            if history_lines:
                parts.append("\nChat history:\n" + "\n".join(history_lines))

        if ctx.similar_context:
            ctx_lines = []
            for item in ctx.similar_context:
                meta = item["metadata"]
                dist = item.get("distance", 0)
                if meta.get("doc_type") == "chat":
                    ctx_lines.append(f"[Related] {meta.get('content', '')[:300]}")
                elif meta.get("doc_type") == "file":
                    ctx_lines.append(f"[File: {meta['path']}] ({meta.get('operation', '')}) {meta.get('content_preview', '')[:200]}")
            if ctx_lines:
                logger.info("Injecting %d related context items into prompt", len(ctx_lines))
                parts.append("--- Related Context ---\n" + "\n".join(ctx_lines))
            else:
                logger.info("Similar context found but all filtered out (distance threshold)")

        return "\n".join(parts)

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
