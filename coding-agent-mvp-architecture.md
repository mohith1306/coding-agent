# Coding Agent — MVP Architecture

## 1. Purpose

This document defines the target architecture for the existing `mohith1306/coding-agent` project.

The goal is to evolve the current Python + FastAPI + React coding agent into a structured agent runtime using:

- LangGraph — agent orchestration and stateful execution
- LangChain — LLM/tool abstractions
- LangSmith — tracing, debugging, observability and evaluation
- Existing Context Builder — repository-aware context construction
- Tree-sitter — code structure / AST analysis
- PostgreSQL + pgvector — semantic memory and retrieval (replaces ChromaDB);
  project facts in `project_contexts`, embeddings via OpenRouter, keyword
  fallback when vectors are unavailable (see §13)
- Daytona + local sandbox — isolated code execution
- Git / GitHub integrations — repository operations
- FastAPI — backend API and streaming
- React/Vite + Monaco — coding workspace

The architecture is intentionally incremental. Existing working components should be preserved and migrated behind clear interfaces instead of rewriting the entire project.

---

# 2. Architectural Principle

The platform should be divided into five major layers:

```text
┌──────────────────────────────────────────────────────────┐
│                    USER INTERFACE                        │
│              React + Monaco + Terminal                   │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                    API / SESSION                         │
│                     FastAPI                              │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                  AGENT RUNTIME                           │
│                     LangGraph                            │
│                                                          │
│ Understand → Context → Plan → Agent → Tools → Verify    │
│                              ↑                    │       │
│                              └──── Repair ───────┘       │
└──────────────────────────┬───────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   Context Engine      Tool Harness      LLM Layer
          │                │                │
          ▼                ▼                ▼
  Tree-sitter/ripgrep   Sandbox/Git      OpenRouter
  Postgres/pgvector     GitHub           BYOK
```

LangSmith observes the LangGraph runtime and records traces across nodes, model calls, tools, errors and execution latency.

---

# 3. High-Level System Architecture

```text
                         ┌──────────────────────┐
                         │         USER         │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │    React / Vite      │
                         │                      │
                         │ Chat                 │
                         │ Monaco Editor        │
                         │ File Explorer        │
                         │ Terminal             │
                         │ Diff Viewer          │
                         │ Approval UI           │
                         └──────────┬───────────┘
                                    │
                              SSE / WebSocket
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       FastAPI        │
                         │                      │
                         │ Session API          │
                         │ Agent API            │
                         │ Sandbox API           │
                         │ Streaming             │
                         └──────────┬───────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────┐
                    │          LANGGRAPH           │
                    │        AGENT RUNTIME         │
                    │                              │
                    │  Understand Request          │
                    │          ↓                   │
                    │  Build Context               │
                    │          ↓                   │
                    │  Plan                        │
                    │          ↓                   │
                    │  Agent / LLM                 │
                    │          ↓                   │
                    │  Tool Harness                │
                    │          ↓                   │
                    │  Verification                │
                    │          │                   │
                    │      ┌───┴────┐              │
                    │      │        │              │
                    │     PASS     FAIL            │
                    │      │        │              │
                    │      ▼        ▼              │
                    │    Finish   Repair ──┐       │
                    │                       └───►Agent
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
       ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
       │   Context   │      │    Tools    │      │     LLM     │
       │   Engine    │      │   Harness   │      │    Layer    │
       └──────┬──────┘      └──────┬──────┘      └──────┬──────┘
              │                    │                    │
       ┌──────┴──────┐       ┌─────┴──────┐      ┌─────┴────────┐
       ▼             ▼       ▼            ▼      ▼              ▼
  Tree-sitter    Chroma   Sandbox       Git   OpenRouter      BYOK
                    │
                    ▼
                 Memory
```

---

# 4. Existing Project → Target Architecture

The existing project already contains the main building blocks. They should be reassigned rather than discarded.

| Existing Component | Target Responsibility |
|---|---|
| `agent.py` | LangGraph graph/runtime |
| `intent.py` | `understand_request` graph node |
| `context.py` | Context Engine |
| `planner.py` | `planning` graph node |
| `memory.py` | Memory subsystem |
| `compaction.py` | Context/token management |
| `verifier.py` | Verification node |
| `tools/files.py` | File tools |
| `tools/terminal.py` | Terminal tool |
| `tools/daytona_sandbox.py` | Daytona sandbox implementation |
| Git integration | Git tools |
| GitHub integration | GitHub tools |
| `events.py` | Graph/event streaming adapter |
| `prompts/` | LangChain prompt layer |
| FastAPI backend | API + graph streaming |
| React frontend | Coding workspace |

