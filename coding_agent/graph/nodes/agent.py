"""Agent node — main LLM reasoning."""

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from ..state import AgentState
from .helpers import emit, elapsed_ms, get_deps, get_prompts_dir

logger = logging.getLogger(__name__)


def agent(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Main LLM reasoning node.

    Calls the LLM with the current state, context, and available tools.
    For read-only intents: generates a response directly.
    For write intents: decides which tools to call.
    """
    start = time.perf_counter()
    emit({"type": "phase", "message": "Thinking…"})

    deps = get_deps(config)
    user_message = state.get("user_message", "")
    intent = state.get("intent", {})
    context = state.get("context")
    path_type = state.get("path_type", "write")
    conversation = state.get("conversation", [])
    confirmed = state.get("confirmed", False)

    intent_name = intent.get("name", "unknown") if intent else "unknown"
    intent_target = intent.get("target", "") if intent else ""

    llm = deps.get("llm")
    tool_registry = deps.get("tool_registry")
    prompts_dir = get_prompts_dir(config)

    if llm is None:
        raise RuntimeError("llm not provided in config")

    # Build context block for prompt
    ctx_block = ""
    if context:
        ctx_block = f"\n\nProject context:\n{context.get('formatted', '')}"

    # Build tool feedback for inspection loop (agent consuming previous tool results)
    tool_results = state.get("tool_results", [])
    tool_feedback = ""
    if tool_results and state.get("repair_attempts", 0) == 0 and path_type != "read_only":
        # Format recent tool results for the LLM to consume
        feedback_parts = []
        for tr in tool_results[-5:]:
            name = tr.get("name", "")
            res = tr.get("result", tr.get("error", ""))[:1500] if isinstance(tr.get("result", tr.get("error", "")), str) else str(tr.get("result", ""))
            feedback_parts.append(f"Tool {name} result:\n{res}")
        if feedback_parts:
            tool_feedback = "\n\nPrevious tool results:\n" + "\n---\n".join(feedback_parts) + "\n\nUse these results to decide your next edit."

    # Build messages
    messages = []

    if path_type == "read_only":
        # Read-only: use question prompt, no tools
        system_prompt = (prompts_dir / "question_prompt.md").read_text(encoding="utf-8")
        messages.append(SystemMessage(content=system_prompt + ctx_block))
        messages.append(HumanMessage(content=user_message))
    else:
        # Write path: use code generation or repair prompt depending on context
        if state.get("repair_attempts", 0) > 0:
            # This is a repair iteration
            repair_prompt = (prompts_dir / "repair_prompt.md").read_text(encoding="utf-8")
            verification = state.get("verification_result", {})
            error_msg = verification.get("message", "") if verification else ""
            last_result = tool_results[-1].get("result", "") if tool_results else ""

            messages.append(SystemMessage(content=repair_prompt + ctx_block))
            messages.append(HumanMessage(
                content=(
                    f"The previous attempt failed with this error:\n\n{error_msg}\n\n"
                    f"Tool output:\n{last_result}\n\n"
                    f"User request: {user_message}\n\n"
                    "Fix the issue and try again."
                )
            ))
        elif tool_feedback:
            # Inspection loop: LLM has already inspected files, now decide edits
            code_gen_prompt = (prompts_dir / "code_generation_prompt.md").read_text(encoding="utf-8")
            messages.append(SystemMessage(content=code_gen_prompt + ctx_block))
            messages.append(HumanMessage(content=f"User request: {user_message}\n{tool_feedback}"))
        elif intent_name in {"create_file", "create_files", "create_project", "modify_code"}:
            # Code generation
            code_gen_prompt = (prompts_dir / "code_generation_prompt.md").read_text(encoding="utf-8")
            messages.append(SystemMessage(content=code_gen_prompt + ctx_block))

            # Build user message with file context
            user_parts = [f"User request: {user_message}"]
            if intent_target:
                user_parts.append(f"Target: {intent_target}")
            if intent.get("args"):
                user_parts.append(f"Args: {json.dumps(intent['args'])}")

            # Add conversation history
            for msg in conversation[-4:]:
                if isinstance(msg, dict):
                    if msg.get("user"):
                        user_parts.append(f"Previous user: {msg['user'][:500]}")
                    if msg.get("agent"):
                        user_parts.append(f"Previous agent: {msg['agent'][:500]}")

            messages.append(HumanMessage(content="\n".join(user_parts)))
        else:
            # General question/plan
            system_prompt = (prompts_dir / "question_prompt.md").read_text(encoding="utf-8")
            messages.append(SystemMessage(content=system_prompt + ctx_block))
            messages.append(HumanMessage(content=user_message + tool_feedback))

    # For write intents, bind tools to the LLM
    if path_type == "write" and tool_registry and intent_name not in {"explain", "unknown"}:
        tools = tool_registry.get_tools()
        llm_with_tools = llm.bind_tools(tools)

        try:
            response = llm_with_tools.invoke(messages)
        except Exception as error:
            logger.warning("LLM call failed: %s", error)
            return {
                "final_response": f"LLM call failed: {error}",
                "tool_calls": [],
                "error": str(error),
                "execution_trace": [{"node": "agent", "error": str(error), "latency_ms": elapsed_ms(start)}],
            }

        # Process tool calls
        tool_calls = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_calls.append({
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                    "id": tc.get("id", ""),
                })

        # If there are tool calls, return them for the tools node
        if tool_calls:
            return {
                "tool_calls": tool_calls,
                "streaming_chunks": [response.content] if response.content else [],
                "execution_trace": [{
                    "node": "agent",
                    "tool_calls": len(tool_calls),
                    "latency_ms": elapsed_ms(start),
                }],
            }

        # No tool calls — direct response (clear stale tool_calls)
        return {
            "final_response": response.content,
            "tool_calls": [],
            "streaming_chunks": [response.content] if response.content else [],
            "execution_trace": [{"node": "agent", "latency_ms": elapsed_ms(start)}],
        }

    # Read-only path or no tools — direct LLM response
    try:
        if path_type == "read_only" and hasattr(llm, 'bind_tools'):
            response = llm.invoke(messages)
        else:
            response = llm.invoke(messages)

        return {
            "final_response": response.content,
            "tool_calls": [],
            "streaming_chunks": [response.content] if response.content else [],
            "execution_trace": [{"node": "agent", "latency_ms": elapsed_ms(start)}],
        }
    except Exception as error:
        logger.warning("LLM call failed: %s", error)
        return {
            "final_response": f"LLM call failed: {error}",
            "tool_calls": [],
            "error": str(error),
            "execution_trace": [{"node": "agent", "error": str(error), "latency_ms": elapsed_ms(start)}],
        }
