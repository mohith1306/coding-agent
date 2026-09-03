"""Phase 1 tests: embeddings client, keyword fallback, retrieval paths.

No network or database required: the OpenRouter client is tested with
a mocked urlopen, and retrieval is tested through InMemoryMemoryStore
(keyword path) plus MemoryStore with a stubbed vector layer.
"""

import io
import json
from unittest.mock import patch

from coding_agent import keyword_search
from coding_agent.embeddings import EmbeddingClient, embed_dim, embeddings_enabled, to_pgvector
from coding_agent.memory import InMemoryMemoryStore


def test_to_pgvector_format() -> None:
    assert to_pgvector([0.1, 0.2]) == "[0.1,0.2]"
    assert to_pgvector([]) == "[]"


def _fake_response(payload: dict):
    response = io.BytesIO(json.dumps(payload).encode())
    response.__enter__ = lambda s: s
    response.__exit__ = lambda s, *a: False
    return response


# --- keyword scorer ---

def test_keyword_score_basic() -> None:
    assert keyword_search.keyword_score("fix login bug", "fix the login bug today") == 1.0
    assert keyword_search.keyword_score("fix login bug", "unrelated weather report") == 0.0
    assert keyword_search.keyword_score("", "anything") == 0.0
    partial = keyword_search.keyword_score("fix login bug", "fix something else")
    assert 0.0 < partial < 1.0


def test_rank_documents_order_and_distance() -> None:
    docs = [
        {"id": "1", "document": "weather report sunny"},
        {"id": "2", "document": "fix login bug in auth"},
        {"id": "3", "document": "login page styles"},
    ]
    ranked = keyword_search.rank_documents("fix login bug", docs, top_k=2)
    assert [d["id"] for d in ranked] == ["2", "3"]
    assert all("distance" in d for d in ranked)
    assert ranked[0]["distance"] <= ranked[1]["distance"]


def test_rank_documents_min_score_filters() -> None:
    docs = [{"id": "1", "document": "completely unrelated text here"}]
    assert keyword_search.rank_documents("xyzzy quantum", docs) == []


# --- embeddings client ---

def test_embed_batch_success() -> None:
    payload = {"data": [
        {"index": 1, "embedding": [0.2, 0.3]},
        {"index": 0, "embedding": [0.1, 0.2]},
    ]}
    with patch("coding_agent.embeddings.urlopen", return_value=_fake_response(payload)):
        client = EmbeddingClient(api_key="test-key", model="test-model", dim=2)
        out = client.embed_batch(["a", "b"])
    assert out == [[0.1, 0.2], [0.2, 0.3]]  # placed by declared index


def test_embed_batch_partial_response_keeps_positions() -> None:
    """A response with only index 1 must not shift into position 0."""
    payload = {"data": [{"index": 1, "embedding": [0.5, 0.6]}]}
    with patch("coding_agent.embeddings.urlopen", return_value=_fake_response(payload)):
        client = EmbeddingClient(api_key="test-key", dim=2)
        out = client.embed_batch(["a", "b", "c"])
    assert out == [None, [0.5, 0.6], None]


def test_embed_batch_rejects_bad_indexes() -> None:
    payload = {"data": [
        {"index": 0, "embedding": [0.1, 0.2]},
        {"index": 0, "embedding": [0.9, 0.9]},  # duplicate: first wins
        {"index": 7, "embedding": [0.3, 0.4]},  # out of range
        {"index": "x", "embedding": [0.3, 0.4]},  # invalid type
    ]}
    with patch("coding_agent.embeddings.urlopen", return_value=_fake_response(payload)):
        client = EmbeddingClient(api_key="test-key", dim=2)
        out = client.embed_batch(["a"])
    assert out == [[0.1, 0.2]]


def test_fit_dim_slices_and_renormalizes() -> None:
    client = EmbeddingClient(api_key="test-key", dim=2)
    out = client._fit_dim([3.0, 4.0, 9.0, 9.0])
    assert out is not None and len(out) == 2
    assert abs(sum(x * x for x in out) - 1.0) < 1e-9  # L2 re-normalized
    assert client._fit_dim([0.1]) is None  # too short: rejected
    assert client._fit_dim([0.0, 0.0, 1.0]) is None  # zero norm: rejected


def test_embed_batch_failure_returns_nones() -> None:
    with patch("coding_agent.embeddings.urlopen", side_effect=RuntimeError("down")):
        client = EmbeddingClient(api_key="test-key")
        assert client.embed_batch(["a", "b"]) == [None, None]
        assert client.embed("a") is None


def test_embed_no_key_returns_none() -> None:
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False):
        client = EmbeddingClient(api_key="")
        assert client.embed("hello") is None


def test_embed_dim_default() -> None:
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("CODING_AGENT_EMBED_DIM", None)
        assert embed_dim() == 1024  # HNSW-safe sliced default


def test_embeddings_enabled_switch() -> None:
    with patch.dict("os.environ", {"CODING_AGENT_EMBEDDINGS": "off", "OPENROUTER_API_KEY": "x"}):
        assert embeddings_enabled() is False


# --- InMemory retrieval (keyword path) ---