The existing repository should remain the source of truth for currently working behavior.

---

# 5. LangGraph Agent Runtime

LangGraph becomes the orchestration layer.

## Graph

```text
START
  │
  ▼
understand_request
  │
  ▼
build_context
  │
  ▼
plan
  │
  ▼
agent
  │
  ▼
tools
  │
  ▼
verify
  │
  ├────────────── PASS ──────────────► finish
  │
  └────────────── FAIL
                       │
                       ▼
                    repair
                       │
                       └──────────────► agent
```

The graph should support:

- stateful execution
- streaming
- retries
- conditional routing
- human approval
- checkpoints
- resumable sessions
- maximum repair iterations

Do not implement multi-agent orchestration in the MVP.

---

# 6. LangGraph State

Create a single typed state shared across graph nodes.

```python
class AgentState:
    session_id: str
    project_id: str

    user_message: str

    intent: object | None
    intent_confidence: float | None

    current_file: str | None
    selected_code: str | None

    conversation: list

    relevant_files: list
    context: list

    plan: list

    tool_calls: list
    tool_results: list

    changed_files: list

    verification_result: object | None
    test_result: object | None

    repair_attempts: int

    awaiting_confirmation: bool

    final_response: str | None
```

The exact implementation should use LangGraph's typed state model.

---

# 7. LangGraph Nodes

## `understand_request`

Responsibility:

- parse the user request
- identify intent
- determine whether code changes are required
- determine whether terminal/sandbox execution may be required

Existing `intent.py` logic should be reused here.

---

## `build_context`

Responsibility:

- inspect current project state
- use existing ContextBuilder
- use Git context
- retrieve relevant memory
- retrieve relevant code
- respect context/token budgets

Do not load the entire repository into the LLM.

---

## `plan`

Responsibility:

- turn the request into executable steps
- identify files/symbols likely involved
- determine required tools
- define verification requirements

Existing `planner.py` should be migrated into this node.

---

## `agent`

Responsibility:

- call the selected LLM
- reason over the current state
- decide which tool to use
- generate or modify code
- determine when the task is complete

This is the main LLM reasoning node.

---

## `tools`

Responsibility:

- execute tool calls
- return structured tool results
- update changed files
- report failures

---

## `verify`

Responsibility:

- inspect modifications
- run relevant tests/checks
- detect syntax/type/build errors
- produce a structured verification result

Existing `verifier.py` should be reused.

---

## `repair`

Responsibility:

- inspect verification failure
- provide failure context to the agent
- allow another repair iteration
- stop after a configurable maximum

Example:

```text
MAX_REPAIR_ATTEMPTS = 3
```

---

## `finish`

Responsibility:

- produce final response
- summarize changes
- report tests
- report remaining issues
- return structured information to the frontend

---

# 8. Tool Harness

LangGraph should never directly manipulate infrastructure.

Use a Tool Harness.

```text
                     LangGraph
                         │
                         ▼
                    Tool Harness
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
       ▼                 ▼                  ▼
   File Tools       Terminal Tools       Git Tools
       │                 │                  │
       ▼                 ▼                  ▼
 read/write/search     Sandbox          Git/GitHub
```

## Core tools

```text
read_file
write_file
list_files
search_files
run_command
run_tests
git_status
git_diff
git_commit
git_push
github_issue
github_pr
```

Each tool should have:

- input schema
- validation
- execution
- structured result
- error handling
- optional approval requirement

---

# 9. Human-in-the-Loop

Destructive or important operations should support approval.

Example:

```text
Agent
  │
  ▼
write_file
  │
  ▼
Human Approval
  │
  ├── Reject ──► Agent
  │
  └── Approve ─► Execute
```

Use LangGraph interrupt/checkpoint functionality so a session can pause and resume without losing agent state.

Approval should eventually cover:

- writing files
- deleting files
- terminal commands with side effects
- Git commit
- Git push
- GitHub PR creation
- deployment

---

# 10. Context Engine

The Context Engine should remain separate from LangGraph.

```text
                      Repository
                          │
                          ▼
                   Context Builder
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
         Git Context   Tree-sitter   ripgrep
             │            │            │
             └────────────┼────────────┘
                          ▼
                   Context Ranking
                          │
                          ▼
                  Semantic Retrieval
                          │
                          ▼
                       Chroma
                          │
                          ▼
                  Token Budgeting
                          │
                          ▼
                       Context
                          │
                          ▼
                       Agent
```

