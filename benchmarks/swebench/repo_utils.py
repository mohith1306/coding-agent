"""Repository utilities: clone, checkout, diff capture."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def clone_repo(repo_url: str, commit: str, workdir: Path) -> Path:
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    repo_path = workdir / repo_name
    subprocess.run(["git", "clone", "--quiet", repo_url, str(repo_path)],
                   check=True, capture_output=True, timeout=120)
    subprocess.run(["git", "checkout", "--quiet", commit],
                   cwd=str(repo_path), check=True, capture_output=True, timeout=30)
    return repo_path


def get_full_patch(repo_path: Path) -> str:
    result = subprocess.run(["git", "diff", "HEAD"], cwd=str(repo_path),
                           capture_output=True, text=True, timeout=30)
    return result.stdout


def get_changed_files(repo_path: Path) -> list[str]:
    result = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=str(repo_path),
                           capture_output=True, text=True, timeout=10)
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def cleanup_repo(repo_path: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)