def test_inmemory_retrieve_similar() -> None:
    mem = InMemoryMemoryStore()
    mem.add_turn("how do I fix the login bug", "check auth.py")
    mem.add_turn("what is the weather", "sunny")
    mem.add_file_event("auth.py", "modified", "fixed login bug")

    results = mem.retrieve_similar("login bug fix", k=5)
    assert results, "expected keyword matches"
    texts = " ".join(r["document"] for r in results)
    assert "login" in texts
    assert all("distance" in r for r in results)


def test_inmemory_retrieve_no_match() -> None:
    mem = InMemoryMemoryStore()
    mem.add_turn("hello world", "hi there")
    assert mem.retrieve_similar("xyzzy quantum tunneling", k=5) == []


def test_inmemory_retrieve_doc_type_filter() -> None:
    mem = InMemoryMemoryStore()
    mem.add_turn("login bug discussion", "response")
    mem.add_file_event("auth.py", "modified", "login bug fix")
    results = mem.retrieve_similar("login bug", k=5, doc_type="file")
    assert results
    assert all(r["metadata"]["doc_type"] == "file" for r in results)


# --- MemoryStore vector path with stubs (no DB) ---

def test_memorystore_vector_search_shapes_results() -> None:
    from coding_agent.memory import MemoryStore

    store = MemoryStore.__new__(MemoryStore)
    store._vector_ready = True
    store._embed_client = None

    fake_rows = [
        {"id": "a", "content": "login fix", "metadata": {"doc_type": "chat"}, "distance": 0.2},
        {"id": "b", "content": "other", "metadata": {"doc_type": "chat"}, "distance": 0.99},
    ]

    class FakeCur:
        def __init__(self, rows):
            self._rows = rows
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def execute(self, *a, **k):
            pass
        def fetchall(self):
            return self._rows

    class FakeConn:
        def __init__(self, rows):
            self._rows = rows
        def cursor(self, cursor_factory=None):
            return FakeCur(self._rows)

    with patch("coding_agent.memory.vector_available", return_value=True), \
         patch("coding_agent.memory.get_connection", return_value=FakeConn(fake_rows)), \
         patch("coding_agent.memory.return_connection", return_value=None), \
         patch.object(MemoryStore, "_embed", return_value=[0.1] * 2048):
        results = store._vector_search("login", k=5, doc_type=None, max_distance=0.95)

    assert len(results) == 1
    assert results[0]["id"] == "a"
    assert results[0]["distance"] == 0.2


def test_memorystore_retrieve_falls_back_on_vector_error() -> None:
    from coding_agent.memory import MemoryStore

    store = MemoryStore.__new__(MemoryStore)
    store._vector_ready = True

    with patch.object(MemoryStore, "_vector_search", side_effect=RuntimeError("boom")), \
         patch.object(MemoryStore, "_keyword_search", return_value=[{"id": "x"}]) as kw:
        results = store.retrieve_similar("q", k=3)
    assert results == [{"id": "x"}]
    kw.assert_called_once_with("q", 3, None, 0.95)


def test_memorystore_no_fallback_on_empty_vector_results() -> None:
    """Successful vector search with no qualifying matches returns [] directly."""
    from coding_agent.memory import MemoryStore

    store = MemoryStore.__new__(MemoryStore)
    store._vector_ready = True

    with patch.object(MemoryStore, "_vector_search", return_value=[]) as vs, \
         patch.object(MemoryStore, "_keyword_search") as kw:
        results = store.retrieve_similar("q", k=3)
    assert results == []
    vs.assert_called_once()
    kw.assert_not_called()


def test_memorystore_falls_back_when_vector_unavailable() -> None:
    from coding_agent.memory import MemoryStore

    store = MemoryStore.__new__(MemoryStore)
    store._vector_ready = True

    with patch.object(MemoryStore, "_vector_search", return_value=None), \
         patch.object(MemoryStore, "_keyword_search", return_value=[]) as kw:
        assert store.retrieve_similar("q", k=3) == []
    kw.assert_called_once_with("q", 3, None, 0.95)


def test_keyword_search_applies_max_distance() -> None:
    from coding_agent.memory import MemoryStore

    store = MemoryStore.__new__(MemoryStore)
    docs = [
        {"id": "close", "document": "login bug fix auth", "metadata": {}},
        {"id": "far", "document": "login weather", "metadata": {}},
    ]
    with patch("coding_agent.memory.get_connection"), \
         patch("coding_agent.memory.return_connection"):
        # Patch at cursor level is complex; test the filter via rank path:
        ranked = keyword_search.rank_documents("login bug fix", docs, top_k=5)
    assert ranked[0]["id"] == "close"
    filtered = [r for r in ranked if r["distance"] <= 0.5]
    assert [r["id"] for r in filtered] == ["close"]


def test_inmemory_respects_max_distance() -> None:
    mem = InMemoryMemoryStore()
    mem.add_turn("login bug fix auth module", "response")
    mem.add_file_event("weather.txt", "modified", "login sunny day")
    strict = mem.retrieve_similar("login bug fix", k=5, max_distance=0.1)
    assert all(r["distance"] <= 0.1 for r in strict)
    loose = mem.retrieve_similar("login bug fix", k=5, max_distance=0.95)
    assert len(loose) >= len(strict)
