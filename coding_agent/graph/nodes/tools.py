"""Execute tools node — runs tool calls from agent."""

import logging
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from ..state import AgentState
from .helpers import emit, elapsed_ms, get_deps

logger = logging.getLogger(__name__)


def execute_tools(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Execute tool calls returned by the agent node.

    Runs each tool call and collects results.
    """
    start = time.perf_counter()
    emit({"type": "phase", "message": "Executing tools…"})

    deps = get_deps(config)
    tool_calls = state.get("tool_calls", [])
    tool_registry = deps.get("tool_registry")

    if not tool_calls:
        return {"tool_results": []}

    if tool_registry is None:
        return {"tool_results": [{"error": "tool_registry not provided"}]}

    tool_results = []
    changed_files = []

    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("args", {})
        call_id = tc.get("id", "")

        emit({"type": "action", "action": name, "target": str(args)[:200]})

        tool = tool_registry.get_tool_by_name(name)
        if tool is None:
            tool_results.append({
                "call_id": call_id,
                "name": name,
                "error": f"Unknown tool: {name}",
            })
            continue

        try:
            result = tool.invoke(args)
            tool_results.append({
                "call_id": call_id,
                "name": name,
                "args": args,
                "result": result,
            })
            # Track file changes
            if name == "write_file" and "path" in args:
                changed_files.append(args["path"])
            logger.info("Tool %s completed", name)
        except Exception as error:
            logger.warning("Tool %s failed: %s", name, error)
            tool_results.append({
                "call_id": call_id,
                "name": name,
                "args": args,
                "error": str(error),
            })

    return {
        "tool_results": tool_results,
        "changed_files": changed_files,
        "execution_trace": [{
            "node": "tools",
            "tools_executed": len(tool_results),
            "tools_failed": sum(1 for r in tool_results if "error" in r),
            "latency_ms": elapsed_ms(start),
        }],
    }
