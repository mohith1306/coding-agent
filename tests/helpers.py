"""Test helpers for tool-call assertions and agent trace validation.

Provides deterministic assertions for testing agent behavior without
relying on exact LLM text output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Optional


# ---------------------------------------------------------------------------
# Tool-call trace recording
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """Recorded tool invocation."""
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass
class AgentTrace:
    """Full trace of an agent run for assertion."""
    tool_calls: list[ToolCall] = field(default_factory=list)
    intent_names: list[str] = field(default_factory=list)
    final_response: str = ""
    errors: list[str] = field(default_factory=list)

    def record_tool(self, name: str, args: Optional[Dict[str, Any]] = None, result: Any = None) -> None:
        self.tool_calls.append(ToolCall(name=name, args=args or {}, result=result))

    def record_intent(self, name: str) -> None:
        self.intent_names.append(name)

    def record_error(self, message: str) -> None:
        self.errors.append(message)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

class ToolCallAssertionError(AssertionError):
    """Raised when tool-call assertions fail."""


def assert_tool_called(
    trace: AgentTrace,
    tool_name: str,
    *,
    min_times: int = 1,
    max_times: Optional[int] = None,
) -> list[ToolCall]:
    """Assert a tool was called at least min_times (and optionally at most max_times).

    Returns all matching ToolCall records.
    """
    matches = [tc for tc in trace.tool_calls if tc.name == tool_name]
    count = len(matches)

    if count < min_times:
        raise ToolCallAssertionError(
            f"Expected '{tool_name}' to be called at least {min_times} time(s), "
            f"but it was called {count} time(s). "
            f"Actual calls: {[tc.name for tc in trace.tool_calls]}"
        )

    if max_times is not None and count > max_times:
        raise ToolCallAssertionError(
            f"Expected '{tool_name}' to be called at most {max_times} time(s), "
            f"but it was called {count} time(s)."
        )

    return matches


def assert_tool_sequence(
    trace: AgentTrace,
    expected: list[str],
    *,
    contiguous: bool = True,
) -> None:
    """Assert tools were called in a specific order.

    If contiguous=True, the sequence must appear consecutively.
    If contiguous=False, the sequence must appear as a subsequence.
    """
    actual_names = [tc.name for tc in trace.tool_calls]

    if contiguous:
        # Find the exact subsequence
        for i in range(len(actual_names) - len(expected) + 1):
            if actual_names[i:i + len(expected)] == expected:
                return
        raise ToolCallAssertionError(
            f"Expected contiguous sequence {expected}, "
            f"but got {actual_names}"
        )
    else:
        # Check subsequence (order preserved but not necessarily adjacent)
        it = iter(actual_names)
        for target in expected:
            if not any(name == target for name in it):
                raise ToolCallAssertionError(
                    f"Expected {expected} as subsequence, "
                    f"but got {actual_names}"
                )


def assert_no_tool_called(trace: AgentTrace, tool_name: str) -> None:
    """Assert a specific tool was NOT called."""
    matches = [tc for tc in trace.tool_calls if tc.name == tool_name]
    if matches:
        raise ToolCallAssertionError(
            f"Expected '{tool_name}' to NOT be called, "
            f"but it was called {len(matches)} time(s)"
        )


def assert_max_tool_calls(trace: AgentTrace, max_total: int) -> None:
    """Assert total tool calls don't exceed a budget."""
    count = len(trace.tool_calls)
    if count > max_total:
        raise ToolCallAssertionError(
            f"Expected at most {max_total} total tool calls, "
            f"but got {count}: {[tc.name for tc in trace.tool_calls]}"
        )


def assert_tool_args(
    tool_call: ToolCall,
    expected_args: dict[str, Any],
    *,
    ignore_keys: Optional[Set[str]] = None,
) -> None:
    """Assert a tool call has specific arguments.

    Only checks keys present in expected_args — extra keys are ignored.
    Use ignore_keys to skip volatile fields like timestamps.
    """
    ignore = ignore_keys or set()
    actual = {k: v for k, v in tool_call.args.items() if k not in ignore}
    expected = {k: v for k, v in expected_args.items() if k not in ignore}

    for key, value in expected.items():
        if key not in actual:
            raise ToolCallAssertionError(
                f"Missing arg '{key}' in tool call '{tool_call.name}'. "
                f"Actual args: {actual}"
            )
        if actual[key] != value:
            raise ToolCallAssertionError(
                f"Arg '{key}' for '{tool_call.name}': "
                f"expected {value!r}, got {actual[key]!r}"
            )


def assert_intent_sequence(trace: AgentTrace, expected: list[str]) -> None:
    """Assert intents were parsed in a specific order."""
    if trace.intent_names != expected:
        raise ToolCallAssertionError(
            f"Expected intent sequence {expected}, "
            f"but got {trace.intent_names}"
        )


def assert_no_errors(trace: AgentTrace) -> None:
    """Assert no errors were recorded."""
    if trace.errors:
        raise ToolCallAssertionError(
            f"Expected no errors, but got: {trace.errors}"
        )


def summarize_trace(trace: AgentTrace) -> str:
    """Human-readable summary of an agent trace for debugging."""
    lines = ["Agent Trace Summary:"]
    lines.append(f"  Intents: {trace.intent_names}")
    lines.append(f"  Tool calls ({len(trace.tool_calls)}):")
    for i, tc in enumerate(trace.tool_calls):
        args_str = ", ".join(f"{k}={v!r}" for k, v in tc.args.items())
        lines.append(f"    [{i}] {tc.name}({args_str})")
    if trace.errors:
        lines.append(f"  Errors: {trace.errors}")
    lines.append(f"  Final response: {trace.final_response[:100]}...")
    return "\n".join(lines)
