"""Phase 3 tests: Postgres project facts store.

Database access is stubbed (no Postgres needed): an in-memory dict
emulates the project_contexts table through fake connections.
"""

from pathlib import Path
from unittest.mock import patch

from coding_agent.project_store import ProjectStore, project_hash


class FakeTable:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.statements: list[str] = []


class FakeCursor:
    def __init__(self, table: FakeTable):
        self._table = table
        self._result = None
        self.statements: list[str] = table.statements

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.statements.append(" ".join(sql.split()))
        if "SELECT learnings" in sql:
            row = self._table.rows.get(params[0])
            self._result = (row["learnings"],) if row else None
        elif "SELECT identity" in sql:
            row = self._table.rows.get(params[0])
            self._result = (
                (row["identity"], row["key_files"], row["structure"], row["learnings"])
                if row else None
            )
        elif "INSERT INTO project_contexts" in sql:
            ph, path, identity, key_files, structure = params
            import json
            self._table.rows.setdefault(ph, {
                "identity": json.loads(identity),
                "key_files": json.loads(key_files),
                "structure": structure,
                "learnings": [],
            })
            self._result = None
        elif "UPDATE project_contexts" in sql:
            import json
            learnings, ph = params
            self._table.rows[ph]["learnings"] = json.loads(learnings)
            self._result = None
        else:
            raise AssertionError(f"unexpected SQL: {sql[:60]}")

    def fetchone(self):
        return self._result


class FakeConn:
    def __init__(self, table: FakeTable):
        self._table = table

    def cursor(self):
        return FakeCursor(self._table)

    def commit(self):
        pass

    def rollback(self):
        pass


def _patched(table: FakeTable):
    return (
        patch("coding_agent.project_store.get_connection", return_value=FakeConn(table)),
        patch("coding_agent.project_store.return_connection", return_value=None),
    )


def _init_git(path: Path, files: dict) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    for rel, content in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_project_hash_stable(tmp_path: Path) -> None:
    assert project_hash(tmp_path) == project_hash(tmp_path)
    assert len(project_hash(tmp_path)) == 16


def test_get_or_create_scans_on_first_use(tmp_path: Path) -> None:
    _init_git(tmp_path, {"requirements.txt": "x\n", "app.py": "print(1)\n"})
    table = FakeTable()
    gc, rc = _patched(table)
    with gc, rc:
        facts = ProjectStore(tmp_path).get_or_create()
    assert facts["identity"]["language"] == "python"
    assert any(p == "app.py" for p, _ in facts["key_files"])
    assert "app.py" in facts["structure"]
    assert project_hash(tmp_path) in table.rows


def test_get_or_create_returns_existing(tmp_path: Path) -> None:
    _init_git(tmp_path, {"package.json": "{}\n"})
    table = FakeTable()
    ph = project_hash(tmp_path)
    table.rows[ph] = {"identity": {"language": "cached"}, "key_files": [],
                      "structure": "s", "learnings": []}
    gc, rc = _patched(table)
    with gc, rc:
        facts = ProjectStore(tmp_path).get_or_create()
    assert facts["identity"]["language"] == "cached"


def test_record_learning_appends_and_caps(tmp_path: Path) -> None:
    _init_git(tmp_path, {"app.py": "x\n"})
    table = FakeTable()
    gc, rc = _patched(table)
    store = ProjectStore(tmp_path)
    with gc, rc:
        store.get_or_create()
        store.record_learning("modify_code", "app.py", "fix bug", "changed code " + "y" * 100)
        # trivial response: dropped
        store.record_learning("explain", "", "hi", "short")
    learnings = table.rows[project_hash(tmp_path)]["learnings"]
    assert len(learnings) == 1
    assert learnings[0]["intent"] == "modify_code"
    assert "fix bug" in learnings[0]["summary"]


def test_record_learning_without_prior_row(tmp_path: Path) -> None:
    _init_git(tmp_path, {"app.py": "x\n"})
    table = FakeTable()
    gc, rc = _patched(table)
    with gc, rc:
        ProjectStore(tmp_path).record_learning(
            "explain", "", "what is this " + "q" * 50, "long answer " + "a" * 200)
    learnings = table.rows[project_hash(tmp_path)]["learnings"]
    assert len(learnings) == 1