The existing project intentionally minimizes unnecessary filesystem access. Preserve this behavior.

---

# 11. Tree-sitter

Tree-sitter should provide structural understanding of source code.

Extract:

```text
files
imports
exports
classes
methods
functions
interfaces
symbols
references
```

This allows the agent to reason about relationships between files rather than relying only on raw text search.

---

# 12. ripgrep

Use ripgrep for fast exact search.

Examples:

```text
find symbol
find string
find imports
find references
find TODO
find error messages
```

Use semantic search only when exact search is insufficient.

---

# 13. ChromaDB

Keep the existing Chroma-based memory/retrieval architecture for the MVP.

Use it for:

```text
conversation memory
project memory
task memory
semantic retrieval
relevant previous context
```

Do not migrate to another vector database unless the current implementation becomes a bottleneck.

---

# 14. Context Ranking

Retrieved context should be ranked using signals such as:

```text
current file relevance
selected code relevance
symbol relevance
import relationship
semantic similarity
recently changed files
user-provided references
```

Then apply a token budget before passing context to the LLM.

---

# 15. LLM Layer

Create a provider abstraction.

```text
                    LLM Service
                        │
            ┌───────────┼────────────┐
            ▼           ▼            ▼
       OpenRouter     OpenAI      Anthropic
            │
            ▼
       Selected Model
```

The agent should depend on an abstract LLM interface rather than a specific provider.

Example:

```python
llm.generate(...)
llm.stream(...)
```

This enables:

- OpenRouter
- platform-owned API keys
- BYOK
- model selection
- future providers

---

# 16. LangChain

Use LangChain selectively.

Responsibilities:

- model wrappers
- tool schemas
- prompts
- structured output
- message abstractions

Do not make LangChain responsible for the entire application.

LangGraph remains the orchestration layer.

---

# 17. LangSmith

LangSmith should observe the complete agent execution.

```text
                         LangSmith
                             │
              ┌──────────────┼───────────────┐
              ▼              ▼               ▼
          Graph Nodes     LLM Calls       Tool Calls
              │              │               │
              └──────────────┼───────────────┘
                             ▼
                         Full Trace
```

Track:

- user request
- intent
- retrieved context
- plan
- LLM calls
- model
- latency
- token usage
- tool calls
- tool failures
- sandbox output
- verification result
- repair iterations
- final response

This should be enabled from the beginning.

---

# 18. Sandbox Architecture

Keep the current Daytona + local fallback approach.

```text
                    Sandbox Interface
                           │
                ┌──────────┴──────────┐
                ▼                     ▼
          Local Sandbox           Daytona
                │                     │
                ▼                     ▼
             Local                 Remote
          Environment             Environment
```

The agent only knows about:

```python
sandbox.run(command)
sandbox.read_file(path)
sandbox.write_file(path)
sandbox.get_output()
```

It should not care whether execution happens locally or in Daytona.

---

# 19. Terminal

The terminal flow should be:

```text
Browser
  │
  ▼
Terminal UI
  │
  ▼
FastAPI
  │
  ▼
Sandbox Manager
  │
  ▼
node-pty / Daytona
  │
  ▼
Execution Environment
```

The terminal is an interactive user feature.

`run_command` is an agent tool.

They may share the same sandbox infrastructure but should remain separate interfaces.

---

# 20. Git Architecture

```text
                    Git Service
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       status           diff          commit
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                      GitHub
```

The agent can use Git tools through the Tool Harness.

---

# 21. API Architecture

FastAPI should remain the public backend.

```text
FastAPI
│
├── /auth
│
├── /projects
│
├── /sessions
│
├── /sessions/{id}/messages
│
├── /agent
│
├── /sandbox
│
├── /terminal
│
└── /github
```

The agent execution endpoint should stream graph events.

Example:

```text
POST /sessions/{session_id}/messages

        ↓

LangGraph

        ↓

SSE stream

        ↓

Frontend
```

---

# 22. Frontend Architecture

Keep the current React application.

```text
React
│
├── Chat
│
├── Monaco Editor
│
├── File Explorer
│
├── Terminal
│
├── Diff Viewer
│
├── Agent Status
│
└── Approval Dialog
```

The frontend should display LangGraph events such as:

```text
Understanding request...
Building context...
Planning...
Reading auth.py
Editing auth.py
Running tests...
Tests failed
Repairing...
Tests passed
Completed
```

---

# 23. Agent Event Model

Create a normalized event model.

