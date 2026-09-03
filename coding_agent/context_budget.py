"""Token-budgeted prompt assembly for agent context.

Replaces blind per-section truncation with a priority-ordered budget:
sections are filled in priority order, each capped individually and by
the remaining total. Highest-priority content (the file being edited)
is never starved by chat history.

Env:
    CODING_AGENT_CONTEXT_TOKENS  total budget for format_for_prompt
                                 output (default: 12000)
"""

import logging
import os
from dataclasses import dataclass, field

from .tokens import estimate_tokens


logger = logging.getLogger(__name__)

DEFAULT_TOTAL_TOKENS = 12_000

# Per-section caps (tokens). Sections listed in fill priority order.
SECTION_CAPS: dict[str, int] = {
    "identity": 300,      # language/branch/config/dirty — tiny, always first
    "target": 4_000,      # file being created/modified
    "files": 4_000,       # relevant file contents
    "project": 3_000,     # project facts from project_store
    "related": 1_500,     # retrieved similar turns/file events
    "history": 2_500,     # recent chat turns
    "summary": 1_500,     # compaction summary
}

TRUNCATION_MARKER = "\n[... truncated to fit context budget]"


@dataclass
class ContextSection:
    """One named chunk of prompt context."""

    name: str
    header: str
    body: str
    cap_tokens: int = 0  # 0 = use SECTION_CAPS default for name
    fence_aware: bool = False  # re-close ``` fences if truncation cuts one


def budget_total() -> int:
    """Total token budget for assembled context."""
    try:
        return max(1, int(os.getenv("CODING_AGENT_CONTEXT_TOKENS", str(DEFAULT_TOTAL_TOKENS))))
    except ValueError:
        logger.warning("Invalid CODING_AGENT_CONTEXT_TOKENS, using %d", DEFAULT_TOTAL_TOKENS)
        return DEFAULT_TOTAL_TOKENS


def truncate_to_tokens(text: str, max_tokens: int, fence_aware: bool = False) -> str:
    """Truncate text to fit max_tokens (char heuristic), marking truncation.

    Headers/separators/markers are the caller's responsibility to reserve
    via max_tokens. When fence_aware, space for a closing fence is
    reserved and an unbalanced cut is re-closed. Degenerate budgets
    (too small for even the marker) hard-cut without a marker so the
    bound always holds.
    """
    if estimate_tokens(text) <= max_tokens:
        return text
    reserve = TRUNCATION_MARKER + ("\n```" if fence_aware else "")
    if max_tokens * 4 <= len(reserve):
        out = text[:max_tokens * 4]
        if fence_aware and out.count("```") % 2 == 1:
            out = out[:out.rfind("```")]  # drop dangling opener (shorter, still in budget)
        return out
    out = text[:max_tokens * 4 - len(reserve)] + TRUNCATION_MARKER
    if fence_aware and out.count("```") % 2 == 1:
        out += "\n```"
    return out


def assemble(sections: list[ContextSection], total_tokens: int = 0) -> str:
    """Assemble sections in priority order within the token budget.

    Each section chunk (header + body together) is truncated to
    min(its cap, remaining total), so headers count against the budget
    and output never exceeds the total. Empty bodies are skipped.
    """
    total = total_tokens or budget_total()
    parts: list[str] = []
    used = 0
    for section in sections:
        if not section.body or used >= total:
            continue
        cap = section.cap_tokens or SECTION_CAPS.get(section.name, 1_000)
        allow = min(cap, total - used)
        if allow <= 0:
            continue
        chunk = f"{section.header}\n{section.body}" if section.header else section.body
        chunk = truncate_to_tokens(chunk, allow, fence_aware=section.fence_aware)
        parts.append(chunk)
        used += estimate_tokens(chunk)
    assembled = "\n".join(parts)
    logger.info("Assembled context: %d tokens across %d sections (budget %d)",
                estimate_tokens(assembled), len(parts), total)
    return assembled
