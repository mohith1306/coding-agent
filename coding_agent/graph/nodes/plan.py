"""Plan node — creates execution plan."""

import logging
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from ..state import AgentState
from .helpers import emit, elapsed_ms, get_deps

logger = logging.getLogger(__name__)


def plan(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Create an execution plan from the intent.

    Wraps existing Planner.create_plan() logic.
    """
    start = time.perf_counter()
    emit({"type": "phase", "message": "Planning…"})

    deps = get_deps(config)
    intent = state.get("intent", {})
    intent_name = intent.get("name", "unknown") if intent else "unknown"
    target = intent.get("target", "") if intent else ""
    raw_message = state.get("user_message", "")

    planner = deps.get("planner")
    if planner is None:
        raise RuntimeError("planner not provided in config")

    plan_obj = planner.create_plan(raw_message, target)

    return {
        "plan": plan_obj.steps,
        "execution_trace": [{
            "node": "plan",
            "steps": plan_obj.steps,
            "executable": plan_obj.executable,
            "latency_ms": elapsed_ms(start),
        }],
    }
