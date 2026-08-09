import json
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web" / "backend"))
import app as appmod  # noqa: E402


def parse_sse(text: str) -> list[dict]:
    events = []
    for frame in text.split("\n\n"):
        for line in frame.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[len("data: "):]))
                except json.JSONDecodeError:
                    pass
    return events


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(appmod, "WORKSPACES", tmp_path / "workspaces")
    return TestClient(appmod.app)


@pytest.fixture
def sid(client, tmp_path):
    session_id = "test-session"
    workspace = tmp_path / "workspaces" / session_id
    workspace.mkdir(parents=True, exist_ok=True)
    return session_id


def test_save_and_read_file(client, sid):
    res = client.put(f"/api/sessions/{sid}/files/hello.py", json={"content": "print('hi')\n"})
    assert res.status_code == 200
    assert res.json()["size"] == len("print('hi')\n")

    res = client.get(f"/api/sessions/{sid}/files/hello.py")
    assert res.status_code == 200
    assert res.json()["content"] == "print('hi')\n"


def test_save_creates_nested_dirs(client, sid):
    res = client.put(
        f"/api/sessions/{sid}/files/src/util.py",
        json={"content": "def f():\n    return 1\n"},
    )
    assert res.status_code == 200
    assert res.json()["size"] > 0


def test_put_rejects_path_traversal(client, sid):
    res = client.put(f"/api/sessions/{sid}/files/..%2F..%2F.env", json={"content": "x"})
    assert res.status_code == 403


def test_delete_rejects_traversal(client, sid):
    res = client.delete(f"/api/sessions/{sid}/files/..%2F..%2F.env")
    assert res.status_code == 403


def test_delete_file(client, sid):
    client.put(f"/api/sessions/{sid}/files/tmp.txt", json={"content": "bye"})
    res = client.delete(f"/api/sessions/{sid}/files/tmp.txt")
    assert res.status_code == 200
    assert res.json()["deleted"] == "tmp.txt"


def test_delete_non_empty_dir_rejected(client, sid):
    client.put(f"/api/sessions/{sid}/files/sub/util.py", json={"content": "x"})
    res = client.delete(f"/api/sessions/{sid}/files/sub")
    assert res.status_code == 400


def test_delete_empty_dir_ok(client, sid):
    res = client.delete(f"/api/sessions/{sid}/files/nope")
    assert res.status_code == 404
    workspace = appmod.WORKSPACES / sid
    (workspace / "empty").mkdir()
    res = client.delete(f"/api/sessions/{sid}/files/empty")
    assert res.status_code == 200


def test_run_rejects_non_python(client, sid):
    client.put(f"/api/sessions/{sid}/files/notes.md", json={"content": "# hi"})
    res = client.post(f"/api/sessions/{sid}/run", json={"file_path": "notes.md"})
    assert res.status_code == 400


def test_run_missing_file_404(client, sid):
    res = client.post(f"/api/sessions/{sid}/run", json={"file_path": "nope.py"})
    assert res.status_code == 404


def test_run_python_streams_output_and_exit(client, sid):
    client.put(
        f"/api/sessions/{sid}/files/app.py",
        json={"content": "print('line 1')\nprint('line 2')\n"},
    )
    res = client.post(f"/api/sessions/{sid}/run", json={"file_path": "app.py"})
    assert res.status_code == 200
    events = parse_sse(res.content.decode("utf-8"))
    types = [e["type"] for e in events]
    assert "output" in types
    assert "exit" in types
    outputs = "".join(e.get("text", "") for e in events if e["type"] == "output")
    assert "line 1" in outputs
    assert "line 2" in outputs
    exit_event = next(e for e in events if e["type"] == "exit")
    assert exit_event["code"] == 0


