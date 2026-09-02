"""Verify node — verifies code modifications."""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from ..state import AgentState
from .helpers import emit, elapsed_ms, get_deps

logger = logging.getLogger(__name__)


def verify(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:
    """Verify modifications by running compile checks, lint, and tests.

    Wraps existing Verifier.verify_file() logic.
    """
    start = time.perf_counter()
    emit({"type": "phase", "message": "Verifying changes…"})

    deps = get_deps(config)
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
            from ...context import AgentContext
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
            "latency_ms": elapsed_ms(start),
        }],
    }
