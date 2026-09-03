"""Finish node — produces final response."""

import logging
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from ..state import AgentState
from .helpers import emit, elapsed_ms, get_deps

logger = logging.getLogger(__name__)


def finish(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Produce the final response.

    Summarizes changes, test results, and any remaining issues.
    """
    start = time.perf_counter()
    emit({"type": "phase", "message": "Finalizing…"})

    deps = get_deps(config)
    final_response = state.get("final_response", "")
    changed_files = state.get("changed_files", [])
    verification = state.get("verification_result")
    tool_results = state.get("tool_results", [])
    repair_attempts = state.get("repair_attempts", 0)
    intent = state.get("intent", {})

    # If we already have a final_response (from read-only path or direct agent response)
    if final_response and not changed_files:
        emit({"type": "done", "response": final_response})
        return {
            "execution_trace": [{"node": "finish", "latency_ms": elapsed_ms(start)}],
        }

    # Build response for write path
    parts = []

    if changed_files:
        parts.append(f"**Changed files:** {', '.join(changed_files)}")

    if verification:
        ver_passed = verification.get("passed", False)
        ver_message = verification.get("message", "")
        if ver_passed:
            parts.append("**Verification:** All checks passed")
        else:
            parts.append(f"**Verification:**\n{ver_message}")

    if repair_attempts > 0:
        if verification and verification.get("passed"):
            parts.append(f"*Repaired after {repair_attempts} attempt(s)*")
        else:
            parts.append(f"*Could not repair after {repair_attempts} attempt(s)*")

    # Include tool results for non-file tools
    for tr in tool_results:
        if tr.get("name") not in {"read_file", "write_file", "list_files"}:
            result = tr.get("result", tr.get("error", ""))
            if result:
                parts.append(f"**{tr['name']}:** {result[:1000]}")

    if not parts:
        parts.append("Task completed.")

    response = "\n\n".join(parts)

    # Record memory
    memory = deps.get("memory")
    if memory:
        try:
            intent_name = intent.get("name", "unknown") if intent else "unknown"
            target = intent.get("target", "") if intent else ""
            memory.add_turn(
                user_message=state.get("user_message", ""),
                agent_response=response,
                intent=intent_name,
                target=target,
            )
            for cf in changed_files:
                memory.add_file_event(cf, "modified")
        except Exception as error:
            logger.warning("Memory recording failed: %s", error)

    emit({"type": "done", "response": response})

    return {
        "final_response": response,
        "execution_trace": [{"node": "finish", "latency_ms": elapsed_ms(start)}],
    }
