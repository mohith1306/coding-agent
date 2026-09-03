"""Build context node — builds repository context."""

import logging
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from ..state import AgentState
from .helpers import emit, elapsed_ms, get_deps

logger = logging.getLogger(__name__)


def build_context(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Build repository context for the agent.

    Wraps existing ContextBuilder.build() logic.
    """
    start = time.perf_counter()
    emit({"type": "phase", "message": "Building context…"})

    deps = get_deps(config)
    user_message = state.get("user_message", "")
    intent = state.get("intent", {})
    intent_name = intent.get("name", "unknown") if intent else "unknown"

    context_builder = deps.get("context_builder")
    if context_builder is None:
        raise RuntimeError("context_builder not provided in config")

    intent_target = intent.get("target", "") if intent else ""
    context = context_builder.build(
        user_message,
        intent_name=intent_name,
        intent_target=intent_target,
    )

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
        "target_path": context.target_path,
        "relevant_file_contents": context.relevant_file_contents,
    }

    # Build formatted context for prompt
    formatted = context_builder.format_for_prompt(context)
    context_dict["formatted"] = formatted

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
            "latency_ms": elapsed_ms(start),
        }],
    }
