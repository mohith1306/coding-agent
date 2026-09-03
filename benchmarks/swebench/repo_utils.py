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
    patch = result.stdout

    # Include untracked files (git diff HEAD excludes them)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=str(repo_path), capture_output=True, text=True, timeout=10,
    )
    for rel in [f.strip() for f in untracked.stdout.splitlines() if f.strip()]:
        fpath = repo_path / rel
        if not fpath.is_file():
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Generate a Git-compatible patch header for the new file
        lines = content.splitlines()
        patch += f"\ndiff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n"
        patch += f"@@ -0,0 +1,{len(lines)} @@\n"
        for line in lines:
            patch += f"+{line}\n"
    return patch


def get_changed_files(repo_path: Path) -> list[str]:
    result = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=str(repo_path),
                           capture_output=True, text=True, timeout=10)
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    # Also include untracked files
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=str(repo_path), capture_output=True, text=True, timeout=10,
    )
    for f in untracked.stdout.splitlines():
        f = f.strip()
        if f and f not in files:
            files.append(f)
    return files


def cleanup_repo(repo_path: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)
