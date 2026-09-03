"""Conditional edges — routing logic for the LangGraph state machine."""

from typing import Any

from .config import MAX_REPAIR_ATTEMPTS, MAX_TOOL_ITERATIONS
from .state import AgentState


def route_after_plan(state: AgentState) -> str:
    """Route after the plan node based on path type.

    Read-only intents go directly to agent (no tools needed).
    Write intents go to agent then tools.
    """
    path_type = state.get("path_type", "write")
    if path_type == "read_only":
        return "agent"
    return "agent"


def route_after_agent(state: AgentState) -> str:
    """Route after the agent node.

    - If agent returned tool_calls → go to tools
    - If agent returned a final_response (read-only) → go to finish
    - If agent returned an error → go to finish
    """
    tool_calls = state.get("tool_calls", [])
    if tool_calls:
        return "tools"

    final_response = state.get("final_response", "")
    if final_response:
        return "finish"

    error = state.get("error", "")
    if error:
        return "finish"

    return "finish"


def route_after_tools(state: AgentState) -> str:
    """Route after tool execution.

    - If changed_files exist → go to verify
    - If inspection-only results exist and under iteration limit → go back to agent
    - Otherwise → go to finish
    """
    changed_files = state.get("changed_files", [])
    if changed_files:
        return "verify"

    # Inspection-only batch: route back to agent so it can consume results and issue edits
    tool_results = state.get("tool_results", [])
    if tool_results:
        iterations = state.get("tool_iterations", 0)
        # Only loop if last batch was successful inspection (not all errors) and under limit
        has_success = any("result" in r for r in tool_results[-5:])
        if has_success and iterations < MAX_TOOL_ITERATIONS:
            return "agent"
    return "finish"


def route_after_verify(state: AgentState) -> str:
    """Route after verification.

    - If verification passed → go to finish
    - If verification failed and under repair limit → go to repair
    - If verification failed and at repair limit → go to finish
    """
    verification = state.get("verification_result", {})
    passed = verification.get("passed", True)

    if passed:
        return "finish"

    repair_attempts = state.get("repair_attempts", 0)
    if repair_attempts < MAX_REPAIR_ATTEMPTS:
        return "repair"

    return "finish"


def route_after_repair(state: AgentState) -> str:
    """After repair, always go back to agent for retry."""
    return "agent"
