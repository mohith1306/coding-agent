# Vector Context Retrieval Architecture

## Overview

Replace the current linear chat-history lookup with semantic vector search. Every interaction, file edit, and task note is embedded and stored in a vector database with HNSW indexing. On each user request, the most semantically relevant context is retrieved using cosine similarity.

## Flow

```text
User request
  -> Embed query vector
  -> HNSW nearest-neighbor search (top K)
  -> Retrieve stored metadata (messages, files, tasks)
  -> Inject into LLM prompt as context
  -> Agent acts
  -> Embed response + outcome
  -> Store in vector DB
```

## Vector Database: ChromaDB

```text
Product:  ChromaDB
Mode:     Embedded (no server)
Index:    HNSW (Hierarchical Navigable Small World)
Metric:   Cosine similarity
Storage:  Persistent, local directory
```

ChromaDB is chosen because:

- Embedded mode — zero infrastructure
- HNSW built-in with configurable M (connections) and ef_construction
- Cosine similarity as default distance
- Persistent to disk
- Stores metadata alongside vectors
- No server process needed

## Embeddings

Option A — Local (recommended for privacy/offline):

```text
Model:  sentence-transformers/all-MiniLM-L6-v2
Size:   ~80 MB
Dim:    384
Speed:  ~10ms per embed on CPU
```

Option B — API:

```text
Model:  OpenAI text-embedding-3-small
Dim:    512 (or 1536 with dimension parameter)
Cost:   ~$0.0001 per embed (negligible for CLI usage)
```

## Collection Schema

Single collection `agent_memory` with three document types distinguished by `doc_type`:

```text
Document type: "chat"
  embedding: vector
  metadata:
    doc_type: "chat"
    session_id: str
    role: "user" | "agent"
    content: str (truncated to 2000 chars)
    intent: str
    target: str
    timestamp: float

Document type: "file"
  embedding: vector
  metadata:
    doc_type: "file"
    path: str
    content_preview: str (first 2000 chars)
    operation: "read" | "created" | "modified" | "deleted"
    timestamp: float

Document type: "task"
  embedding: vector
  metadata:
    doc_type: "task"
    description: str
    status: "completed" | "in_progress" | "failed"
    files_affected: list[str]
    timestamp: float
```

## HNSW Configuration

```python
collection_config = {
    "hnsw:space": "cosine",
    "hnsw:M": 16,              # connections per node (higher = more accurate but slower)
    "hnsw:ef_construction": 200,  # index quality (higher = better recall)
    "hnsw:ef_search": 50,      # search depth (higher = more accurate but slower)
}
```

## Retrieval Logic

```python
def retrieve_context(query: str, k: int = 5) -> str:
    query_embedding = embed(query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        include=["metadatas", "distances"],
    )

    # Filter by distance (cosine similarity threshold)
    results = [r for r in results if r.distance < 0.4]

    # Build context block
    blocks = []
    for result in results:
        if result.doc_type == "chat":
            blocks.append(f"[{result.role}] {result.content[:500]}")
        elif result.doc_type == "file":
            blocks.append(f"[File: {result.path}] {result.content_preview[:300]}")
        elif result.doc_type == "task":
            blocks.append(f"[Task: {result.description}] ({result.status})")

    return "\n".join(blocks)
```

## Context Prompt Format

When injected into LLM calls, the retrieved context is formatted as:

```text
--- Related Context ---
[user] can you add error handling to the login function
[agent] I'll modify auth.py to add try/except blocks
[File: src/auth.py] def login(username, password):
[Task: Add error handling to auth.py] (in_progress)
```

## Storage Layout

```text
.coding-agent/
  chromadb/           ChromaDB persistent data
  embeddings_cache/   Optional local embedding model cache
```

No additional databases. ChromaDB replaces SQLite entirely.

## Dependencies

```text
chromadb>=0.5.0
sentence-transformers>=2.2.0   (if using local embeddings)
```

## Benefits Over Current Approach

```text
Current: last 5 turns by position only
-> Ignores earlier but relevant context

Vector: top 5 turns by semantic relevance
-> Finds relevant context from entire session history

Current: no file memory across sessions
-> Agent forgets what files it created yesterday

Vector: file edits are embedded and searchable
-> Agent remembers "oh, I already created that utility function"
```