```text
AgentEvent

type:
  run_started
  node_started
  node_completed
  llm_started
  llm_completed
  tool_started
  tool_completed
  sandbox_started
  sandbox_output
  verification_started
  verification_completed
  approval_required
  repair_started
  run_completed
  run_failed
```

This decouples LangGraph internals from the React UI.

---

# 24. Session Architecture

A coding session should map to a LangGraph thread.

```text
User
 │
 ▼
Project
 │
 ▼
Session
 │
 ▼
LangGraph Thread
 │
 ▼
Checkpointed State
```

This allows:

- conversation continuation
- interrupted runs
- approval/resume
- repair loops
- session restoration

---

# 25. Complete User Request Flow

Example:

> "Fix the authentication bug and run the tests."

```text
USER
 │
 ▼
React
 │
 ▼
FastAPI
 │
 ▼
Create Agent Run
 │
 ▼
LangGraph
 │
 ▼
Understand Request
 │
 ▼
Context Engine
 │
 ├── Git
 ├── Tree-sitter
 ├── ripgrep
 └── Chroma
 │
 ▼
Planner
 │
 ▼
Agent / LLM
 │
 ▼
Tool Harness
 │
 ▼
read_file()
 │
 ▼
Agent / LLM
 │
 ▼
write_file()
 │
 ▼
Sandbox
 │
 ▼
run_tests()
 │
 ▼
Verification
 │
 ├── PASS ───────────────► Finish
 │
 └── FAIL
       │
       ▼
     Repair
       │
       └──────────────► Agent
```

LangSmith traces every important step.

---

# 26. Repository Structure

Target structure:

```text
coding-agent/
│
├── coding_agent/
│   │
│   ├── graph/
│   │   ├── state.py
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   ├── edges.py
│   │   └── config.py
│   │
│   ├── context/
│   │   ├── builder.py
│   │   ├── retriever.py
│   │   ├── ranker.py
│   │   └── compaction.py
│   │
│   ├── tools/
│   │   ├── registry.py
│   │   ├── files.py
│   │   ├── terminal.py
│   │   ├── sandbox.py
│   │   ├── git.py
│   │   └── github.py
│   │
│   ├── memory/
│   │   └── chroma.py
│   │
│   ├── llm/
│   │   ├── factory.py
│   │   ├── openrouter.py
│   │   └── providers.py
│   │
│   ├── verification/
│   │   ├── verifier.py
│   │   └── repair.py
│   │
│   ├── prompts/
│   │
│   └── main.py
│
├── web/
│   ├── backend/
│   │   ├── app.py
│   │   ├── routes/
│   │   └── streaming.py
│   │
│   └── frontend/
│
├── tests/
│
├── langgraph.json
├── requirements.txt
└── .env
```

The exact folder migration should be incremental rather than a single large rewrite.

---

# 27. Configuration

Environment variables should include:

```text
OPENROUTER_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

LANGSMITH_API_KEY=
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=coding-agent

CHROMA_API_KEY=
CHROMA_TENANT=
CHROMA_DATABASE=

DAYTONA_API_KEY=

GITHUB_TOKEN=
```

Secrets must never be committed.

---

# 28. MVP Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite |
| Editor | Monaco |
| Backend | FastAPI |
| Agent Runtime | LangGraph |
| LLM/Tools | LangChain |
| Observability | LangSmith |
| Context | Existing ContextBuilder |
| Code Parsing | Tree-sitter |
| Exact Search | ripgrep |
| Memory/Retrieval | ChromaDB |
| Sandbox | Daytona + Local fallback |
| Git | Git |
| GitHub | Existing GitHub integration |
| Streaming | SSE |
| Terminal | Existing terminal architecture |
| Language | Python |
| Existing UI | React |

---

# 29. What NOT to introduce yet

Do not add these during the MVP architecture migration:

```text
Kubernetes
Firecracker
Kafka
Temporal
Redis
PostgreSQL migration
Qdrant migration
Multiple agent architecture
WebRTC collaboration
Microservices
Complex distributed workers
```

They can be introduced when actual scale requires them.

---

# 30. Migration Plan

## Phase 1 — Agent State

Create:

```text
graph/state.py
```

Move the important state currently stored inside `CodingAgent` into `AgentState`.

---

## Phase 2 — Graph

Create:

```text
graph/graph.py
graph/nodes.py
graph/edges.py
```

Implement:

```text
START
 ↓
understand
 ↓
context
 ↓
plan
 ↓
agent
 ↓
tools
 ↓
verify
 ↓
finish
```

---

## Phase 3 — Tool Harness

Convert existing tools into standardized LangChain-compatible tools.

