# Coding Agent

This project is a Python CLI coding agent built from the recommended architecture in `coding-agent-architecture.md`.

## Current Status

Implemented:

1. Basic chat interface
2. File search and file read tools (single + glob)
3. LLM-backed intent parser (Groq/Gemini/OpenAI)
4. File editor (create, modify, delete)
5. Diff view on file modifications
6. Auto-verifier (Python compile check after create/modify)
7. Relative path resolution for nested files
8. Initial structure for context, planner, verifier, Git, memory, and GitHub integration

The current version is intentionally minimal. It gives you a working CLI loop and clean places to add each capability in the recommended build order.

## Run

```bash
python3 -m coding_agent
```

Type a message and press Enter. Use `exit`, `quit`, or `:q` to stop.

## Current Commands

```text
search **/*.py          List matching files
search for .md file     Natural-language search

read README.md          Read a file
read agent.py           Auto-resolves to coding_agent/agent.py
read all the .md files  Read content of all matching files

create hello.py with content print("hi")
                        Create file with inline content
create hello.py         Auto-generates content via LLM

modify hello.py to change goodbye to hello
                        Edits file, shows diff, verifies

delete hello.py         Delete a file
```

All file access is restricted to the current workspace directory.

## Intent Parser

The agent uses an LLM-backed intent parser. It can identify these intents:

```text
search_files
read_file
create_file
modify_code
delete_file
run_command
explain
unknown
```

Before running the agent, configure the LLM provider in `.env`.

For Gemini:

```text
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key-here
CODING_AGENT_INTENT_MODEL=gemini-2.0-flash
```

For Groq:

```text
LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key-here
CODING_AGENT_INTENT_MODEL=llama-3.1-8b-instant
```

For OpenAI:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key-here
CODING_AGENT_INTENT_MODEL=gpt-4o-mini
```

You can override it:

```text
CODING_AGENT_INTENT_MODEL=gemini-2.0-flash
```

The CLI loads `.env` automatically from the project root.

Startup logs show whether `.env` was loaded, which provider/model is selected, and whether the provider-specific API key is configured. The actual API key is never printed.

Examples:

```text
search for .md file
read the content from coding-agent-architecture.md file
i want to create a sample.txt file
```

The intent system prompt is stored at:

```text
coding_agent/prompts/intent_system_prompt.md
```

Currently executable: `search_files`, `read_file`, `create_file`, and `modify_code`. `run_command` is detected but not yet executed until the terminal sandbox step is implemented.

## Build Order

Completed:

1. Basic chat interface
2. File search and file read tools (single + glob)
3. LLM-backed intent parser (Groq/Gemini/OpenAI)
4. File editor (create, modify, delete with diff + verification)

Remaining:

5. Context builder
6. Planner
7. Terminal sandbox
8. Verifier
9. Git context
10. Memory store
11. GitHub integration

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
  memory.py          Short-term memory store
  verifier.py        Verification result handling
  tools/
    files.py         File search/read/edit tools
    terminal.py      Terminal sandbox placeholder
    git.py           Git context placeholder
    github.py        GitHub integration placeholder
