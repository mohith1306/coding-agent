"""Shared utilities for graph nodes."""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


def emit(event: dict) -> None:
    """Emit an event through the existing event system if active."""
    try:
        from ...events import emit as _emit_fn
        _emit_fn(event)
    except Exception:
        pass


def elapsed_ms(start: float) -> float:
    """Calculate elapsed time in milliseconds."""
    return round((time.perf_counter() - start) * 1000, 1)


def get_deps(config: Optional[RunnableConfig]) -> dict[str, Any]:
    """Extract dependencies from LangGraph config."""
    if config is None:
        return {}
    return config.get("configurable", {})


def get_prompts_dir(config: Optional[RunnableConfig]) -> Path:
    """Get prompts directory from config or default."""
    deps = get_deps(config)
    return deps.get("prompts_dir", Path(__file__).parent.parent.parent / "prompts")
