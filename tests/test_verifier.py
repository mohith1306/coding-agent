from pathlib import Path

from coding_agent.verifier import Verifier


def test_verify_python_clean(workspace: Path) -> None:
    path = workspace / "ok.py"
    path.write_text("print('hi')\n")
    verifier = Verifier(root=workspace)
    result = verifier.verify_file(path)
    assert "compiles clean" in result


def test_verify_python_syntax_error(workspace: Path) -> None:
    path = workspace / "bad.py"
    path.write_text("def broken(:\n")
    verifier = Verifier(root=workspace)
    result = verifier.verify_file(path)
    assert "issues" in result or "Warning" in result


def test_verify_python_missing(workspace: Path) -> None:
    verifier = Verifier(root=workspace)
    result = verifier.verify_file(workspace / "missing.py")
    assert "does not exist" in result


def test_verify_non_python(workspace: Path) -> None:
    path = workspace / "notes.txt"
    path.write_text("hello")
    verifier = Verifier(root=workspace)
    result = verifier.verify_file(path)
    assert "written successfully" in result
