"""Repository utilities: clone, checkout, diff capture."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def clone_repo(repo_url: str, commit: str, workdir: Path) -> Path:
    """Clone a repo at a specific commit into a temp directory.

    Returns the path to the cloned repository.
    """
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    repo_path = workdir / repo_name

    logger.info("Cloning %s @ %s → %s", repo_url, commit[:12], repo_path)

    subprocess.run(
        ["git", "clone", "--quiet", repo_url, str(repo_path)],
        check=True,
        capture_output=True,
        timeout=120,
    )

    subprocess.run(
        ["git", "checkout", "--quiet", commit],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
        timeout=30,
    )

    return repo_path


def get_patch(repo_path: Path) -> str:
    """Capture the unified diff of all changes in the repo."""
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout


def get_staged_patch(repo_path: Path) -> str:
    """Capture staged changes (if agent uses git add)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout


def get_full_patch(repo_path: Path) -> str:
    """Get all changes (unstaged + staged)."""
    unstaged = get_patch(repo_path)
    staged = get_staged_patch(repo_path)
    return unstaged or staged


def cleanup_repo(repo_path: Path) -> None:
    """Remove a cloned repo directory."""
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)
        logger.debug("Cleaned up %s", repo_path)


def get_changed_files(repo_path: Path) -> list[str]:
    """List files changed in the working tree."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]
