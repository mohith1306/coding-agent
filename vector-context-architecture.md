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
Mode:     Cloud (server-side, single database for all memory)
Index:    HNSW (Hierarchical Navigable Small World)
Metric:   Cosine similarity
Storage:  Chroma Cloud
```

ChromaDB is chosen because:

- HNSW built-in with configurable M (connections) and ef_construction
- Cosine similarity as default distance
- Stores metadata alongside vectors
- Cloud mode means no local persistence to manage; one database serves all clients
- Credentials come from `.env` (`CHROMA_TENANT`, `CHROMA_DATABASE`, `CHROMA_API_KEY`)

## Embeddings

```text
Provider: Chroma's default ONNX embedding model (all-MiniLM-L6-v2)
Dim:      384
Cache:    downloaded on first use to ~/.cache/chroma
```

The query is embedded client-side before the HNSW nearest-neighbor search.

## Collection Schema

Single collection `agent_memory` with three document types distinguished by `doc_type`:

```text
Document type: "chat"
  embedding: vector
  metadata:
    doc_type: "chat"
    role: "user" | "agent"
    content: str (truncated to 1000 chars)
    agent_response: str (truncated to 1000 chars)
    intent: str
    target: str
    timestamp: float (time.time())

Document type: "file"
  embedding: vector
  metadata:
    doc_type: "file"
    path: str
    content_preview: str (first 500 chars)
    operation: "created" | "modified" | "deleted"
    timestamp: float

Document type: "task"
  embedding: vector
  metadata:
    doc_type: "task"
    description: str
    status: "pending" | "done"
    files_affected: str (comma-joined)
    timestamp: float

Document type: "preference"
  embedding: vector
  metadata:
    doc_type: "preference"
    key: str
    value: str (truncated to 1000 chars)
    timestamp: float
```

## HNSW Configuration

Chroma Cloud applies HNSW indexing with cosine distance by default; no custom config is required from the client.

## Retrieval Logic

```python
def retrieve_similar(query: str, k: int = 5, doc_type: str | None = None, max_distance: float = 0.95) -> list[dict]:
    where = {"doc_type": doc_type} if doc_type else None
    results = collection.query(
        query_texts=[query],
        n_results=k,
        where=where,
        include=["metadatas", "documents", "distances"],
    )

    # Filter by cosine distance threshold
    merged = [
        {
            "id": results["ids"][0][i],
            "document": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        }
        for i in range(len(results["ids"][0]))
        if results["distances"][0][i] <= max_distance
    ]
    return merged
```

Relevant matches typically land at cosine distance ~0.74-0.83; unrelated topics exceed `max_distance` and are filtered out.

## Context Prompt Format

When injected into LLM calls, the retrieved context is formatted as:

```text
--- Related Context ---
[File: src/auth.py] (modified) def login(username, password):
[Related] can you add error handling to the login function
```

If vector search returns nothing, the builder falls back to the most recent file events.

## Storage Layout

Chroma Cloud hosts the single `agent_memory` collection. The local Chroma cache lives in `~/.cache/chroma`. No local database directory is used.

## Dependencies

```text
chromadb>=1.5.0
```

LLM calls (intent parsing, code generation) use only the standard library (`urllib`); no SDK is required.

## Benefits

```text
Vector: top 5 turns by semantic relevance
-> Finds relevant context from entire session history

Vector: file edits are embedded and searchable
-> Agent remembers "oh, I already created that utility function"

Vector: tasks and preferences persisted across sessions
-> Agent remembers ongoing work and personal facts
```
