"""AgentState — typed state shared across all LangGraph nodes."""

import operator
from typing import Annotated, Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """Typed state for the coding agent LangGraph runtime.

    Fields are grouped by responsibility. Lists use Annotated reducers
    so that multiple nodes can append without overwriting.
    """

    # ── Session ──────────────────────────────────────────────────────
    session_id: str
    project_id: str

    # ── Input ────────────────────────────────────────────────────────
    user_message: str
    confirmed: bool

    # ── Intent ───────────────────────────────────────────────────────
    intent: Optional[dict[str, Any]]
    intent_confidence: Optional[float]

    # ── Context ──────────────────────────────────────────────────────
    current_file: Optional[str]
    selected_code: Optional[str]
    conversation: Annotated[list[dict[str, Any]], operator.add]
    relevant_files: Annotated[list[str], operator.add]
    context: Optional[dict[str, Any]]

    # ── Planning ─────────────────────────────────────────────────────
    plan: Annotated[list[str], operator.add]
    path_type: Optional[str]  # "read_only" | "write"

    # ── Execution ────────────────────────────────────────────────────
    tool_calls: list[dict[str, Any]]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    changed_files: Annotated[list[str], operator.add]
    tool_iterations: int

    # ── Verification ─────────────────────────────────────────────────
    verification_result: Optional[dict[str, Any]]
    test_result: Optional[dict[str, Any]]
    repair_attempts: int

    # ── Control ──────────────────────────────────────────────────────
    awaiting_confirmation: bool
    pending_confirmation_type: Optional[str]
    pending_confirmation_action: Optional[str]
    pending_confirmation_target: Optional[str]
    pending_confirmation_preview: Optional[str]

    # ── Output ───────────────────────────────────────────────────────
    final_response: Optional[str]

    # ── Observability ────────────────────────────────────────────────
    token_count: int
    execution_trace: Annotated[list[dict[str, Any]], operator.add]
    streaming_chunks: Annotated[list[str], operator.add]
    error: Optional[str]
    model_name: Optional[str]
    latency_ms: float
