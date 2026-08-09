from coding_agent.compaction import CompactionManager, estimate_tokens


class FakeMemory:
    def __init__(self) -> None:
        self.turns = []
        self.preferences = {}
        self.deleted = []

    def add_turn(self, user_message, agent_response, intent="", target=""):
        self.turns.append({
            "id": f"id{len(self.turns)}",
            "document": f"User: {user_message}\nAgent: {agent_response}",
            "metadata": {"timestamp": len(self.turns)},
        })

    def get_all_by_type(self, doc_type):
        return self.turns if doc_type == "chat" else []

    def get_preference(self, key):
        return self.preferences.get(key)

    def set_preference(self, key, value):
        self.preferences[key] = value

    def delete_by_ids(self, ids):
        self.deleted.extend(ids)
        self.turns = [t for t in self.turns if t["id"] not in ids]


def _fill(memory, count):
    for i in range(count):
        memory.add_turn(f"question {i}", "answer words words words")


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2
    assert estimate_tokens("x" * 100) == 25


def test_should_compact_under_budget():
    memory = FakeMemory()
    _fill(memory, 5)
    manager = CompactionManager(memory, max_tokens=1000)
    assert manager.should_compact() is False


def test_compact_prunes_old_turns():
    memory = FakeMemory()
    _fill(memory, 30)
    manager = CompactionManager(memory, max_tokens=200, keep_recent=10)
    assert manager.should_compact() is True
    summary = manager.compact()
    assert summary is not None
    assert len(memory.turns) == 10
    assert len(memory.deleted) == 20
    assert memory.get_preference("compaction_summary")


def test_compact_uses_generator():
    memory = FakeMemory()
    _fill(memory, 30)
    calls = []

    def fake_generate(system, user):
        calls.append(user)
        return "COMPACTED SUMMARY text"

    manager = CompactionManager(memory, generate=fake_generate, max_tokens=200, keep_recent=10)
    summary = manager.compact()
    assert summary == "COMPACTED SUMMARY text"
    assert "Previous summary" in calls[0]
    assert "Conversation to fold in" in calls[0]


def test_compact_noop_below_keep_threshold():
    memory = FakeMemory()
    _fill(memory, 5)
    manager = CompactionManager(memory, generate=lambda s, u: "x", max_tokens=1000, keep_recent=10)
    assert manager.compact() is None


def test_current_tokens_includes_summary():
    memory = FakeMemory()
    _fill(memory, 10)
    manager = CompactionManager(memory, max_tokens=1000)
    before = manager.current_tokens()
    memory.set_preference("compaction_summary", "S" * 400)
    after = manager.current_tokens()
    assert after > before
