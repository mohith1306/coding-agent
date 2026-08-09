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
        self.deleted = []

    def add_turn(self, user_message, agent_response, intent="", target=""):
        self.turns.append({
            "id": f"id{len(self.turns)}",
            "document": f"User: {user_message}\nAgent: {agent_response}",
            "metadata": {"timestamp": len(self.turns)},
        })

    def recent_turns(self, limit=5):
        return []

    def retrieve_similar(self, query, k=5, doc_type=None, max_distance=0.95):
        return []

    def get_by_type(self, doc_type, limit=20):
        if doc_type == "task":
            return self.tasks
        return []

    def get_all_by_type(self, doc_type):
        if doc_type == "chat":
            return self.turns
        return []

    def delete_by_ids(self, ids):
        self.deleted.extend(ids)
        self.turns = [t for t in self.turns if t["id"] not in ids]

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


def _intent(name, target="", raw="", confirm=False, args=None, reason=""):
    return Intent(name=name, target=target, raw_message=raw, confidence=0.9, requires_confirmation=confirm, args=args or {}, reason=reason)


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


def test_plan_not_executable_answers_via_llm(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("plan", "", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: "1. Set up a login form.\n2. Validate credentials."
    response = agent.handle("plan out how to build a login feature")
    assert "login" in response.lower()
    assert "form" in response.lower()
    assert "Here's a plan" not in response


def test_explain_answers_via_llm(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("explain", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: "Use React + Flask + SQLite."
    response = agent.handle("suggest a tech stack")
    assert "react" in response.lower()
    assert "Intent detected" not in response


def test_unknown_answers_via_llm_with_fallback(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("unknown", raw=msg, reason="Ambiguous request")
    agent.intent_parser.generate = lambda sys_p, user_p: ""
    response = agent.handle("some gibberish")
    assert "could not parse the intent" in response


def test_auto_compaction_triggers_in_handle(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("explain", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: "COMPACTED: task summary here."
    agent.compaction.max_tokens = 100
    agent.compaction.keep_recent = 10

    for i in range(20):
        agent.handle(f"request number {i}")

    assert len(agent.memory.turns) == 10
    assert len(agent.memory.deleted) > 0
    assert agent.memory.get_preference("compaction_summary") == "COMPACTED: task summary here."


def test_auto_compaction_noop_under_budget(agent: CodingAgent) -> None:
    agent.intent_parser.parse = lambda msg: _intent("explain", raw=msg)

    for i in range(3):
        agent.handle(f"request number {i}")

    assert len(agent.memory.turns) == 3
    assert agent.memory.get_preference("compaction_summary") is None


def test_create_python_requires_confirmation(agent: CodingAgent, workspace: Path) -> None:
    agent.intent_parser.parse = lambda msg: _intent("create_file", "hello.py", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: "print('hello')\n"

    r1 = agent.handle("create hello.py")
    assert r1.startswith(CONFIRMATION_MARKER)
    assert "Make this change to `hello.py`?" in r1
    assert "print('hello')" in r1
    assert not (workspace / "hello.py").exists()

    r2 = agent.handle("create hello.py", confirmed=True)
    assert "Created" in r2
    assert (workspace / "hello.py").read_text() == "print('hello')"


def test_modify_python_requires_confirmation(agent: CodingAgent, workspace: Path) -> None:
    (workspace / "utils.py").write_text("print('old')\n")
    agent.intent_parser.parse = lambda msg: _intent("modify_code", "utils.py", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: "print('new')\n"

    r1 = agent.handle("update utils.py")
    assert r1.startswith(CONFIRMATION_MARKER)
    assert "Make this change to `utils.py`?" in r1
    assert "-print('old')" in r1
    assert (workspace / "utils.py").read_text() == "print('old')\n"

    r2 = agent.handle("update utils.py", confirmed=True)
    assert "Modified" in r2
    assert (workspace / "utils.py").read_text() == "print('new')\n"


def test_create_python_runs_sandbox_test(agent: CodingAgent, workspace: Path) -> None:
    agent.intent_parser.parse = lambda msg: _intent("create_file", "hello.py", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: "print('hello')\n"

    agent.terminal = agent._build_terminal()
    captured = {}

    def fake_run(command, timeout=30):
        captured["command"] = command
        return "Exit code: 0\nhello\n"

    agent.terminal.run = fake_run

    agent.handle("create hello.py")
    r2 = agent.handle("create hello.py", confirmed=True)
    assert "Sandbox test: [PASS]" in r2
    assert captured.get("command") == "python3 hello.py"


def test_create_non_python_no_confirmation(agent: CodingAgent, workspace: Path) -> None:
    agent.intent_parser.parse = lambda msg: _intent("create_file", "notes.txt", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: "hello world"

    r = agent.handle("create notes.txt")
    assert not r.startswith(CONFIRMATION_MARKER)
    assert (workspace / "notes.txt").read_text() == "hello world"


def test_create_files_requires_confirmation(agent: CodingAgent, workspace: Path) -> None:
    targets = ["sliding_window.py", "two_pointers.py", "binary_search.py"]
    agent.intent_parser.parse = lambda msg: _intent("create_files", "", raw=msg, args={"targets": targets})
    agent.intent_parser.generate = lambda sys_p, user_p: "def run():\n    return 0\n"

    r1 = agent.handle("make separate files for sliding window, two pointers, binary search")
    assert r1.startswith(CONFIRMATION_MARKER)
    assert "Action: create_files" in r1
    assert "sliding_window.py, two_pointers.py, binary_search.py" in r1
    for name in targets:
        assert not (workspace / name).exists()

    r2 = agent.handle("make separate files", confirmed=True)
    assert "Created multiple files" in r2
    for name in targets:
        assert (workspace / name).read_text() == "def run():\n    return 0"


def test_create_files_infers_targets(agent: CodingAgent, workspace: Path) -> None:
    agent.intent_parser.parse = lambda msg: _intent("create_files", "", raw=msg, args={})
    agent.intent_parser.generate = lambda sys_p, user_p: "def run():\n    return 0\n"

    agent.handle("make files for sliding window and binary search", confirmed=True)
    assert (workspace / "sliding_window.py").exists()
    assert (workspace / "binary_search.py").exists()


def test_create_project_requires_confirmation(agent: CodingAgent, workspace: Path) -> None:
    agent.intent_parser.parse = lambda msg: _intent("create_project", "", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: (
        '{"files":["server/models/Todo.js","server/routes/todo.js","server/app.js"]}'
    )

    r1 = agent.handle("create a to-do list project with the necessary tech stack")
    assert r1.startswith(CONFIRMATION_MARKER)
    assert "Action: create_project" in r1
    assert "Project structure" in r1
    assert "server/models/Todo.js" in r1
    for name in ["server/models/Todo.js", "server/routes/todo.js", "server/app.js"]:
        assert not (workspace / name).exists()

    r2 = agent.handle("create a to-do list project", confirmed=True)
    assert "Project created with 3 files" in r2
    for name in ["server/models/Todo.js", "server/routes/todo.js", "server/app.js"]:
        assert (workspace / name).exists()


def test_create_project_writes_nested_folders(agent: CodingAgent, workspace: Path) -> None:
    agent.intent_parser.parse = lambda msg: _intent("create_project", "", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: (
        '{"files":["client/src/components/Todo.js","server/config/db.js"]}'
    )

    r = agent.handle("build a todo app", confirmed=True)
    assert "Project created with 2 files" in r
    assert (workspace / "client/src/components/Todo.js").is_file()
    assert (workspace / "server/config/db.js").is_file()


def test_create_project_strips_code_fences(agent: CodingAgent, workspace: Path) -> None:
    agent.intent_parser.parse = lambda msg: _intent("create_project", "", raw=msg)
    agent.intent_parser.generate = lambda sys_p, user_p: (
        '{"files":["server/models/Todo.js","server/routes/todo.js","server/app.js"]}'
        if "architect" in sys_p
        else "server/models/Todo.js\n```javascript\nclass Todo {\n  constructor() {}\n}\n```"
    )

    r = agent.handle("create a to-do project", confirmed=True)
    content = (workspace / "server/models/Todo.js").read_text()
    assert content.startswith("class Todo {")
    assert "```" not in content
    assert "server/models/Todo.js" not in content


def test_create_file_repaired_on_syntax_error(agent: CodingAgent, workspace: Path) -> None:
    junk = "DSA/\nsliding_window.py\ntwo_pointers.py\n\nclass SlidingWindow:\n    pass\n"
    clean = "class SlidingWindow:\n    def max_sum_subarray(self, arr, k):\n        return 0"
    calls = []

    def fake_generate(sys_p, user_p):
        calls.append(user_p)
        return clean if len(calls) > 1 else junk

    agent.intent_parser.parse = lambda msg: _intent("create_file", "sliding_window.py", raw=msg)
    agent.intent_parser.generate = fake_generate
    agent.terminal = agent._build_terminal()
    agent.terminal.run = lambda command, timeout=30: "Exit code: 0\n"

    r = agent.handle("create sliding_window.py", confirmed=True)
    assert "repaired after 1 attempt" in r
    assert (workspace / "sliding_window.py").read_text() == clean
    assert len(calls) == 2


def test_create_file_repair_failures_reported(agent: CodingAgent, workspace: Path) -> None:
    junk = "DSA/\nsliding_window.py\n\nclass SlidingWindow:\n    pass\n"
    calls = []

    def fake_generate(sys_p, user_p):
        calls.append(user_p)
        return f"{junk}  # attempt {len(calls)}\n"

    agent.intent_parser.parse = lambda msg: _intent("create_file", "sliding_window.py", raw=msg)
    agent.intent_parser.generate = fake_generate
    agent.terminal = agent._build_terminal()
    agent.terminal.run = lambda command, timeout=30: "Exit code: 1\nboom\n"

    r = agent.handle("create sliding_window.py", confirmed=True)
    assert "could not repair after 3 attempts" in r
    assert "SyntaxError" in r
    assert len(calls) == 4


def test_create_files_repaired_per_file(agent: CodingAgent, workspace: Path) -> None:
    junk = "DSA/\n__init__.py\nsliding_window.py\ntwo_pointers.py\nbinary_search.py\n\nclass X:\n    pass\n"
    clean = "def run():\n    return 0"
    calls = []

    def fake_generate(sys_p, user_p):
        calls.append(user_p)
        return clean if len(calls) > 1 else junk

    targets = ["sliding_window.py", "two_pointers.py", "binary_search.py"]
    agent.intent_parser.parse = lambda msg: _intent("create_files", "", raw=msg, args={"targets": targets})
    agent.intent_parser.generate = fake_generate
    agent.terminal = agent._build_terminal()
    agent.terminal.run = lambda command, timeout=30: "Exit code: 0\n"

    r1 = agent.handle("make separate files for sliding window, two pointers, binary search")
    assert r1.startswith(CONFIRMATION_MARKER)

    r2 = agent.handle("make separate files", confirmed=True)
    assert "repaired after 1 attempt" in r2
    for name in targets:
        assert (workspace / name).read_text() == clean
