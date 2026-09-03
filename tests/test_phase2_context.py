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
    assert estimate_tokens(out) <= 500  # strict: headers counted, no slack
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
    assert estimate_tokens(out) <= context_budget.SECTION_CAPS["history"]


def test_assemble_tiny_budget_never_exceeds() -> None:
    sections = [
        ContextSection("identity", "", "proj info here"),
        ContextSection("history", "Chat history:", "y" * 5000),
    ]
    for total in (1, 5, 20):
        out = assemble(sections, total_tokens=total)
        assert estimate_tokens(out) <= total, f"budget {total} exceeded: {estimate_tokens(out)}"


def test_truncate_fence_aware_recloses() -> None:
    text = "### a.py\n```\n" + "code line\n" * 30 + "```\n"
    out = truncate_to_tokens(text, 11, fence_aware=True)
    assert out.count("```") % 2 == 0  # balanced
    assert "[... truncated to fit context budget]" in out
    assert estimate_tokens(out) <= 11


def test_truncate_degenerate_keeps_fences_balanced() -> None:
    out = truncate_to_tokens("### a.py\n```\n" + "code\n" * 20, 10, fence_aware=True)
    assert out.count("```") % 2 == 0
    assert estimate_tokens(out) <= 10


def test_truncate_degenerate_budget_hard_cuts() -> None:
    out = truncate_to_tokens("y" * 1000, 1, fence_aware=True)
    assert estimate_tokens(out) <= 1


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


def test_collect_dedupes_aliases(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.py").write_text("y = 2\n")
    out = collect_relevant_files(
        tmp_path, ["foo.py", "./foo.py", "sub/../foo.py", "sub/deep.py", "./sub/deep.py"]
    )
    assert [f["path"] for f in out] == ["foo.py", "sub/deep.py"]


def test_normalize_target_variants(tmp_path: Path) -> None:
    from coding_agent.file_context import normalize_target

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "t.py").write_text("x\n")
    assert normalize_target(tmp_path, "sub/t.py") == "sub/t.py"
    assert normalize_target(tmp_path, "./sub/t.py") == "sub/t.py"
    assert normalize_target(tmp_path, "sub/../sub/t.py") == "sub/t.py"
    assert normalize_target(tmp_path, str(tmp_path / "sub" / "t.py")) == "sub/t.py"
    assert normalize_target(tmp_path, "missing.py") == ""
    assert normalize_target(tmp_path, "") == ""
    assert normalize_target(tmp_path, "../outside.py") == ""


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


def test_build_injects_recent_files_despite_chat_results(tmp_path: Path) -> None:
    """Bug 1: chat-only semantic results must not suppress file injection."""
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    (tmp_path / "recent.py").write_text("r = 1\n")
    memory = FakeMemory()
    memory.retrieve_similar = lambda q, k=5, doc_type=None, max_distance=0.95: [
        {"id": "c1", "document": "chat about auth",
         "metadata": {"doc_type": "chat", "content": "chat about auth"}, "distance": 0.1},
    ]
    memory.add_file_event("recent.py", "modified", "touched recently")
    builder = ContextBuilder(memory, root=tmp_path)

    ctx = builder.build("fix it", intent_name="modify_code", intent_target="")
    assert [f["path"] for f in ctx.relevant_file_contents] == ["recent.py"]


def test_build_target_alias_keeps_priority(tmp_path: Path) -> None:
    """Bug 3: ./auth.py target is classified as the target file."""
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    (tmp_path / "auth.py").write_text("def login():\n    pass\n")
    builder = ContextBuilder(FakeMemory(), root=tmp_path)
    ctx = builder.build("fix login", intent_name="modify_code", intent_target="./auth.py")
    assert ctx.target_path == "auth.py"
    prompt = builder.format_for_prompt(ctx)
    assert "--- Target File ---" in prompt


def test_format_balances_fences_under_pressure(tmp_path: Path) -> None:
    """Bug 5: many files over the files-cap keep balanced fences."""
    from tests.fakes import FakeMemory

    from coding_agent.context import ContextBuilder

    for i in range(5):
        (tmp_path / f"f{i}.py").write_text(f"# file {i}\n" + "x = 1\n" * 2000)
    builder = ContextBuilder(FakeMemory(), root=tmp_path)
    ctx = builder.build(
        "fix all", intent_name="modify_code",
        intent_target="f0.py",
    )
    prompt = builder.format_for_prompt(ctx)
    files_part = prompt.split("--- Relevant Files ---")[1] if "--- Relevant Files ---" in prompt else prompt
    # fences balanced in every file section present
    assert prompt.count("```") % 2 == 0


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
    assert estimate_tokens(prompt) <= context_budget.budget_total()
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
