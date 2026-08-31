"""Graph nodes — each function is a LangGraph node.

Nodes delegate to existing components (IntentParser, ContextBuilder, Planner,
Verifier, etc.) rather than reimplementing logic. This preserves all existing
working behavior while adding LangGraph orchestration.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from .config import (
    CONFIRMATION_MARKER,
    MAX_REPAIR_ATTEMPTS,
    READ_ONLY_INTENTS,
    WRITE_INTENTS,
)
from .state import AgentState

logger = logging.getLogger(__name__)


def _emit(event: dict) -> None:
    """Emit an event through the existing event system if active."""
    try:
        from ..events import emit as _emit_fn
        _emit_fn(event)
    except Exception:
        pass


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _get_deps(config: Optional[RunnableConfig]) -> dict[str, Any]:
    """Extract dependencies from LangGraph config."""
    if config is None:
        return {}
    return config.get("configurable", {})


# ─── Node: understand_request ────────────────────────────────────────


def understand_request(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Parse the user request and identify intent.

    Wraps existing IntentParser.parse() logic.
    """
    start = time.perf_counter()
    _emit({"type": "phase", "message": "Understanding your request…"})

    deps = _get_deps(config)
    user_message = state.get("user_message", "")
    conversation = state.get("conversation", [])

    # Build history from conversation state
    history = []
    for msg in conversation[-6:]:
        if isinstance(msg, dict):
            history.append(msg)

    # Get intent parser from config (injected at graph creation)
    intent_parser = deps.get("intent_parser")
    if intent_parser is None:
        raise RuntimeError("intent_parser not provided in config")

    intent = intent_parser.parse(user_message, history=history)

    intent_dict = {
        "name": intent.name,
        "target": intent.target or "",
        "args": intent.args or {},
        "confidence": intent.confidence,
        "requires_confirmation": intent.requires_confirmation,
        "reason": intent.reason or "",
        "raw_message": intent.raw_message,
    }

    # Determine path type
    intent_name = intent.name
    if intent_name in READ_ONLY_INTENTS:
        path_type = "read_only"
    elif intent_name in WRITE_INTENTS:
        path_type = "write"
    else:
        path_type = "write"  # default to write path for unknown intents

    _emit({"type": "intent", "name": intent.name, "target": intent.target or ""})
    logger.info(
        "Intent: %s target=%r confidence=%s path_type=%s",
        intent.name, intent.target, intent.confidence, path_type,
    )

    return {
        "intent": intent_dict,
        "intent_confidence": intent.confidence,
        "path_type": path_type,
        "execution_trace": [{
            "node": "understand_request",
            "intent": intent.name,
            "target": intent.target,
            "latency_ms": _elapsed_ms(start),
        }],
    }


# ─── Node: build_context ─────────────────────────────────────────────


def build_context(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Build repository context for the agent.

    Wraps existing ContextBuilder.build() logic.
    """
    start = time.perf_counter()
    _emit({"type": "phase", "message": "Building context…"})

    deps = _get_deps(config)
    user_message = state.get("user_message", "")
    intent = state.get("intent", {})
    intent_name = intent.get("name", "unknown") if intent else "unknown"

    context_builder = deps.get("context_builder")
    if context_builder is None:
        raise RuntimeError("context_builder not provided in config")

    # Only load project context for intents that need it
    should_load_context = intent_name in {"explain", "unknown", "analyze_project"}
    context = context_builder.build(user_message, load_context=should_load_context)

    context_dict = {
        "chat_history": context.chat_history,
        "similar_context": context.similar_context,
        "last_intent": context.last_intent,
        "last_target": context.last_target,
        "branch": context.branch,
        "has_dirty_files": context.has_dirty_files,
        "dirty_files": context.dirty_files,
        "language": context.language,
        "has_test_config": context.has_test_config,
        "has_lint_config": context.has_lint_config,
        "has_typecheck_config": context.has_typecheck_config,
        "session_summary": context.session_summary,
        "project_context": context.project_context,
    }

    # Build formatted context for prompt
    formatted = context_builder.format_for_prompt(context)

    # Retrieve relevant memory
    relevant_files = []
    if context.similar_context:
        for item in context.similar_context:
            meta = item.get("metadata", {})
            if meta.get("doc_type") == "file" and meta.get("path"):
                relevant_files.append(meta["path"])

    return {
        "context": context_dict,
        "relevant_files": relevant_files,
        "execution_trace": [{
            "node": "build_context",
            "language": context.language,
            "branch": context.branch,
            "has_dirty_files": context.has_dirty_files,
            "latency_ms": _elapsed_ms(start),
        }],
    }


# ─── Node: plan ──────────────────────────────────────────────────────


def plan(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Create an execution plan from the intent.

    Wraps existing Planner.create_plan() logic.
    """
    start = time.perf_counter()
    _emit({"type": "phase", "message": "Planning…"})

    deps = _get_deps(config)
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
            "latency_ms": _elapsed_ms(start),
        }],
    }


# ─── Node: agent ─────────────────────────────────────────────────────


