"""Backfill script tests: limit exactness, failure bounds, DB errors.

The script's DB/API dependencies are stubbed via sys.modules so no
Postgres or network is required.
"""

import importlib.util
import sys
import types
from pathlib import Path


def _load_backfill(db_rows, embed_results, update_raises=False):
    """Load backfill_embeddings with stubbed coding_agent modules.

    db_rows: list of (id, content) returned for SELECT (consumed per call).
    embed_results: list of vectors/None returned per embed_batch call.
    """
    state = {"rows": [list(db_rows)], "embeds": list(embed_results), "updates": []}

    fake_db = types.ModuleType("coding_agent.db")

    class FakeCur:
        def __init__(self):
            self._limit = 0
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def execute(self, sql, params=None):
            if "SELECT id" in sql:
                self._limit = params[0] if params else 0
            elif "UPDATE agent_memory" in sql:
                if update_raises:
                    raise RuntimeError("db down")
                state["updates"].append(params[1])
                # Simulate persistence: drop updated rows from the pool
                pool = state["rows"][0]
                state["rows"][0] = [r for r in pool if r[0] != params[1]]
            else:
                raise AssertionError(f"unexpected SQL: {sql[:60]}")
        def fetchall(self):
            # SELECT does not consume: rows persist until an UPDATE removes them
            return list(state["rows"][0][:self._limit])

    class FakeConn:
        def cursor(self):
            return FakeCur()
        def commit(self):
            pass
        def rollback(self):
            pass

    fake_db.get_connection = lambda: FakeConn()
    fake_db.return_connection = lambda c: None
    fake_db.init_db = lambda: None
    fake_db.ensure_vector_column = lambda dim: True

    fake_emb = types.ModuleType("coding_agent.embeddings")
    fake_emb.embed_dim = lambda: 2
    fake_emb.embeddings_enabled = lambda: True
    fake_emb.to_pgvector = lambda v: "[" + ",".join(map(str, v)) + "]"

    class FakeClient:
        def embed_batch(self, texts):
            return [state["embeds"].pop(0) if state["embeds"] else None for _ in texts]

    fake_emb.EmbeddingClient = FakeClient

    pkg = types.ModuleType("coding_agent")
    pkg.__path__ = []
    old = {k: sys.modules.get(k) for k in ("coding_agent", "coding_agent.db", "coding_agent.embeddings")}
    sys.modules["coding_agent"] = pkg
    sys.modules["coding_agent.db"] = fake_db
    sys.modules["coding_agent.embeddings"] = fake_emb
    # NOTE: stubs stay installed until _restore() — main() resolves its
    # from-imports at call time, so restore must happen after _run().
    path = Path(__file__).parent.parent / "scripts" / "backfill_embeddings.py"
    spec = importlib.util.spec_from_file_location("backfill_embeddings", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def _restore():
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    return mod, state, _restore


def _run_backfill(db_rows, embed_results, argv, update_raises=False):
    """Load the script with stubs, run main(argv), restore modules."""
    mod, state, restore = _load_backfill(db_rows, embed_results, update_raises)
    old_argv = sys.argv
    sys.argv = ["backfill_embeddings.py"] + argv
    try:
        return mod.main(), state
    finally:
        sys.argv = old_argv
        restore()


def test_limit_is_exact() -> None:
    rows = [(f"id{i}", f"text {i}") for i in range(10)]
    rc, state = _run_backfill(rows, [[0.1, 0.2]] * 10, ["--limit", "3", "--batch-size", "20"])
    assert rc == 0
    assert len(state["updates"]) == 3


def test_zero_progress_aborts_nonzero() -> None:
    rows = [(f"id{i}", f"text {i}") for i in range(5)]
    rc, state = _run_backfill(rows, [None] * 30, ["--batch-size", "2"])
    assert rc == 1
    assert state["updates"] == []


def test_db_failure_exits_nonzero() -> None:
    rows = [("id0", "text 0")]
    rc, _ = _run_backfill(rows, [[0.1, 0.2]], [], update_raises=True)
    assert rc == 1


def test_invalid_batch_size_rejected() -> None:
    rc, _ = _run_backfill([], [], ["--batch-size", "0"])
    assert rc == 1


def test_empty_table_succeeds() -> None:
    rc, _ = _run_backfill([], [], [])
    assert rc == 0
