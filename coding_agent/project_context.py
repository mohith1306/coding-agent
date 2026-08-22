import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from .memory import MemoryStore


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
        return f"\n\n--- Project Context (from previous sessions) ---\n{content}"

    def generate_initial_context(self, context_builder: "ContextBuilder") -> str:
        """Generate initial project context by analyzing the project.

        This is called on the first open of a project.
        """
        logger.info("Generating initial context for %s", self.root)

        # Build basic project info
        parts = []

        # Project overview
        parts.append("# Project Context")
        parts.append(f"\n**Path**: `{self.root}`")
        parts.append(f"\n**Discovered**: {self._get_timestamp()}")

        # Language and config - detect directly without calling context_builder.build()
        # to avoid infinite recursion
        language = self._detect_language_direct()
        if language and language != "unknown":
            parts.append(f"\n**Language**: {language}")

        configs = self._detect_configs_direct()
        if configs:
            parts.append(f"\n**Config**: {', '.join(configs)}")

        # Key files (from git)
        parts.append("\n\n## Key Files")
        key_files = self._detect_key_files()
        if key_files:
            for path, kind in key_files[:15]:
                parts.append(f"- `{path}` ({kind})")
        else:
            parts.append("- No key files detected")

        # Project structure overview
        parts.append("\n\n## Structure")
        structure = self._get_structure_overview()
        parts.append(structure)

        # Initial chat history placeholder
        parts.append("\n\n## Chat History & Learnings")
        parts.append("_Updated as you interact with the project._")

        return "\n".join(parts)

    def _detect_language_direct(self) -> str:
        """Detect project language directly from files."""
        tracked = self._get_tracked_files()
        root_files = set()
        for f in tracked:
            if "/" not in f:
                root_files.add(f)

        if "package.json" in root_files:
            return "javascript"
        if "requirements.txt" in root_files or "setup.py" in root_files or "pyproject.toml" in root_files:
            return "python"
        if "Cargo.toml" in root_files:
            return "rust"
        if "go.mod" in root_files:
            return "go"
        if "Gemfile" in root_files:
            return "ruby"
        if "CMakeLists.txt" in root_files:
            return "cpp"
        return "unknown"

    def _detect_configs_direct(self) -> list[str]:
        """Detect config files directly."""
        tracked = self._get_tracked_files()
        root_files = set()
        for f in tracked:
            if "/" not in f:
                root_files.add(f)

        configs = []
        if "pytest.ini" in root_files or "setup.cfg" in root_files:
            configs.append("tests")
        if any("jest.config" in f for f in root_files):
            configs.append("tests")
        if any("spec." in f or "_test." in f or ".test." in f for f in tracked[:200]):
            configs.append("tests")

        lint_configs = {".eslintrc", ".eslintrc.json", ".ruff", ".ruff.toml", ".flake8"}
        if root_files & lint_configs:
            configs.append("lint")

        typecheck_configs = {"tsconfig.json", "mypy.ini", "pyrightconfig.json"}
        if root_files & typecheck_configs:
            configs.append("typecheck")

        return configs

    def update_after_turn(self, user_message: str, agent_response: str, intent: str = "", target: str = "") -> None:
        """Update the context file after a meaningful turn.

        Appends new learnings from the conversation.
        """
        if not self.exists():
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
        """Detect key files in the project."""
        key_files = []
        tracked = self._get_tracked_files()

        for f in tracked[:200]:
            suffix = Path(f).suffix
            name = Path(f).name.lower()

            # Entry points
            if suffix == ".py" and any(kw in name for kw in {"__init__", "app", "main", "server"}):
                key_files.append((f, "entry point"))
            # Test files
            elif any(keyword in name for keyword in {"test", "spec"}):
                key_files.append((f, "test"))
            # Config files
            elif suffix in {".json", ".yml", ".yaml", ".toml", ".cfg", ".ini"}:
                key_files.append((f, "config"))
            # Markdown docs
            elif suffix == ".md":
                key_files.append((f, "docs"))
            # React/Vue components
            elif suffix in {".tsx", ".jsx", ".vue"}:
                key_files.append((f, "component"))
            # TypeScript
            elif suffix == ".ts":
                key_files.append((f, "module"))

        return key_files[:15]

    def _get_tracked_files(self) -> list[str]:
        """Get git tracked files."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return [f for f in result.stdout.strip().split("\n") if f]
        except Exception:
            pass
        return []

    def _get_structure_overview(self) -> str:
        """Get a high-level structure overview."""
        try:
            entries = sorted(self.root.iterdir(), key=lambda p: p.name.lower())
            lines = []
            count = 0
            for entry in entries:
                if entry.name.startswith(".") or entry.name in {"node_modules", "__pycache__", ".venv", "venv"}:
                    continue
                if entry.is_dir():
                    lines.append(f"- `{entry.name}/`")
                else:
                    lines.append(f"- `{entry.name}`")
                count += 1
                if count >= 20:
                    lines.append(f"- ...and more")
                    break
            return "\n".join(lines) if lines else "_Empty project_"
        except Exception as error:
            return f"_Could not read structure: {error}_"