def agent(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Main LLM reasoning node.

    Calls the LLM with the current state, context, and available tools.
    For read-only intents: generates a response directly.
    For write intents: decides which tools to call.
    """
    start = time.perf_counter()
    _emit({"type": "phase", "message": "Thinking…"})

    deps = _get_deps(config)
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
    prompts_dir = deps.get("prompts_dir", Path(__file__).parent.parent / "prompts")

    if llm is None:
        raise RuntimeError("llm not provided in config")

    # Build context block for prompt
    ctx_block = ""
    if context:
        ctx_block = f"\n\nProject context:\n{context.get('formatted', '')}"

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
            tool_results = state.get("tool_results", [])
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
            messages.append(HumanMessage(content=user_message))

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
                "error": str(error),
                "execution_trace": [{"node": "agent", "error": str(error), "latency_ms": _elapsed_ms(start)}],
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
                    "latency_ms": _elapsed_ms(start),
                }],
            }

        # No tool calls — direct response
        return {
            "final_response": response.content,
            "streaming_chunks": [response.content] if response.content else [],
            "execution_trace": [{"node": "agent", "latency_ms": _elapsed_ms(start)}],
        }

    # Read-only path or no tools — direct LLM response
    try:
        if path_type == "read_only" and hasattr(llm, 'bind_tools'):
            response = llm.invoke(messages)
        else:
            response = llm.invoke(messages)

        return {
            "final_response": response.content,
            "streaming_chunks": [response.content] if response.content else [],
            "execution_trace": [{"node": "agent", "latency_ms": _elapsed_ms(start)}],
        }
    except Exception as error:
        logger.warning("LLM call failed: %s", error)
        return {
            "final_response": f"LLM call failed: {error}",
            "error": str(error),
            "execution_trace": [{"node": "agent", "error": str(error), "latency_ms": _elapsed_ms(start)}],
        }


# ─── Node: tools ─────────────────────────────────────────────────────


def execute_tools(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Execute tool calls returned by the agent node.

    Runs each tool call and collects results.
    """
    start = time.perf_counter()
    _emit({"type": "phase", "message": "Executing tools…"})

    deps = _get_deps(config)
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

        _emit({"type": "action", "action": name, "target": str(args)[:200]})

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
            "latency_ms": _elapsed_ms(start),
        }],
    }


# ─── Node: verify ────────────────────────────────────────────────────


def verify(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Verify modifications by running compile checks, lint, and tests.

    Wraps existing Verifier.verify_file() logic.
    """
    start = time.perf_counter()
    _emit({"type": "phase", "message": "Verifying changes…"})

    deps = _get_deps(config)
    changed_files = state.get("changed_files", [])
    context = state.get("context")

    if not changed_files:
        return {
            "verification_result": {"passed": True, "message": "No files changed."},
        }

    verifier = deps.get("verifier")
    if verifier is None:
        return {
            "verification_result": {"passed": True, "message": "No verifier configured."},
        }

    # Rebuild AgentContext from dict if needed
    agent_context = None
    if context:
        try:
            from ..context import AgentContext
            agent_context = AgentContext(
                chat_history=context.get("chat_history", []),
                similar_context=context.get("similar_context", []),
                last_intent=context.get("last_intent", ""),
                last_target=context.get("last_target", ""),
                branch=context.get("branch", ""),
                has_dirty_files=context.get("has_dirty_files", False),
                dirty_files=context.get("dirty_files", []),
                language=context.get("language", "unknown"),
                has_test_config=context.get("has_test_config", False),
                has_lint_config=context.get("has_lint_config", False),
                has_typecheck_config=context.get("has_typecheck_config", False),
                session_summary=context.get("session_summary", ""),
                project_context=context.get("project_context", ""),
            )
        except Exception:
            pass

    root = deps.get("root", Path.cwd())
    all_passed = True
    results = []

    for file_path_str in changed_files:
        file_path = Path(file_path_str)
        if not file_path.is_absolute():
            file_path = root / file_path
        file_path = file_path.resolve()

        if not file_path.is_file():
            continue

        verification = verifier.verify_file(file_path, agent_context)
        passed = "compiles clean" in verification or "File written" in verification
        if not passed:
            all_passed = False
        results.append({
            "file": file_path_str,
            "passed": passed,
            "message": verification,
        })

    return {
        "verification_result": {
            "passed": all_passed,
            "results": results,
            "message": "\n".join(r["message"] for r in results),
        },
        "execution_trace": [{
            "node": "verify",
            "files_checked": len(results),
            "passed": all_passed,
            "latency_ms": _elapsed_ms(start),
        }],
    }


# ─── Node: repair ────────────────────────────────────────────────────


def repair(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Provide failure context for the agent to fix.

    This node doesn't do the actual repair — it updates state
    so the agent node gets the error context on the next iteration.
    """
    start = time.perf_counter()
    _emit({"type": "phase", "message": f"Repairing… (attempt {state.get('repair_attempts', 0) + 1}/{MAX_REPAIR_ATTEMPTS})"})

    verification = state.get("verification_result", {})
    attempts = state.get("repair_attempts", 0) + 1

    return {
        "repair_attempts": attempts,
        "execution_trace": [{
            "node": "repair",
            "attempt": attempts,
            "latency_ms": _elapsed_ms(start),
        }],
    }


# ─── Node: finish ────────────────────────────────────────────────────


def finish(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Produce the final response.

    Summarizes changes, test results, and any remaining issues.
    """
    start = time.perf_counter()
    _emit({"type": "phase", "message": "Finalizing…"})

    deps = _get_deps(config)
    final_response = state.get("final_response", "")
    changed_files = state.get("changed_files", [])
    verification = state.get("verification_result")
    tool_results = state.get("tool_results", [])
    repair_attempts = state.get("repair_attempts", 0)
    intent = state.get("intent", {})

    # If we already have a final_response (from read-only path or direct agent response)
    if final_response and not changed_files:
        _emit({"type": "done", "response": final_response})
        return {
            "execution_trace": [{"node": "finish", "latency_ms": _elapsed_ms(start)}],
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

    _emit({"type": "done", "response": response})

    return {
        "final_response": response,
        "execution_trace": [{"node": "finish", "latency_ms": _elapsed_ms(start)}],
    }
