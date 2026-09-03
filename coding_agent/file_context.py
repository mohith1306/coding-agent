"""Relevant-file content collection for prompt injection.

Reads the bodies of files the agent is likely to need (intent target +
recently touched files from memory) so the LLM sees code without an
extra tool round-trip. Safety rules:

- Paths are resolved against the project root; escapes are skipped.
- Binary files (null byte in probe) are skipped.
- Files larger than MAX_FILE_BYTES are skipped (listed, not inlined).
- Bodies are capped at MAX_FILE_CHARS with a truncation marker.
- At most MAX_FILES files, deduplicated, target first.
"""

import logging
from pathlib import Path


logger = logging.getLogger(__name__)

MAX_FILES = 5
MAX_FILE_BYTES = 100_000
MAX_FILE_CHARS = 6_000

TRUNCATION_MARKER = "\n[... file truncated]"


def is_binary(path: Path, probe_bytes: int = 8_192) -> bool:
    """Heuristic binary check: null byte in the first chunk."""
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(probe_bytes)
    except OSError:
        return True


def resolve_within_root(root: Path, rel: str) -> Path | None:
    """Resolve a repo-relative path, returning None on escape/missing."""
    try:
        candidate = (root / rel).resolve()
        candidate.relative_to(root.resolve())
    except (ValueError, RuntimeError, OSError):
        return None
    return candidate if candidate.is_file() else None


def read_capped(path: Path) -> str | None:
    """Read a file body capped at MAX_FILE_CHARS; None when skipped."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            logger.info("Skipping oversize file for context: %s", path)
            return None
        if is_binary(path):
            logger.info("Skipping binary file for context: %s", path)
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        logger.warning("Could not read %s for context: %s", path, error)
        return None
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    return text


def collect_relevant_files(
    root: Path,
    paths: list[str],
    max_files: int = MAX_FILES,
) -> list[dict]:
    """Read bodies for candidate repo-relative paths.

    Returns [{path, content}] for readable files (in input order,
    deduplicated, capped at max_files). Unreadable entries are skipped
    silently — absence from the list signals the skip.
    """
    collected: list[dict] = []
    seen: set[str] = set()
    for rel in paths:
        if len(collected) >= max_files or not rel or rel in seen:
            continue
        seen.add(rel)
        resolved = resolve_within_root(root, rel)
        if resolved is None:
            continue
        content = read_capped(resolved)
        if content is None:
            continue
        try:
            display = str(resolved.relative_to(root.resolve()))
        except ValueError:
            display = rel
        collected.append({"path": display, "content": content})
    logger.info("Collected %d/%d relevant files for context", len(collected), len(seen))
    return collected