def test_stop_terminates_running_process(client, sid):
    client.put(
        f"/api/sessions/{sid}/files/sleepy.py",
        json={"content": "import time\ntime.sleep(60)\n"},
    )
    results = {}

    def do_run():
        results["res"] = client.post(f"/api/sessions/{sid}/run", json={"file_path": "sleepy.py"})

    thread = threading.Thread(target=do_run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while sid not in appmod._running_procs and time.time() < deadline:
        time.sleep(0.05)
    assert sid in appmod._running_procs

    stop = client.post(f"/api/sessions/{sid}/stop")
    assert stop.status_code == 200
    assert stop.json()["stopped"] is True

    thread.join(timeout=5)
    assert not thread.is_alive()
    assert results["res"].status_code == 200
    events = parse_sse(results["res"].content.decode("utf-8"))
    assert events[-1]["type"] == "exit"
    assert sid not in appmod._running_procs


def test_run_while_running_is_conflict(client, sid):
    client.put(
        f"/api/sessions/{sid}/files/sleepy.py",
        json={"content": "import time\ntime.sleep(60)\n"},
    )
    results = {}

    def do_run():
        results["res"] = client.post(f"/api/sessions/{sid}/run", json={"file_path": "sleepy.py"})

    thread = threading.Thread(target=do_run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while sid not in appmod._running_procs and time.time() < deadline:
        time.sleep(0.05)
    assert sid in appmod._running_procs

    res2 = client.post(f"/api/sessions/{sid}/run", json={"file_path": "sleepy.py"})
    assert res2.status_code == 409

    client.post(f"/api/sessions/{sid}/stop")
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_chat_stream_emits_events(client, sid):
    fake = mock.Mock()

    def fake_handle(message, confirmed=False):
        from coding_agent.events import emit

        emit({"type": "phase", "message": "Working…"})
        emit({"type": "chunk", "text": "Hel"})
        emit({"type": "chunk", "text": "lo"})
        return "Hello"

    fake.handle = fake_handle
    with mock.patch.object(appmod, "_get_agent", return_value=(fake, sid)):
        res = client.post("/api/chat/stream", json={"message": "hi", "session_id": sid})
    assert res.status_code == 200
    events = parse_sse(res.content.decode("utf-8"))
    types = [e["type"] for e in events]
    assert "phase" in types
    assert "chunk" in types
    assert types[-1] == "done"
    done = next(e for e in events if e["type"] == "done")
    assert done["response"] == "Hello"


def test_chat_stream_emits_confirmation(client, sid):
    from coding_agent.agent import CONFIRMATION_MARKER

    fake = mock.Mock()
    marker = f"{CONFIRMATION_MARKER}\nAction: delete_file\nTarget: x.py"
    fake.handle.return_value = marker
    with mock.patch.object(appmod, "_get_agent", return_value=(fake, sid)):
        res = client.post("/api/chat/stream", json={"message": "delete x.py", "session_id": sid})
    assert res.status_code == 200
    events = parse_sse(res.content.decode("utf-8"))
    assert events[-1]["type"] == "confirmation"
    assert events[-1]["action"] == "delete_file"
    assert events[-1]["target"] == "x.py"


def test_chat_stream_emits_error(client, sid):
    fake = mock.Mock()
    fake.handle.side_effect = RuntimeError("boom")
    with mock.patch.object(appmod, "_get_agent", return_value=(fake, sid)):
        res = client.post("/api/chat/stream", json={"message": "hi", "session_id": sid})
    assert res.status_code == 200
    events = parse_sse(res.content.decode("utf-8"))
    assert events[-1]["type"] == "error"


def test_run_missing_workspace_404(client, sid):
    res = client.post("/api/sessions/ghost/run", json={"file_path": "app.py"})
    assert res.status_code == 404


def test_create_session_creates_workspace(client):
    res = client.post("/api/sessions/brand-new-tab")
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == "brand-new-tab"
    assert (appmod.WORKSPACES / "brand-new-tab").is_dir()

    files = client.get("/api/sessions/brand-new-tab/files")
    assert files.status_code == 200
    assert files.json()["tree"] == []


def test_create_session_is_idempotent(client):
    res1 = client.post("/api/sessions/dup")
    res2 = client.post("/api/sessions/dup")
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res2.json()["session_id"] == "dup"
