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


def normalize_target(root: Path, target: str) -> str:
    """Normalize an intent target to a canonical root-relative path.

    Accepts ./rel, nested, absolute in-root, and separator variants;
    returns "" when the target is not a file inside the root.
    """
    if not target:
        return ""
    resolved = resolve_within_root(root, target)
    if resolved is None:
        return ""
    try:
        return str(resolved.relative_to(root.resolve()))
    except ValueError:
        return ""


def collect_relevant_files(
    root: Path,
    paths: list[str],
    max_files: int = MAX_FILES,
) -> list[dict]:
    """Read bodies for candidate repo-relative paths.

    Returns [{path, content}] with root-relative canonical paths, in
    input order, capped at max_files. Deduplication happens AFTER
    resolution, so aliases (foo.py, ./foo.py, sub/../foo.py) collapse
    to one entry instead of consuming slots twice. Unreadable entries
    are skipped silently.
    """
    collected: list[dict] = []
    seen: set[str] = set()
    for rel in paths:
        if len(collected) >= max_files or not rel:
            continue
        resolved = resolve_within_root(root, rel)
        if resolved is None:
            continue
        canonical = str(resolved)
        if canonical in seen:
            continue
        seen.add(canonical)
        content = read_capped(resolved)
        if content is None:
            continue
        try:
            display = str(resolved.relative_to(root.resolve()))
        except ValueError:
            display = rel
        collected.append({"path": display, "content": content})
    logger.info("Collected %d files (%d unique candidates)", len(collected), len(seen))
    return collected
