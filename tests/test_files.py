from pathlib import Path

import pytest

from coding_agent.tools.files import FileTools


def test_search_glob(workspace: Path) -> None:
    (workspace / "a.py").write_text("")
    (workspace / "b.py").write_text("")
    (workspace / "c.md").write_text("")
    tools = FileTools(workspace)
    results = tools.search(workspace, "**/*.py")
    assert [p.name for p in results] == ["a.py", "b.py"]


def test_write_then_read(workspace: Path) -> None:
    tools = FileTools(workspace)
    target = workspace / "hello.py"
    tools.write_text(target, "print('hi')\n")
    assert tools.read_text(target) == "print('hi')\n"


def test_escape_workspace_blocked(workspace: Path) -> None:
    tools = FileTools(workspace)
    outside = Path("/etc/passwd")
    with pytest.raises(PermissionError):
        tools.read_text(outside)


def test_relative_path_resolved_inside_workspace(workspace: Path) -> None:
    tools = FileTools(workspace)
    target = workspace / "sub" / "f.txt"
    target.parent.mkdir()
    tools.write_text(target, "data")
    assert tools.exists("sub/f.txt")
    assert tools.read_text("sub/f.txt") == "data"
