# Coding Agent

A Python CLI coding agent that understands natural-language requests and acts on a git workspace: search, read, create, modify, delete, and run files; inspect git and GitHub state; commit and push; and remember facts across sessions.

## Features

```text
search_files          Search files by glob or natural language
read_file             Read a file (single path or glob)
create_file           Create a file (inline content or LLM-generated)
modify_code           Edit a file, show a diff, auto-verify
delete_file           Delete a file (requires confirmation)
run_command           Run commands in a terminal sandbox
plan                  Print a step-by-step plan
list_tasks            List recorded tasks
remember / recall     Store and recall key-value preferences
commit / push         Stage, commit, and push (requires confirmation)
list_issues           List GitHub issues
list_prs              List GitHub pull requests
explain               Explain the detected intent
```

Context is retrieved semantically from a ChromaDB vector store (HNSW + cosine similarity) and injected into LLM calls. Risky operations (delete, install, commit, push) always require confirmation.

## Setup

1. Install dependencies:

   ```bash
   python3 -m pip install -r requirements.txt
   ```

2. Create `.env` in the project root:

   ```text
   LLM_PROVIDER=groq
   GROQ_API_KEY=your-groq-api-key-here
   CODING_AGENT_INTENT_MODEL=llama-3.3-70b-versatile

   # Optional: GitHub integration
   GITHUB_TOKEN=your-github-pat-here

   # Chroma Cloud credentials (vector memory)
   CHROMA_TENANT=your-tenant
   CHROMA_DATABASE=your-database
   CHROMA_API_KEY=your-api-key
   ```

   Supported providers: `groq`, `gemini`, `openai` (see `intent.py` for the matching `*_API_KEY` and model names).

3. Run:

   ```bash
   python3 -m coding_agent
   ```

   Type a request and press Enter. Use `exit`, `quit`, or `:q` to stop.

## Tests

```bash
python3 -m pip install pytest
python3 -m pytest tests/
```

The suite covers the terminal sandbox, git operations, file tools, agent confirmation flow, task/preference memory, and the verifier.

## How It Works

- `cli.py` — interactive loop, drives the confirmation flow
- `agent.py` — intent dispatch, file ops, git commit/push, task and preference handlers
- `intent.py` — LLM-backed intent parser (Groq/OpenAI/Gemini via stdlib urllib)
- `context.py` — builds project + related-context for LLM calls
- `memory.py` — ChromaDB-backed memory (chat turns, file events, tasks, preferences)
- `verifier.py` — compile checks and project test/lint runs
- `planner.py` — step plan generation
- `tools/` — files, terminal sandbox, git, GitHub REST integration

## Project Structure

```text
coding_agent/
  __main__.py        CLI module entry point
  cli.py             Interactive chat loop
  agent.py           Main agent orchestration
  context.py         Context builder
  intent.py          Intent parser
  prompts/           LLM system prompts
  planner.py         Task planner
  memory.py          ChromaDB-backed memory store
  verifier.py        File + project verification
  tools/
    files.py         File search/read/edit tools
    terminal.py      Terminal sandbox
    git.py           Git status / stage / commit / push
    github.py        GitHub issues and PRs (REST API)
tests/               pytest suite
```

## Architecture

Design notes are in `context-builder-architecture.md` and `vector-context-architecture.md`. The memory layer uses ChromaDB Cloud rather than the embedded mode described in the original docs.
