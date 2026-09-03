"""Phase 2 tests: budget assembly + file content injection."""

import os
from pathlib import Path

from coding_agent import context_budget
from coding_agent.context_budget import ContextSection, assemble, truncate_to_tokens
from coding_agent.file_context import collect_relevant_files
from coding_agent.tokens import estimate_tokens


def test_truncate_marks_cut() -> None:
    text = "x" * 1000  # ~250 tokens
    out = truncate_to_tokens(text, 10)
    assert "[... truncated to fit context budget]" in out
    assert estimate_tokens(out) <= 15
    assert truncate_to_tokens("short", 100) == "short"


def test_assemble_respects_total() -> None:
    sections = [
        ContextSection("identity", "", "proj info"),
        ContextSection("history", "Chat history:", "y" * 20000),
        ContextSection("summary", "Summary:", "z" * 20000),
    ]
    out = assemble(sections, total_tokens=500)
    assert estimate_tokens(out) <= 600
    assert "proj info" in out  # highest priority survives


def test_assemble_priority_order() -> None:
    # Contract: sections are filled in the order given (caller passes
    # priority order); earlier sections win when the budget is tight.
    sections = [
        ContextSection("target", "Target:", "t" * 4000),
        ContextSection("summary", "Summary:", "s" * 4000),
    ]
    out = assemble(sections, total_tokens=300)
    assert "Target:" in out
    assert "Summary:" not in out


def test_assemble_skips_empty_and_caps_sections() -> None:
    sections = [
        ContextSection("history", "Chat:", ""),
        ContextSection("history", "Chat:", "h" * 8000),  # ~2000 tokens, cap 2500
    ]
    out = assemble(sections, total_tokens=100_000)
    assert "Chat:" in out
    assert estimate_tokens(out) <= context_budget.SECTION_CAPS["history"] + 100


def test_assemble_env_override(monkeypatch) -> None:
    monkeypatch.setenv("CODING_AGENT_CONTEXT_TOKENS", "100")
    assert context_budget.budget_total() == 100
    monkeypatch.setenv("CODING_AGENT_CONTEXT_TOKENS", "junk")
    assert context_budget.budget_total() == context_budget.DEFAULT_TOTAL_TOKENS


def test_collect_reads_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print('a')\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("print('b')\n")
    out = collect_relevant_files(tmp_path, ["a.py", "sub/b.py", "a.py", "missing.py"])
    assert [f["path"] for f in out] == ["a.py", "sub/b.py"]
    assert "print('a')" in out[0]["content"]


def test_collect_skips_binary_oversize_escape(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02binary")
    (tmp_path / "big.txt").write_text("x" * 200_000)
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret")
    out = collect_relevant_files(tmp_path, ["bin.dat", "big.txt", "../secret.txt"])
    assert out == []


def test_collect_truncates_long_files(tmp_path: Path) -> None:
    (tmp_path / "long.py").write_text("y" * 50_000)  # under 100k bytes, over char cap
    out = collect_relevant_files(tmp_path, ["long.py"])
    assert len(out) == 1
    assert "[... file truncated]" in out[0]["content"]


def test_build_injects_target_and_memory_files(tmp_path: Path) -> None:
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    (tmp_path / "auth.py").write_text("def login():\n    pass\n")
    (tmp_path / "other.py").write_text("x = 1\n")
    memory = FakeMemory()
    memory.add_file_event("other.py", "modified", "touched")
    builder = ContextBuilder(memory, root=tmp_path)

    ctx = builder.build("fix login", intent_name="modify_code", intent_target="auth.py")
    paths = [f["path"] for f in ctx.relevant_file_contents]
    assert paths[0] == "auth.py"  # target first
    assert "other.py" in paths
    assert ctx.target_path == "auth.py"
    assert "def login" in ctx.relevant_file_contents[0]["content"]


def test_build_skips_injection_for_non_code_intents(tmp_path: Path) -> None:
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    (tmp_path / "auth.py").write_text("def login():\n    pass\n")
    builder = ContextBuilder(FakeMemory(), root=tmp_path)
    ctx = builder.build("commit now", intent_name="commit", intent_target="")
    assert ctx.relevant_file_contents == []
    assert ctx.target_path == ""


def test_format_stays_within_budget(tmp_path: Path) -> None:
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    (tmp_path / "big.py").write_text("z = '" + "z" * 50_000 + "'\n")
    memory = FakeMemory()
    # recent_turns-shaped rows (user/agent keys), as the real store returns
    memory.turns = [
        {"user": f"question {i} " + "w" * 2000, "agent": "answer " + "v" * 3000}
        for i in range(5)
    ]
    memory.add_file_event("big.py", "modified", "x" * 2000)
    builder = ContextBuilder(memory, root=tmp_path)

    ctx = builder.build("explain big", intent_name="explain", intent_target="big.py")
    prompt = builder.format_for_prompt(ctx)
    assert estimate_tokens(prompt) <= context_budget.budget_total() + 100
    assert "--- Target File ---" in prompt or "--- Relevant Files ---" in prompt
    assert "Chat history:" in prompt or "question" in prompt


def test_format_without_files_omits_sections(tmp_path: Path) -> None:
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    builder = ContextBuilder(FakeMemory(), root=tmp_path)
    ctx = builder.build("hello")
    prompt = builder.format_for_prompt(ctx)
    assert "--- Target File ---" not in prompt
    assert "--- Relevant Files ---" not in prompt
    assert "Project:" in prompt
