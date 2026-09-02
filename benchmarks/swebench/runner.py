"""SWE-bench instance runner: feeds an issue to the coding agent, captures the patch."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .providers import ProviderRotation
from .repo_utils import cleanup_repo, clone_repo, get_full_patch, get_changed_files

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_issue_prompt(instance: dict[str, Any]) -> str:
    repo = instance.get("repo", "")
    issue = instance.get("problem_statement", "")
    hints = instance.get("hints_text", "")
    parts = [f"Repository: {repo}", f"Issue: {issue}"]
    if hints:
        parts.append(f"Hints: {hints}")
    parts.append(
        "\nFix this issue. Read the relevant files first, understand the problem, "
        "then make the necessary code changes. Do not run tests — just fix the code."
    )
    return "\n\n".join(parts)


def run_instance(
    instance: dict[str, Any],
    provider: ProviderRotation,
    tmpdir: Path,
    max_turns: int = 15,
) -> dict[str, Any]:
    from coding_agent.agent import CodingAgent
    from coding_agent.intent import IntentParser

    instance_id = instance["instance_id"]
    repo_url = f"https://github.com/{instance['repo']}.git"
    base_commit = instance["base_commit"]

    result: dict[str, Any] = {
        "instance_id": instance_id,
        "model_patch": "",
        "model_name_or_path": "coding-agent",
        "status": "error",
        "error": "",
        "turns": 0,
        "latency_s": 0.0,
    }

    start = time.time()
    repo_path: Optional[Path] = None

    try:
        repo_path = clone_repo(repo_url, base_commit, tmpdir)

        original_call = IntentParser._call_openrouter_raw

        def patched_call(self: Any, system_prompt: str, user_message: str, json_mode: bool = False) -> str:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            return provider.chat(messages)

        IntentParser._call_openrouter_raw = patched_call  # type: ignore

        agent = CodingAgent(memory=None, root=repo_path)
        user_message = _build_issue_prompt(instance)

        final_response = ""
        for turn in range(max_turns):
            response = agent.handle(user_message, confirmed=True)
            final_response = response

            if not response or "CONFIRMATION_REQUIRED" in response:
                break

            if any(kw in response.lower() for kw in ["i can", "tell me", "what content", "which file"]):
                user_message = "Just implement the fix directly. Don't ask questions — read the code and make the changes."
            else:
                user_message = (
                    "Good. Now make sure all relevant changes are made. "
                    "If you need to modify more files, do so. When done, just say 'done'."
                )
            result["turns"] = turn + 1

        patch = get_full_patch(repo_path)
        result["model_patch"] = patch
        result["changed_files"] = get_changed_files(repo_path)
        result["status"] = "success" if patch else "no_changes"
        result["response_preview"] = final_response[:500]

    except Exception as e:
        result["error"] = str(e)[:1000]
        logger.error("Instance %s failed: %s", instance_id, str(e)[:300])

    finally:
        try:
            IntentParser._call_openrouter_raw = original_call  # type: ignore
        except Exception:
            pass
        if repo_path:
            cleanup_repo(repo_path)

    result["latency_s"] = round(time.time() - start, 1)
    return result
