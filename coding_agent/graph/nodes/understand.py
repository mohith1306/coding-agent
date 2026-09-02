"""Understand request node — parses user intent."""

import logging
import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from ..config import READ_ONLY_INTENTS, WRITE_INTENTS
from ..state import AgentState
from .helpers import emit, elapsed_ms, get_deps

logger = logging.getLogger(__name__)


def understand_request(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Parse the user request and identify intent.

    Wraps existing IntentParser.parse() logic.
    """
    start = time.perf_counter()
    emit({"type": "phase", "message": "Understanding your request…"})

    deps = get_deps(config)
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

    emit({"type": "intent", "name": intent.name, "target": intent.target or ""})
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
            "latency_ms": elapsed_ms(start),
        }],
    }
