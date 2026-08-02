# Context Builder Architecture

## Constraint: Minimum Storage Access

Every file stat, directory scan, or read from disk is considered expensive. The design must minimize them.

Allowed operations by cost:

```text
Cost 0 (free)      — in-memory data (chat history, last intent, cached values)
Cost 1 (cheap)     — 1 git command (git status, git ls-files, git log)
Cost 2 (moderate)  — 1 file read (reading a single file's content)
Cost 3 (expensive) — directory scan or multiple file stats
Cost 4 (forbidden) — recursive directory walk, repeated stat calls
```

The context builder must never exceed **Cost 2** for any single request, and typical requests should be **Cost 0-1**.

## Design

### Principle: Git is the primary data source

Instead of filesystem scanning, use git commands. A single git command returns more information than multiple stat calls.

### Principle: Read config files only once, cache forever

Project identity is determined on first request and never refreshed. No TTL, no re-reading.

### Principle: Zero file reads for intent

The intent parser call never includes file content. File content is only read when the agent actually needs to generate or modify code.

### Principle: No recursion, no walking

`os.walk()` and `Path.rglob()` are forbidden in context building. Use `git ls-files` instead.

## Data Model

```python
@dataclass(frozen=True)
class AgentContext:
    # Cost 0: from memory
    chat_history: list[dict[str, str]]
    last_intent: str
    last_target: str

    # Cost 1: from 1 git status call
    branch: str
    has_dirty_files: bool
    dirty_files: list[str]

    # Cost 1: from 1 git ls-files call (done once, cached)
    language: str           # python | javascript | typescript | rust | go | ruby | unknown
    has_test_config: bool
    has_lint_config: bool
    has_typecheck_config: bool
    tracked_files: list[str]
```

## Context Collection Flow

### Step 1: In-memory (Cost 0)

Every request, collected from MemoryStore with zero I/O:

```text
- Last 5 chat turns
- Last intent name
- Last target file
```

### Step 2: Git status (Cost 1)

One `git status --porcelain` call. Returns everything needed:

```text
branch
dirty files (staged + unstaged + untracked)
```

This replaces:
- Directory scans (forbidden)
- File stat calls (forbidden)
- Manual diff checks (expensive)

### Step 3: Project identity (Cost 1, cached forever)

One `git ls-files` call on first request. Result is cached in memory permanently.

From the list of tracked files, determine:

```text
language:
  if package.json in root       -> javascript / typescript
  if requirements.txt in root   -> python
  if Cargo.toml in root         -> rust
  if go.mod in root             -> go
  if Gemfile in root            -> ruby
  else                          -> unknown

test config:
  if pytest.ini / setup.cfg in list    -> has pytest
  if jest.config.* / .jest in list     -> has jest
  if Cargo.toml contains [dev-dependencies] -> has test config

lint config:
  if .eslintrc* / .ruff* / .flake8 in list -> has lint config

typecheck config:
  if tsconfig.json / mypy.ini / pyrightconfig.json in list -> has typecheck config
```

Why `git ls-files` instead of `os.path.exists()`:

```text
os.path.exists("package.json")  -> 1 stat call
os.path.exists("requirements.txt") -> 1 stat call
...                              -> N stat calls for N config files

git ls-files                     -> 1 process call
set(tracked).contains(...)       -> 0 I/O
```

Result: N stat calls replaced by 1 git call + in-memory lookup.

### Step 4: File state (Cost 2, only when needed)

Only when the agent needs to generate or modify code:

```text
1. Resolve file path (from tracked_files or dirty_files)
2. Read file content once
3. Truncate to 4000 chars
```

This is the only time file content is read. Never read a file "just in case."

## What is NOT Collected (to minimize storage access)

```text
Workspace file tree            = forbidden (recursive scan)
Directory structure            = forbidden (recursive scan)
Total file/directory counts    = forbidden (recursive scan)
Dependency list/versions       = forbidden (file reads × N)
File metadata (size, mtime)    = forbidden (stat calls)
Persistent task memory         = forbidden (file writes)
Full file content              = only for the target file, only when needed
```

## Prompt Format

```text
Project: <language> | branch: <branch>
Config: tests=<yes/no> lint=<yes/no> typecheck=<yes/no>
Dirty: <file1>, <file2>

Chat:
User: <last message>
Agent: <last response>

Target: <file>
```

This is injected into code generation calls only, never into intent parsing.

## Summary: Cost Per Request

| Request type | Git calls | File reads | Directory scans |
|---|---|---|---|
| "search for .py" | 0 (already cached) | 0 | 0 |
| "read config file" | 0 | 1 | 0 |
| "create hello.py" | 0 | 0 | 0 |
| "modify utils.py" | 0 | 1 (read existing) | 0 |
| "run tests" | 1 (git status) | 0 | 0 |
| First ever request | 2 (ls-files + status) | 0 | 0 |

Maximum storage access per request: **1 git command + 0-1 file reads**. Never more.
