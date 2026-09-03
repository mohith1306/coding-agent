"""Shared token estimation utilities.

Single implementation of the ~4 chars/token heuristic so that
context budgeting (Phase 2), compaction, and prompt assembly all
agree on sizes. No behavior change: same formula as before.
"""


def estimate_tokens(text: str) -> int:
    """Heuristic token estimate (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)
