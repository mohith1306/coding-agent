import sys
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web" / "backend"))
import app as appmod  # noqa: E402


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


def test_run_python_runs_in_sandbox(client, sid):
    client.put(f"/api/sessions/{sid}/files/app.py", json={"content": "print('ok')\n"})
    fake = mock.Mock()
    fake.terminal.run.return_value = "Exit code: 0\nok"
    with mock.patch.object(appmod, "_get_agent", return_value=(fake, sid)):
        res = client.post(f"/api/sessions/{sid}/run", json={"file_path": "app.py"})
    assert res.status_code == 200
    assert res.json()["result"] == "Exit code: 0\nok"
    fake.terminal.run.assert_called_once()
    assert "app.py" in fake.terminal.run.call_args[0][0]


def test_run_missing_workspace_404(client, sid):
    res = client.post("/api/sessions/ghost/run", json={"file_path": "app.py"})
    assert res.status_code == 404
