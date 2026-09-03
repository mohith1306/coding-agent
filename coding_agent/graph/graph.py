"""LangGraph StateGraph — the central execution engine.

Assembles nodes and edges into a compiled graph that owns agent orchestration.
"""

import logging
import time
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Optional

logger = logging.getLogger(__name__)


class AgentGraph:
    """Wraps a compiled LangGraph StateGraph.

    Provides:
    - invoke(): synchronous single-shot execution
    - astream_events(): async streaming execution
    - Configurable injection of dependencies (LLM, tools, context, etc.)
    """

    def __init__(
        self,
        root: Path,
        llm=None,
        tool_registry=None,
        intent_parser=None,
        context_builder=None,
        planner=None,
        verifier=None,
        memory=None,
    ) -> None:
        self.root = root.resolve()
        self._deps = {
            "root": self.root,
            "llm": llm,
            "tool_registry": tool_registry,
            "intent_parser": intent_parser,
            "context_builder": context_builder,
            "planner": planner,
            "verifier": verifier,
            "memory": memory,
            "prompts_dir": Path(__file__).parent.parent / "prompts",
        }
        self._graph = self._build_graph()

    def _build_graph(self):
        """Build and compile the LangGraph StateGraph."""
        from langgraph.graph import END, StateGraph

        from .edges import (
            route_after_agent,
            route_after_plan,
            route_after_repair,
            route_after_tools,
            route_after_verify,
        )
        from .nodes import (
            agent,
            build_context,
            execute_tools,
            finish,
            plan,
            repair,
            understand_request,
            verify,
        )
        from .state import AgentState

        graph = StateGraph(AgentState)

        # Add nodes
        graph.add_node("understand_request", understand_request)
        graph.add_node("build_context", build_context)
        graph.add_node("plan", plan)
        graph.add_node("agent", agent)
        graph.add_node("tools", execute_tools)
        graph.add_node("verify", verify)
        graph.add_node("repair", repair)
        graph.add_node("finish", finish)

        # Entry point
        graph.set_entry_point("understand_request")

        # Linear edges
        graph.add_edge("understand_request", "build_context")
        graph.add_edge("build_context", "plan")

        # Conditional: plan → agent (always, but path_type is set)
        graph.add_conditional_edges(
            "plan",
            route_after_plan,
            {"agent": "agent"},
        )

        # Conditional: agent → tools | finish
        graph.add_conditional_edges(
            "agent",
            route_after_agent,
            {"tools": "tools", "finish": "finish"},
        )

        # Conditional: tools → verify | agent (inspection loop) | finish
        graph.add_conditional_edges(
            "tools",
            route_after_tools,
            {"verify": "verify", "agent": "agent", "finish": "finish"},
        )

        # Conditional: verify → finish | repair
        graph.add_conditional_edges(
            "verify",
            route_after_verify,
            {"finish": "finish", "repair": "repair"},
        )

        # Conditional: repair → agent
        graph.add_conditional_edges(
            "repair",
            route_after_repair,
            {"agent": "agent"},
        )

        # End
        graph.add_edge("finish", END)

        return graph.compile()

    def invoke(self, user_message: str, confirmed: bool = False, session_id: str = "") -> dict[str, Any]:
        """Run the graph synchronously to completion.

        Args:
            user_message: The user's input.
            confirmed: Whether the user has confirmed a pending action.
            session_id: Optional session identifier.

        Returns:
            The final state dictionary.
        """
        from .state import AgentState

        initial_state: AgentState = {
            "session_id": session_id or "default",
            "project_id": str(self.root),
            "user_message": user_message,
            "confirmed": confirmed,
            "intent": None,
            "intent_confidence": None,
            "current_file": None,
            "selected_code": None,
            "conversation": [],
            "relevant_files": [],
            "context": None,
            "plan": [],
            "path_type": None,
            "tool_calls": [],
            "tool_results": [],
            "changed_files": [],
            "tool_iterations": 0,
            "verification_result": None,
            "test_result": None,
            "repair_attempts": 0,
            "awaiting_confirmation": False,
            "pending_confirmation_type": None,
            "pending_confirmation_action": None,
            "pending_confirmation_target": None,
            "pending_confirmation_preview": None,
            "final_response": None,
            "token_count": 0,
            "execution_trace": [],
            "streaming_chunks": [],
            "error": None,
            "model_name": None,
            "latency_ms": 0.0,
        }

        start = time.perf_counter()
        try:
            # LangGraph expects deps in {"configurable": {...}} format
            graph_config = {"configurable": self._deps}
            result = self._graph.invoke(initial_state, config=graph_config)
            result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "Graph completed in %.1fms (path=%s, repair_attempts=%d)",
                result["latency_ms"],
                result.get("path_type"),
                result.get("repair_attempts", 0),
            )
            return result
        except Exception as error:
            latency = round((time.perf_counter() - start) * 1000, 1)
            logger.exception("Graph execution failed after %.1fms", latency)
            return {
                "final_response": f"Agent error: {error}",
                "error": str(error),
                "latency_ms": latency,
            }

    async def ainvoke(self, user_message: str, confirmed: bool = False, session_id: str = "") -> dict[str, Any]:
        """Run the graph asynchronously to completion."""
        from .state import AgentState

        initial_state: AgentState = {
            "session_id": session_id or "default",
            "project_id": str(self.root),
            "user_message": user_message,
            "confirmed": confirmed,
            "intent": None,
            "intent_confidence": None,
            "current_file": None,
            "selected_code": None,
            "conversation": [],
            "relevant_files": [],
            "context": None,
            "plan": [],
            "path_type": None,
            "tool_calls": [],
            "tool_results": [],
            "changed_files": [],
            "tool_iterations": 0,
            "verification_result": None,
            "test_result": None,
            "repair_attempts": 0,
            "awaiting_confirmation": False,
            "pending_confirmation_type": None,
            "pending_confirmation_action": None,
            "pending_confirmation_target": None,
            "pending_confirmation_preview": None,
            "final_response": None,
            "token_count": 0,
            "execution_trace": [],
            "streaming_chunks": [],
            "error": None,
            "model_name": None,
            "latency_ms": 0.0,
        }

        start = time.perf_counter()
        try:
            # LangGraph expects deps in {"configurable": {...}} format
            graph_config = {"configurable": self._deps}
            result = await self._graph.ainvoke(initial_state, config=graph_config)
            result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
            return result
        except Exception as error:
            latency = round((time.perf_counter() - start) * 1000, 1)
            logger.exception("Async graph execution failed after %.1fms", latency)
            return {
                "final_response": f"Agent error: {error}",
                "error": str(error),
                "latency_ms": latency,
            }

    def stream_events(self, user_message: str, confirmed: bool = False, session_id: str = "") -> Iterator[dict]:
        """Stream graph execution events synchronously.

        Yields normalized event dicts compatible with the existing frontend event model:
        - {"type": "phase", "message": "..."}
        - {"type": "intent", "name": "...", "target": "..."}
        - {"type": "action", "action": "...", "target": "..."}
        - {"type": "chunk", "text": "..."}
        - {"type": "confirmation", "action": "...", "target": "..."}
        - {"type": "done", "response": "..."}
        - {"type": "error", "message": "..."}
        """
        from ..events import emit as _emit_fn, set_event_sink, reset_event_sink
        import queue

        events: queue.Queue = queue.Queue()

        def event_sink(event: dict) -> None:
            events.put_nowait(event)

        token = set_event_sink(event_sink)
        try:
            # Run graph — nodes will emit events through the sink
            result = self.invoke(user_message, confirmed=confirmed, session_id=session_id)

            # Yield all accumulated events
            while not events.empty():
                try:
                    yield events.get_nowait()
                except queue.Empty:
                    break

            # Ensure we yield the final response
            final_response = result.get("final_response", "")
            if final_response:
                if not any(
                    e.get("type") == "done"
                    for e in list(events.queue)
                ):
                    yield {"type": "done", "response": final_response}
        except Exception as error:
            yield {"type": "error", "message": str(error)}
        finally:
            reset_event_sink(token)

    def close(self) -> None:
        """Clean up resources."""
        tool_registry = self._deps.get("tool_registry")
        if tool_registry:
            try:
                tool_registry.close()
            except Exception:
                pass