def test_db_failure_degrades_gracefully(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    with patch("coding_agent.project_store.get_connection", side_effect=RuntimeError("no db")), \
         patch("coding_agent.project_store.return_connection", return_value=None):
        assert store.get_or_create() == {}
        store.record_learning("explain", "", "q" * 100, "a" * 200)  # must not raise


def test_format_for_prompt_sections() -> None:
    facts = {
        "identity": {"language": "python", "has_test_config": True,
                     "has_lint_config": False, "has_typecheck_config": True},
        "key_files": [["app.py", "entry point"]],
        "structure": "- `app.py`",
        "learnings": [{"ts": "t", "summary": "did a thing"}],
    }
    out = ProjectStore.format_for_prompt(facts)
    assert "**Language**: python" in out
    assert "**Config**: tests, typecheck" in out
    assert "`app.py` (entry point)" in out
    assert "## Learnings" in out
    assert ProjectStore.format_for_prompt({}) == ""


def test_build_loads_facts_for_write_intents(tmp_path: Path) -> None:
    """Phase 3: write intents get project facts (previously gated)."""
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    _init_git(tmp_path, {"requirements.txt": "x\n", "app.py": "print(1)\n"})
    table = FakeTable()
    gc, rc = _patched(table)
    builder = ContextBuilder(FakeMemory(), root=tmp_path)
    with gc, rc:
        ctx = builder.build("create file", intent_name="create_file", intent_target="new.py")
    assert "python" in ctx.project_context
    prompt = builder.format_for_prompt(ctx)
    assert "--- Project Context ---" in prompt


def test_record_learning_locks_row() -> None:
    """Bug 2: the read-modify-write holds a row lock through commit."""
    import tempfile

    table = FakeTable()
    ph = "abc123"
    table.rows[ph] = {"identity": {}, "key_files": [], "structure": "",
                      "learnings": []}
    gc, rc = _patched(table)
    with gc, rc:
        store = ProjectStore(Path(tempfile.gettempdir()))
        store.hash = ph  # point at the seeded row regardless of root
        store.record_learning("explain", "", "question " + "q" * 100,
                              "answer " + "a" * 200)
    selects = [s for s in table.statements if s.startswith("SELECT learnings")]
    assert selects, "expected a learnings SELECT"
    assert all("FOR UPDATE" in s for s in selects)
    assert len(table.rows[ph]["learnings"]) == 1


def test_create_returns_winning_row_on_conflict(tmp_path: Path) -> None:
    """Bug 3: loser of the insert race returns persisted facts + learnings."""
    _init_git(tmp_path, {"app.py": "x\n"})
    table = FakeTable()
    ph = project_hash(tmp_path)
    table.rows[ph] = {
        "identity": {"language": "python"}, "key_files": [["app.py", "entry point"]],
        "structure": "winner structure",
        "learnings": [{"ts": "t", "intent": "explain", "target": "", "summary": "winner learning"}],
    }
    gc, rc = _patched(table)
    with gc, rc:
        facts = ProjectStore(tmp_path)._create()
    assert facts["structure"] == "winner structure"
    assert facts["learnings"] == table.rows[ph]["learnings"]
    assert facts["learnings"] != []


def test_finish_node_records_learning_both_paths() -> None:
    """Bug 1: graph finish persists learnings on read-only AND write paths."""
    from types import SimpleNamespace

    from coding_agent.graph.nodes.finish import finish

    recorded = []

    class FakeStore:
        def record_learning(self, intent, target, user_message, agent_response):
            recorded.append({"intent": intent, "response": agent_response})

    deps = {"configurable": {
        "context_builder": SimpleNamespace(project_store=FakeStore()),
        "memory": None,
    }}

    # Read-only path: pre-existing final_response, no changed files
    state_ro = {
        "user_message": "what is this",
        "intent": {"name": "explain", "target": ""},
        "context": None,
        "final_response": "read-only answer with enough length " + "x" * 100,
        "changed_files": [],
        "tool_results": [],
        "verification_result": None,
        "repair_attempts": 0,
        "conversation": [],
    }
    out = finish(state_ro, deps)  # type: ignore[arg-type]
    assert out["execution_trace"]
    assert len(recorded) == 1
    assert "read-only answer" in recorded[0]["response"]

    # Write path: built response from tool results
    state_wr = dict(state_ro, final_response=None, changed_files=["a.py"],
                    tool_results=[{"name": "run_command", "result": "ok " + "y" * 100}])
    finish(state_wr, deps)  # type: ignore[arg-type]
    assert len(recorded) == 2
    assert recorded[1]["intent"] == "explain"


def test_finish_without_store_still_completes() -> None:
    """Bug 1: missing project_store (old fakes) must not break finish."""
    from coding_agent.graph.nodes.finish import finish

    deps = {"configurable": {"memory": None}}  # no context_builder at all
    state = {
        "user_message": "hi",
        "intent": {"name": "explain", "target": ""},
        "context": None,
        "final_response": "hello there",
        "changed_files": [],
        "tool_results": [],
        "verification_result": None,
        "repair_attempts": 0,
        "conversation": [],
    }
    out = finish(state, deps)  # type: ignore[arg-type]
    assert out["execution_trace"]


def test_build_offline_omits_project_section(tmp_path: Path) -> None:
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    (tmp_path / "a.py").write_text("x\n")
    builder = ContextBuilder(FakeMemory(), root=tmp_path)
    with patch("coding_agent.project_store.get_connection", side_effect=RuntimeError("no db")), \
         patch("coding_agent.project_store.return_connection", return_value=None):
        ctx = builder.build("hello")
    assert ctx.project_context == ""
