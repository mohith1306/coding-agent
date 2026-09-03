"""Graph configuration constants."""

import os

MAX_REPAIR_ATTEMPTS = int(os.getenv("CODING_AGENT_MAX_REPAIR_ATTEMPTS", "3"))
MAX_TOOL_ITERATIONS = int(os.getenv("CODING_AGENT_MAX_TOOL_ITERATIONS", "5"))

READ_ONLY_INTENTS = frozenset({
    "search_files",
    "read_file",
    "explain",
    "unknown",
    "analyze_project",
    "list_tasks",
    "recall",
    "list_issues",
    "list_prs",
})

WRITE_INTENTS = frozenset({
    "create_file",
    "create_files",
    "create_project",
    "modify_code",
    "delete_file",
    "run_command",
    "run_tests",
    "commit",
    "push",
    "commit_and_push",
    "plan",
    "remember",
    "create_pr",
    "create_issue",
    "add_comment",
    "close_issue",
    "merge_pr",
    "create_branch",
    "delete_branch",
    "merge_branch",
    "auto_fix",
})

CONFIRMATION_MARKER = "CONFIRMATION_REQUIRED"

PROJECT_IDENTITY_CACHE = None
TRACKED_FILES_CACHE = None
