"""Project scanning — single implementation of project detection.

Consolidates the language/config/key-file/structure detection logic
previously duplicated across ``context.py`` (``ContextBuilder``) and
``project_context.py`` (``ProjectContext``). Behavior is unchanged;
both callers delegate here.

In Phase 3 the scan results feed the Postgres ``project_contexts``
table instead of the markdown file.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectIdentity:
    language: str
    has_test_config: bool
    has_lint_config: bool
    has_typecheck_config: bool


@dataclass(frozen=True)
class ProjectScan:
    """Full scan result for a project root."""

    identity: ProjectIdentity
    key_files: list[tuple[str, str]] = field(default_factory=list)
    structure: str = ""
    tracked_files: list[str] = field(default_factory=list)


def get_tracked_files(root: Path, timeout: int = 10) -> list[str]:
    """Return git tracked files for root (empty list on failure)."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f]


def detect_language(root_files: set[str]) -> str:
    """Detect primary project language from root-level filenames."""
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


def detect_test_config(root_files: set[str], tracked: list[str]) -> bool:
    """Detect whether the project has test configuration or test files."""
    if "pytest.ini" in root_files or "setup.cfg" in root_files:
        return True
    if any("jest.config" in f for f in root_files):
        return True
    if any("spec." in f or "_test." in f or ".test." in f or "_test.go" in f for f in tracked[:200]):
        return True
    return False


def detect_lint_config(root_files: set[str]) -> bool:
    """Detect whether the project has lint configuration."""
    lint_configs = {".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.yaml",
                    ".ruff", ".ruff.toml", ".flake8", ".pylintrc",
                    ".prettierrc", ".prettierrc.json", ".prettierrc.js"}
    return bool(root_files & lint_configs)


def detect_typecheck_config(root_files: set[str]) -> bool:
    """Detect whether the project has typecheck configuration."""
    typecheck_configs = {"tsconfig.json", "mypy.ini", "pyrightconfig.json",
                         ".mypy.ini", "tsconfig.app.json"}
    return bool(root_files & typecheck_configs)


def detect_identity(root: Path, tracked: list[str] | None = None) -> ProjectIdentity:
    """Detect project identity (language + tooling configs)."""
    if tracked is None:
        tracked = get_tracked_files(root)
    root_files = {f for f in tracked if "/" not in f}
    return ProjectIdentity(
        language=detect_language(root_files),
        has_test_config=detect_test_config(root_files, tracked),
        has_lint_config=detect_lint_config(root_files),
        has_typecheck_config=detect_typecheck_config(root_files),
    )


def detect_key_files(tracked: list[str], limit: int = 15) -> list[tuple[str, str]]:
    """Detect key files (entry points, tests, configs, docs, components)."""
    key_files = []
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

    return key_files[:limit]


def get_structure_overview(root: Path, limit: int = 20) -> str:
    """Get a high-level directory structure overview."""
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
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
            if count >= limit:
                lines.append("- ...and more")
                break
        return "\n".join(lines) if lines else "_Empty project_"
    except Exception as error:
        return f"_Could not read structure: {error}_"


def scan_project(root: Path) -> ProjectScan:
    """Run a full project scan (single git call, shared by all callers)."""
    root = root.resolve()
    tracked = get_tracked_files(root)
    return ProjectScan(
        identity=detect_identity(root, tracked),
        key_files=detect_key_files(tracked),
        structure=get_structure_overview(root),
        tracked_files=tracked,
    )
