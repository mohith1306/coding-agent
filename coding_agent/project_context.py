import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from .memory import MemoryStore
from .project_scan import detect_key_files, get_structure_overview, get_tracked_files, scan_project


logger = logging.getLogger(__name__)

CONTEXT_DIR = Path(__file__).resolve().parent.parent / "web" / "project_contexts"


class ProjectContext:
    """Manages persistent project context files (.md) for each session/project.

    Each project gets a unique hash based on its absolute path, and a context.md
    file is maintained that grows as the user interacts with the project.
    """

    def __init__(self, root: Path, memory: Optional[MemoryStore] = None) -> None:
        self.root = root.resolve()
        self.memory = memory
        self.session_hash = self._compute_hash()
        self.context_dir = CONTEXT_DIR / self.session_hash
        self.context_file = self.context_dir / "context.md"

    def _compute_hash(self) -> str:
        """Compute a stable hash from the absolute project path."""
        path_str = str(self.root).encode("utf-8")
        return hashlib.sha256(path_str).hexdigest()[:16]

    def exists(self) -> bool:
        """Check if a context file already exists for this project."""
        return self.context_file.is_file()

    def load(self) -> str:
        """Load the existing project context, or return empty string."""
        if not self.context_file.is_file():
            return ""
        try:
            return self.context_file.read_text(encoding="utf-8")
        except Exception as error:
            logger.warning("Failed to load project context: %s", error)
            return ""

    def save(self, content: str) -> None:
        """Save project context to the context file."""
        self.context_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.context_file.write_text(content, encoding="utf-8")
            logger.info("Saved project context to %s", self.context_file)
        except Exception as error:
            logger.warning("Failed to save project context: %s", error)

    def append(self, section: str) -> None:
        """Append a new section to the existing context file."""
        existing = self.load()
        if existing:
            updated = existing.rstrip() + "\n\n" + section.rstrip() + "\n"
        else:
            updated = section.rstrip() + "\n"
        self.save(updated)

    def get_context_for_prompt(self) -> str:
        """Get the project context formatted for the LLM prompt."""
        content = self.load()
        if not content:
            return ""

        # Check if context is stale (contains old LLM-generated DSA content)
        if self._is_stale_content(content):
            logger.info("Context contains stale LLM-generated content, clearing")
            self.save("")
            return ""

        return f"\n\n--- Project Context (from previous sessions) ---\n{content}"

    def _is_stale_content(self, content: str) -> bool:
        """Check if context contains stale LLM-generated content."""
        # Detect old LLM-generated content patterns
        stale_patterns = [
            "DSA Folder Structure",
            "sliding_window.py",
            "two_pointers.py",
            "binary_search.py",
            "**Location:** `DSA/`",
            "**Files Present:**",
            "What Each File Does",
            "Purpose & Usage",
            "Next Steps",
        ]
        return any(pattern in content for pattern in stale_patterns)

    def clear_stale_content(self) -> None:
        """Clear the context file if it contains stale content."""
        content = self.load()
        if content and self._is_stale_content(content):
            logger.info("Clearing stale context from %s", self.context_file)
            self.save("")

    def generate_initial_context(self, context_builder: "ContextBuilder") -> str:
        """Generate initial project context by analyzing the project.

        This is called on the first open of a project.
        """
        logger.info("Generating initial context for %s", self.root)

        # Build basic project info
        parts = []

        # Single shared scan (one git call) — no context_builder needed,
        # avoiding infinite recursion
        scan = scan_project(self.root)

        # Project overview
        parts.append("# Project Context")
        parts.append(f"\n**Path**: `{self.root}`")
        parts.append(f"\n**Discovered**: {self._get_timestamp()}")

        # Language and config
        if scan.identity.language and scan.identity.language != "unknown":
            parts.append(f"\n**Language**: {scan.identity.language}")

        configs = []
        if scan.identity.has_test_config:
            configs.append("tests")
        if scan.identity.has_lint_config:
            configs.append("lint")
        if scan.identity.has_typecheck_config:
            configs.append("typecheck")
        if configs:
            parts.append(f"\n**Config**: {', '.join(configs)}")

        # Key files (from git)
        parts.append("\n\n## Key Files")
        if scan.key_files:
            for path, kind in scan.key_files[:15]:
                parts.append(f"- `{path}` ({kind})")
        else:
            parts.append("- No key files detected")

        # Project structure overview
        parts.append("\n\n## Structure")
        parts.append(scan.structure)

        # Initial chat history placeholder
        parts.append("\n\n## Chat History & Learnings")
        parts.append("_Updated as you interact with the project._")

        return "\n".join(parts)

    def update_after_turn(self, user_message: str, agent_response: str, intent: str = "", target: str = "") -> None:
        """Update the context file after a meaningful turn.

        Appends new learnings from the conversation.
        """
        if not self.exists():
            return

        # Check if the response contains stale content before appending
        if self._is_stale_content(agent_response):
            logger.info("Skipping update - response contains stale content")
            return

        # Build the update section
        update_parts = []

        # Add meaningful interactions
        if intent in {"explain", "unknown"} and len(agent_response) > 100:
            # This was a question/explanation - extract learnings
            update_parts.append(f"\n### User Asked: {user_message[:200]}")
            update_parts.append(f"\n**Summary**: {agent_response[:500]}")
            update_parts.append("")

        elif intent in {"create_file", "create_files", "create_project"}:
            update_parts.append(f"\n### Created: {target}")
            update_parts.append(f"_User requested: {user_message[:200]}_")
            update_parts.append("")

        elif intent == "modify_code":
            update_parts.append(f"\n### Modified: {target}")
            update_parts.append(f"_User requested: {user_message[:200]}_")
            update_parts.append("")

        elif intent == "read_file":
            # Track which files were examined
            update_parts.append(f"\n### Examined: {target}")
            update_parts.append("")

        elif intent == "search_files":
            update_parts.append(f"\n### Searched: {target}")
            update_parts.append("")

        if update_parts:
            # Add timestamp
            update_parts.insert(0, f"\n---\n### Turn: {self._get_timestamp()}")
            self.append("\n".join(update_parts))

    def _get_timestamp(self) -> str:
        """Get a formatted timestamp."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _detect_key_files(self) -> list[tuple[str, str]]:
        """Detect key files in the project (delegates to shared scan)."""
        return detect_key_files(get_tracked_files(self.root))

    def _get_tracked_files(self) -> list[str]:
        """Get git tracked files (delegates to shared scan)."""
        return get_tracked_files(self.root)

    def _get_structure_overview(self) -> str:
        """Get a high-level structure overview (delegates to shared scan)."""
        return get_structure_overview(self.root)
