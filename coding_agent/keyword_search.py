"""Keyword fallback scorer for memory retrieval.

Used when pgvector is unavailable (or embeddings fail): ranks documents
by token overlap with the query. Shared by ``MemoryStore`` (Postgres
fallback path) and ``InMemoryMemoryStore`` so both behave identically.
"""

import re

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens."""
    return set(_TOKEN_RE.findall(text.lower()))


def keyword_score(query: str, document: str) -> float:
    """Token-overlap score in [0, 1]: fraction of query tokens in document."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    doc_tokens = tokenize(document)
    if not doc_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens)


def rank_documents(
    query: str,
    documents: list[dict],
    text_key: str = "document",
    top_k: int = 5,
    min_score: float = 0.01,
) -> list[dict]:
    """Rank document dicts by keyword score, highest first.

    Each returned dict is the original with an added ``distance`` key
    (1 - score, so lower is better — matching pgvector semantics).
    Documents below ``min_score`` are dropped.
    """
    scored = []
    for doc in documents:
        score = keyword_score(query, str(doc.get(text_key, "")))
        if score >= min_score:
            scored.append((score, doc))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = []
    for score, doc in scored[:top_k]:
        ranked.append({**doc, "distance": 1.0 - score})
    return ranked
