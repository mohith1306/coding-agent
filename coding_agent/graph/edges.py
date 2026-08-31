"""Conditional edges — routing logic for the LangGraph state machine."""

from typing import Any

from .config import MAX_REPAIR_ATTEMPTS
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
    - Otherwise → go to finish
    """
    changed_files = state.get("changed_files", [])
    if changed_files:
        return "verify"
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
