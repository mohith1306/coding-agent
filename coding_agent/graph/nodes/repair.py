"""Repair node — provides failure context for agent to fix."""

import logging
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from ..config import MAX_REPAIR_ATTEMPTS
from ..state import AgentState
from .helpers import emit, elapsed_ms, get_deps

logger = logging.getLogger(__name__)


def repair(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Provide failure context for the agent to fix.

    This node doesn't do the actual repair — it updates state
    so the agent node gets the error context on the next iteration.
    """
    start = time.perf_counter()
    emit({"type": "phase", "message": f"Repairing… (attempt {state.get('repair_attempts', 0) + 1}/{MAX_REPAIR_ATTEMPTS})"})

    verification = state.get("verification_result", {})
    attempts = state.get("repair_attempts", 0) + 1

    return {
        "repair_attempts": attempts,
        "execution_trace": [{
            "node": "repair",
            "attempt": attempts,
            "latency_ms": elapsed_ms(start),
        }],
    }
