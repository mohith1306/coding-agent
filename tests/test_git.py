import subprocess
from pathlib import Path

from coding_agent.tools.git import GitContext


def _write_and_commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)


def test_status_clean(git_workspace: Path) -> None:
    _write_and_commit(git_workspace, "a.txt", "x", "init")
    status = GitContext(git_workspace).status()
    assert status.is_clean
    assert status.branch == "main"


def test_status_dirty_files_full_paths(git_workspace: Path) -> None:
    _write_and_commit(git_workspace, "a.py", "x", "init")
    (git_workspace / "b.py").write_text("y")
    status = GitContext(git_workspace).status()
    assert "b.py" in status.dirty_files


def test_stage_commit_flow(git_workspace: Path) -> None:
    _write_and_commit(git_workspace, "a.py", "print(1)\n", "init")
    (git_workspace / "a.py").write_text("print(1)\nprint(2)\n")
    (git_workspace / "b.py").write_text("print(3)\n")

    git = GitContext(git_workspace)
    assert git.stage_all() == ""
    code, output = git.commit("Update a.py, b.py")
    assert code == 0
    assert "Update a.py, b.py" in output
    assert git.current_hash() != "none"
    assert git.status().is_clean


def test_commit_empty_tree(git_workspace: Path) -> None:
    _write_and_commit(git_workspace, "a.txt", "x", "init")
    git = GitContext(git_workspace)
    assert git.stage_all() == ""
    code, output = git.commit("nothing to commit")
    assert code != 0
