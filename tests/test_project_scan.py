"""Phase 0 tests: shared tokens + project scan modules.

Verifies:
- estimate_tokens matches the legacy compaction formula (parity).
- project_scan detection matches legacy ContextBuilder behavior.
- ProjectContext.generate_initial_context still renders all sections.
"""

import subprocess
from pathlib import Path

from coding_agent.compaction import estimate_tokens as legacy_estimate
from coding_agent.project_scan import (
    detect_identity,
    detect_key_files,
    detect_language,
    detect_lint_config,
    detect_test_config,
    detect_typecheck_config,
    get_structure_overview,
    get_tracked_files,
    scan_project,
)
from coding_agent.tokens import estimate_tokens


def _init_repo(path: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    for rel, content in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


def test_estimate_tokens_parity() -> None:
    """Shared estimator matches the legacy compaction formula."""
    for text in ["", "hello world", "x" * 100, "abc", "x" * 1000]:
        assert estimate_tokens(text) == legacy_estimate(text)
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2


def test_detect_language() -> None:
    assert detect_language({"package.json"}) == "javascript"
    assert detect_language({"requirements.txt"}) == "python"
    assert detect_language({"pyproject.toml"}) == "python"
    assert detect_language({"Cargo.toml"}) == "rust"
    assert detect_language({"go.mod"}) == "go"
    assert detect_language({"Gemfile"}) == "ruby"
    assert detect_language({"CMakeLists.txt"}) == "cpp"
    assert detect_language(set()) == "unknown"


def test_detect_configs() -> None:
    assert detect_test_config({"pytest.ini"}, []) is True
    assert detect_test_config({"jest.config.js"}, []) is True
    assert detect_test_config(set(), ["src/app_test.py"]) is True
    assert detect_test_config(set(), []) is False

    assert detect_lint_config({".ruff.toml"}) is True
    assert detect_lint_config({".pylintrc"}) is True
    assert detect_lint_config(set()) is False

    assert detect_typecheck_config({"tsconfig.json"}) is True
    assert detect_typecheck_config({"mypy.ini"}) is True
    assert detect_typecheck_config(set()) is False


def test_scan_python_project(tmp_path: Path) -> None:
    _init_repo(tmp_path, {
        "requirements.txt": "pytest\n",
        "pytest.ini": "[pytest]\n",
        "app.py": "print('hi')\n",
        "src/main.py": "x = 1\n",
        "README.md": "# Test\n",
    })
    scan = scan_project(tmp_path)
    assert scan.identity.language == "python"
    assert scan.identity.has_test_config is True
    assert "app.py" in scan.tracked_files
    kinds = {path: kind for path, kind in scan.key_files}
    assert kinds.get("app.py") == "entry point"
    assert "README.md" in scan.structure


def test_scan_matches_context_builder(tmp_path: Path) -> None:
    """Scan identity matches what ContextBuilder produces (parity)."""
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    _init_repo(tmp_path, {
        "package.json": "{}\n",
        "src/index.ts": "export {};\n",
    })
    scan = scan_project(tmp_path)

    builder = ContextBuilder(FakeMemory(), root=tmp_path)
    identity = builder._detect_project_identity()
    assert scan.identity == identity


def test_project_context_initial_sections(tmp_path: Path) -> None:
    """generate_initial_context still renders all sections via shared scan."""
    from coding_agent.project_context import ProjectContext

    _init_repo(tmp_path, {
        "requirements.txt": "x\n",
        "app.py": "print(1)\n",
    })
    pc = ProjectContext(tmp_path)
    content = pc.generate_initial_context(None)  # type: ignore[arg-type]
    assert "# Project Context" in content
    assert "**Language**: python" in content
    assert "## Key Files" in content
    assert "## Structure" in content
    assert "## Chat History & Learnings" in content


def test_get_tracked_files_empty_outside_repo(tmp_path: Path) -> None:
    assert get_tracked_files(tmp_path) == []


def test_detect_key_files_kinds() -> None:
    tracked = ["app.py", "test_utils.py", "config.yaml", "README.md", "Comp.tsx", "mod.ts", "notes.txt"]
    kinds = dict(detect_key_files(tracked))
    assert kinds["app.py"] == "entry point"
    assert kinds["test_utils.py"] == "test"
    assert kinds["config.yaml"] == "config"
    assert kinds["README.md"] == "docs"
    assert kinds["Comp.tsx"] == "component"
    assert kinds["mod.ts"] == "module"
    assert "notes.txt" not in kinds


def test_detect_identity_explicit_tracked() -> None:
    identity = detect_identity(Path("/nonexistent"), tracked=["Cargo.toml", "src/main.rs"])
    assert identity.language == "rust"
    assert identity.has_test_config is False


def test_builders_do_not_share_cache_across_projects(tmp_path: Path) -> None:
    """Regression: one builder's scan must not leak into another project."""
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()
    _init_repo(proj_a, {"requirements.txt": "x\n"})
    _init_repo(proj_b, {"package.json": "{}\n"})

    builder_a = ContextBuilder(FakeMemory(), root=proj_a)
    builder_b = ContextBuilder(FakeMemory(), root=proj_b)

    assert builder_a._detect_project_identity().language == "python"
    # Builder B must see its own project even though A populated a cache first
    assert builder_b._detect_project_identity().language == "javascript"
    # And A still sees its own after B scanned
    assert builder_a._detect_project_identity().language == "python"
