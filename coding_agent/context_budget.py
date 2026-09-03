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
    "project": 3_000,     # project facts / ProjectContext.md
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


def budget_total() -> int:
    """Total token budget for assembled context."""
    try:
        return max(1, int(os.getenv("CODING_AGENT_CONTEXT_TOKENS", str(DEFAULT_TOTAL_TOKENS))))
    except ValueError:
        logger.warning("Invalid CODING_AGENT_CONTEXT_TOKENS, using %d", DEFAULT_TOTAL_TOKENS)
        return DEFAULT_TOTAL_TOKENS


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to ~max_tokens (char heuristic), marking truncation."""
    if estimate_tokens(text) <= max_tokens:
        return text
    char_budget = max(0, max_tokens * 4 - len(TRUNCATION_MARKER))
    return text[:char_budget] + TRUNCATION_MARKER


def assemble(sections: list[ContextSection], total_tokens: int = 0) -> str:
    """Assemble sections in priority order within the token budget.

    Each section is capped at min(its cap, remaining total). Empty bodies
    are skipped. Returns the joined prompt string.
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
        body = truncate_to_tokens(section.body, allow)
        chunk = f"{section.header}\n{body}" if section.header else body
        chunk_tokens = estimate_tokens(chunk)
        # Header itself can push us slightly over on tiny budgets; accept
        # the first section regardless so output is never empty.
        if not parts or used + chunk_tokens <= total + 50:
            parts.append(chunk)
            used += chunk_tokens
        else:
            break
    assembled = "\n".join(parts)
    logger.info("Assembled context: %d tokens across %d sections (budget %d)",
                estimate_tokens(assembled), len(parts), total)
    return assembled