Start with:

```text
read_file
write_file
search_files
run_command
run_tests
```

Then migrate Git/GitHub tools.

---

## Phase 4 — LangSmith

Enable tracing and verify that one complete agent execution produces a useful trace.

---

## Phase 5 — Streaming

Connect LangGraph streaming events to FastAPI and then React.

---

## Phase 6 — Human Approval

Add approval interrupts for file modification and other sensitive operations.

---

## Phase 7 — Repair Loop

Move the existing verifier/repair behavior into conditional LangGraph edges.

---

## Phase 8 — Context Engine

Keep the existing ContextBuilder behavior while exposing it as a clean graph node/service.

---

# 31. First MVP Graph

The first graph that must work end-to-end is:

```text
START
  ↓
Understand
  ↓
Context
  ↓
Agent
  ↓
Read/Write Tools
  ↓
Sandbox
  ↓
Verify
  ↓
Finish
```

Test it with:

> "Find the bug in this file, fix it, and run the tests."

Once this works reliably, add planning, memory, GitHub operations and human approval.

---

# 32. Definition of Done

The architecture migration is successful when:

- LangGraph owns agent orchestration.
- `AgentState` contains the execution state.
- Existing tools are accessible through a Tool Harness.
- Existing ContextBuilder remains responsible for repository context.
- Daytona/local sandbox remains responsible for execution.
- Verification and repair are graph nodes/edges.
- LangSmith traces the complete execution.
- FastAPI streams graph events.
- React displays live agent progress.
- A session can pause and resume.
- The agent can modify code and verify the modification.
- Existing CLI functionality remains usable during migration.

---

# 33. Future Architecture

Once the MVP is validated, the architecture can evolve toward:

```text
                         Supervisor Agent
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
           Coder            Reviewer          Tester
              │                │                │
              └────────────────┼────────────────┘
                               ▼
                         Tool Harness
                               │
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
               Context      Sandbox       Git
                  │
              Repository
                  │
          Tree-sitter + Search
```

Additional infrastructure can later include:

- PostgreSQL
- Redis
- Qdrant
- distributed sandbox workers
- Firecracker
- E2B/Daytona scaling
- background indexing
- multi-agent workflows
- evaluation pipelines

These should be added only when the MVP demonstrates the need.

---

# 34. Core Architectural Rule

The final separation of responsibility should remain:

```text
FastAPI
    = API + sessions + streaming

LangGraph
    = agent orchestration + state + control flow

LangChain
    = models + tools + prompts + structured output

LangSmith
    = tracing + observability + evaluation

Context Engine
    = repository understanding + retrieval

Tree-sitter
    = source-code structure

ripgrep
    = exact search

PostgreSQL + pgvector
    = semantic memory/retrieval + project facts

Tool Harness
    = safe standardized tool execution

Sandbox
    = code execution

Git/GitHub
    = source control

React + Monaco
    = coding workspace
```

This is the architecture to implement against for the MVP. Do not introduce another orchestration framework on top of LangGraph; LangGraph should be the central execution engine.

---

# 35. Context Subsystem (as built, Phases 0–3)

Single build per user turn (`ContextBuilder.build`), no mid-loop refresh:

```text
build()
 ├─ chat history (last 5 turns) + compaction summary
 ├─ retrieve_similar → pgvector cosine → keyword fallback (shared ranker)
 ├─ git branch + dirty files, project identity (instance-cached)
 ├─ project facts (Postgres project_contexts, all intents)
 └─ file bodies: intent target first + semantic + recent files
        (root-jailed, binary/oversize skipped, canonical dedup)

format_for_prompt() → budget assembler (CODING_AGENT_CONTEXT_TOKENS, 12k default)
 priority: identity > target > files > project > related > history > summary
 per-section caps; per-file pre-budgeting; fence-aware truncation;
 output never exceeds the total.
```

Supporting modules: `tokens.py` (shared estimator), `project_scan.py`
(single detection impl), `embeddings.py` (OpenRouter, default
`nvidia/nemotron-3-embed-1b:free` sliced + L2-renormalized to 1024 dims
for HNSW), `keyword_search.py`, `context_budget.py`, `file_context.py`,
`project_store.py` (learnings recorded on all intents, both legacy and
graph runtimes; `SELECT ... FOR UPDATE` appends). Migrations
`002_pgvector.sql` (guarded extension setup) and
`003_project_contexts.sql`. All paths degrade offline: missing DB,
missing extension, or embedding outage yields keyword search and
omitted sections — never a crash.
