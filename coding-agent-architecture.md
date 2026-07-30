# Coding Agent Architecture

## Overview

This architecture defines a coding agent that can understand a user request, inspect a codebase, make safe code changes, verify the result, and preserve useful context for future tasks.

The core agent loop is:

```text
Understand -> Plan -> Act -> Verify -> Respond -> Remember
```

## High-Level Flow

```text
User Question
  -> Context Builder
  -> Intent Classifier
  -> Planner
  -> Permission Gate
  -> Tool Router
      -> File Search
      -> File Reader
      -> File Editor
      -> Terminal Sandbox
      -> Git Context
      -> GitHub Integration
      -> File Generator
  -> Verifier
      -> Tests
      -> Lint
      -> Typecheck
      -> Diff Review
  -> Response Generator
  -> Memory Store
```

## Main Components

### 1. User Question

The starting point of the system. The user can ask the agent to explain code, fix bugs, add features, generate files, run tests, interact with GitHub, or inspect the project.

### 2. Context Builder

Collects all relevant context before the agent decides what to do.

Sources include:

- Current user message
- Previous chat history
- Project files
- Documentation
- Git status and diffs
- Existing task memory
- User preferences

### 3. Intent Classifier

Determines what type of task the user is asking for.

Example intents:

- Explain code
- Search codebase
- Fix bug
- Add feature
- Refactor code
- Generate documentation
- Run tests
- Create GitHub issue or PR
- Review code

### 4. Planner

Creates a short execution plan before using tools.

Example plan:

```text
1. Inspect relevant files
2. Identify the required change
3. Edit the smallest necessary files
4. Run verification commands
5. Summarize the result
```

The planner should keep the plan minimal and update it when new information is discovered.

### 5. Permission Gate

Controls which actions the agent is allowed to perform automatically and which actions require user approval.

Safe actions:

- Read files
- Search files
- Inspect Git status
- Run non-destructive test commands
- Generate local documentation files

Approval-required actions:

- Delete files
- Modify secret or environment files
- Install packages
- Run destructive shell commands
- Commit code
- Push code
- Create pull requests
- Change permissions
- Access external services with credentials

### 6. Tool Router

Routes the planned action to the correct tool.

The previous `Heaven Gates` component should be renamed to `Tool Router` or `Agent Controller` because this component controls which capability is used next.

## Tool Layer

### File Search

Used to discover files and references in the codebase.

Capabilities:

- Glob search
- Regex search
- Symbol search
- Dependency lookup

### File Reader

Reads project files without modifying them.

Used for:

- Understanding code
- Reading configs
- Reviewing docs
- Inspecting tests

### File Editor

Applies code changes to existing files.

Rules:

- Make the smallest correct change
- Preserve existing style
- Avoid unrelated edits
- Never overwrite user changes without approval

### Terminal Sandbox

Runs shell commands in a controlled environment.

Used for:

- Tests
- Build commands
- Lint commands
- Type checks
- Package scripts

The sandbox should block or request approval for destructive commands.

### Git Context

Provides repository state to the agent.

Useful commands:

```text
git status
git diff
git log
git branch
```

This helps the agent avoid overwriting user work and summarize exactly what changed.

### GitHub Integration

Optional integration for remote collaboration.

Capabilities:

- Read issues
- Read pull requests
- Create issues
- Create pull requests
- Comment on PRs
- Check CI status

Any write operation should require user approval.

### File Generator

Generates new files when needed.

Examples:

- Markdown documentation
- PDF exports
- Reports
- Config templates
- Generated code files

## Verifier

The verifier checks whether the action succeeded before the final response is returned.

Verification methods:

- Run tests
- Run lint
- Run typecheck
- Run build
- Inspect generated diff
- Confirm expected files changed
- Check command output for errors

If verification fails, the agent should try to fix the issue or clearly report the failure.

## Response Generator

Produces the final user-facing answer.

The response should include:

- What was changed
- Which files were affected
- What verification was run
- Any failures or limitations
- Suggested next steps, if useful

## Memory Store

Stores useful information for future interactions.

Memory types:

- Short-term chat context
- Task history
- Project-specific notes
- User preferences
- Tool execution logs
- Successful solutions

The memory store should not save secrets, tokens, credentials, or private data unless explicitly allowed.

## Error Handling

The architecture should handle these cases:

- Tool execution failure
- Test failure
- Build failure
- Ambiguous user request
- Missing files
- Permission denied
- Conflicting file changes
- External service failure

Recommended behavior:

```text
Detect error -> Retry if safe -> Ask user if blocked -> Report clearly
```

## Updated Architecture Diagram Text

```text
┌─────────────────┐
│  User Question  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Context Builder │
└────────┬────────┘
         │
         ▼
┌───────────────────┐
│ Intent Classifier │
└────────┬──────────┘
         │
         ▼
┌─────────────────┐
│     Planner     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Permission Gate │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Tool Router   │
└────────┬────────┘
         │
         ├── File Search
         ├── File Reader
         ├── File Editor
         ├── Terminal Sandbox
         ├── Git Context
         ├── GitHub Integration
         └── File Generator
         │
         ▼
┌─────────────────┐
│    Verifier     │
└────────┬────────┘
         │
         ├── Tests
         ├── Lint
         ├── Typecheck
         ├── Build
         └── Diff Review
         │
         ▼
┌────────────────────┐
│ Response Generator │
└────────┬───────────┘
         │
         ▼
┌─────────────────┐
│  Memory Store   │
└─────────────────┘
```

## Recommended Build Order

Build the agent in this order:

1. Basic chat interface
2. File search and file read tools
3. Context builder
4. Planner
5. File editor
6. Terminal sandbox
7. Verifier
8. Git context
9. Memory store
10. GitHub integration

## Minimum Viable Coding Agent

For the first working version, implement only these parts:

```text
User Question
  -> Context Builder
  -> Planner
  -> File Search/File Read
  -> File Editor
  -> Terminal Sandbox
  -> Verifier
  -> Final Response
```

GitHub integration, PDF generation, and long-term memory can be added later.
