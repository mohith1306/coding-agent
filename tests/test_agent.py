import subprocess
from pathlib import Path

import pytest

from coding_agent.agent import CONFIRMATION_MARKER, CodingAgent
from coding_agent.intent import Intent


class FakeMemory:
    def __init__(self) -> None:
        self.turns = []
        self.tasks = []
        self.preferences = {}

    def add_turn(self, user_message, agent_response, intent="", target=""):
        self.turns.append((user_message, agent_response, intent, target))

    def recent_turns(self, limit=5):
        return []

    def retrieve_similar(self, query, k=5, doc_type=None, max_distance=0.95):
        return []

    def get_by_type(self, doc_type, limit=20):
        if doc_type == "task":
            return self.tasks
        return []

    def add_task(self, description, status="pending", files_affected=None):
        self.tasks.append({
            "metadata": {
                "description": description,
                "status": status,
                "files_affected": ",".join(files_affected or []),
            }
        })

    def add_file_event(self, path, operation, content=""):
        pass

    def set_preference(self, key, value):
        self.preferences[key] = value

    def get_preference(self, key):
        return self.preferences.get(key)

    def list_preferences(self):
        return [{"key": k, "value": v} for k, v in sorted(self.preferences.items())]


@pytest.fixture
def agent(workspace: Path, monkeypatch) -> CodingAgent:
    monkeypatch.chdir(workspace)
    agent = CodingAgent(memory=FakeMemory(), root=workspace)
    return agent


def _intent(name, target="", raw="", confirm=False, args=None):
    return Intent(name=name, target=target, raw_message=raw, confidence=0.9, requires_confirmation=confirm, args=args or {})


def test_confirmation_required_when_not_confirmed(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("delete_file", "x.txt", raw=msg, confirm=True)
    response = agent.handle("delete x.txt")
    assert response.startswith(CONFIRMATION_MARKER)
    assert "Action: delete_file" in response


def test_delete_confirmed(agent: CodingAgent, workspace: Path) -> None:
    (workspace / "x.txt").write_text("data")
    agent.intent_parser.parse = lambda msg: _intent("delete_file", "x.txt", raw=msg, confirm=True)
    response = agent.handle("delete x.txt", confirmed=True)
    assert "Deleted" in response
    assert not (workspace / "x.txt").exists()
    assert agent.memory.tasks[-1]["metadata"]["status"] == "done"


def test_resolve_run_file_py(agent: CodingAgent, workspace: Path) -> None:
    (workspace / "dfs.py").write_text("print(1)")
    resolved = agent._resolve_run_file("dfs")
    assert resolved == "python3 dfs.py"


def test_resolve_run_file_exact(agent: CodingAgent, workspace: Path) -> None:
    (workspace / "run.sh").write_text("#!/bin/sh\necho hi")
    resolved = agent._resolve_run_file("run.sh")
    assert resolved == "run.sh"


def test_resolve_run_file_missing(agent: CodingAgent, workspace: Path) -> None:
    assert agent._resolve_run_file("nope") is None


def test_commit_message_from_target(agent: CodingAgent) -> None:
    status = agent.git.status()
    msg = agent._commit_message(_intent("commit", "fix typo"), status)
    assert msg == "fix typo"


def test_commit_message_from_dirty(agent: CodingAgent, workspace: Path) -> None:
    from coding_agent.tools.git import GitContext

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=workspace, check=True)
    (workspace / "a.py").write_text("print(1)\n")
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=workspace, check=True, capture_output=True)
    (workspace / "b.py").write_text("print(2)\n")
    status = GitContext(workspace).status()
    msg = agent._commit_message(_intent("commit", ""), status)
    assert "b.py" in msg


def test_list_tasks_empty(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("list_tasks")
    response = agent.handle("show tasks")
    assert "No tasks recorded" in response


def test_list_tasks_with_tasks(agent: CodingAgent) -> None:
    agent.memory.tasks.append({"metadata": {"description": "Create x.py", "status": "done", "files_affected": "x.py"}})
    agent.intent_parser.parse = lambda msg: _intent("list_tasks")
    response = agent.handle("show tasks")
    assert "Create x.py" in response
    assert "done" in response


def test_remember_and_recall(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("remember", "name", raw=msg, args={"value": "Mohith"})
    response = agent.handle("remember my name is Mohith")
    assert "Remembered" in response
    assert agent.memory.get_preference("name") == "Mohith"

    agent.intent_parser.parse = lambda msg: _intent("recall", "", raw=msg)
    response = agent.handle("what do you remember")
    assert "name: Mohith" in response


def test_plan_executes_create(agent: CodingAgent, workspace: Path) -> None:
    agent.intent_parser.parse = lambda msg: _intent("plan", "hello.py", raw=msg, confirm=True)
    agent.intent_parser.generate = lambda sys_p, user_p: "print('hello')\n"

    r1 = agent.handle("plan and implement hello.py")
    assert r1.startswith(CONFIRMATION_MARKER)

    r2 = agent.handle("plan and implement hello.py", confirmed=True)
    assert "Plan executed" in r2
    assert (workspace / "hello.py").read_text() == "print('hello')"


def test_plan_executes_modify(agent: CodingAgent, workspace: Path) -> None:
    (workspace / "utils.py").write_text("print('old')\n")
    agent.intent_parser.parse = lambda msg: _intent("plan", "utils.py", raw=msg, confirm=True)
    agent.intent_parser.generate = lambda sys_p, user_p: "print('new')\n"

    r2 = agent.handle("plan and implement in utils.py", confirmed=True)
    assert "Plan executed" in r2
    assert "Modified" in r2
    assert (workspace / "utils.py").read_text() == "print('new')\n"


def test_plan_not_executable(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("plan", "", raw=msg)
    response = agent.handle("plan out how to build a login feature")
    assert response.startswith("Here's a plan")
