"""OpenRouter embeddings client for semantic memory.

Uses the OpenAI-compatible ``/api/v1/embeddings`` endpoint with a
configurable (default free) embedding model. All failures return None —
embeddings are best-effort: a rate-limit or outage must never block
a memory write or a retrieval (callers fall back to keyword search).

Env:
    CODING_AGENT_EMBED_MODEL  model slug (default: nvidia/nemotron-3-embed-1b:free)
    CODING_AGENT_EMBED_DIM    stored vector dimension (default: 1024, sliced +
                              L2 re-normalized from the model's native 2048 so
                              pgvector HNSW (<=2000 dims) can index it)
    CODING_AGENT_EMBEDDINGS   "off" disables all embedding calls (default: on)
"""

import json
import logging
import os
from typing import Optional
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "nvidia/nemotron-3-embed-1b:free"
# Nemotron-3-Embed emits 2048 dims natively, but pgvector HNSW indexes
# support at most 2000 dims for the `vector` type. The model supports
# slicing the leading dims (1024/512 remain functional after L2
# re-normalization), so the default fits HNSW. Override via
# CODING_AGENT_EMBED_DIM only with a model whose native dim fits.
DEFAULT_DIM = 1024
MAX_INPUT_CHARS = 8000


def embed_model() -> str:
    """Configured embedding model slug."""
    return os.getenv("CODING_AGENT_EMBED_MODEL", DEFAULT_MODEL)


def embed_dim() -> int:
    """Configured embedding dimension (must match the model)."""
    try:
        return max(1, int(os.getenv("CODING_AGENT_EMBED_DIM", str(DEFAULT_DIM))))
    except ValueError:
        logger.warning("Invalid CODING_AGENT_EMBED_DIM, using %d", DEFAULT_DIM)
        return DEFAULT_DIM


def embeddings_enabled() -> bool:
    """Whether embedding calls are enabled (env kill-switch)."""
    if os.getenv("CODING_AGENT_EMBEDDINGS", "on").lower() in {"off", "0", "false", "no"}:
        return False
    return bool(os.getenv("OPENROUTER_API_KEY", ""))


def to_pgvector(vec: list[float]) -> str:
    """Format a vector for pgvector input ('[0.1,0.2,...]' literal)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class EmbeddingClient:
    """Thin OpenRouter embeddings client (OpenAI-compatible)."""

    def __init__(self, api_key: str = "", model: str = "", dim: int = 0) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model = model or embed_model()
        self.dim = dim or embed_dim()

    def _fit_dim(self, vec: list[float]) -> Optional[list[float]]:
        """Fit a raw embedding to the configured dimension.

        Longer vectors are sliced to the leading dims and L2
        re-normalized (supported by Matryoshka-style models); shorter
        vectors are rejected so nothing silently misaligns the column.
        """
        if len(vec) == self.dim:
            return vec
        if len(vec) > self.dim:
            sliced = vec[:self.dim]
            norm = sum(x * x for x in sliced) ** 0.5
            if norm <= 0:
                return None
            return [x / norm for x in sliced]
        logger.warning("Embedding dim %d < expected %d; skipping", len(vec), self.dim)
        return None

    def embed(self, text: str) -> Optional[list[float]]:
        """Embed a single text. Returns None on any failure."""
        results = self.embed_batch([text])
        return results[0] if results else None

    def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Embed multiple texts in one request. Failures yield None per item.

        Returns a list aligned with `texts`; never raises.
        """
        if not texts:
            return []
        if not self.api_key:
            logger.debug("OPENROUTER_API_KEY not set, skipping embeddings")
            return [None] * len(texts)

        payload = {
            "model": self.model,
            "input": [t[:MAX_INPUT_CHARS] for t in texts],
        }
        request = Request(
            "https://openrouter.ai/api/v1/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/mohith1306/coding-agent",
                "X-Title": "Coding Agent",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            logger.warning("Embedding request failed (%s); falling back", error)
            return [None] * len(texts)

        try:
            # Place each embedding at its declared index; reject duplicates
            # and out-of-range indexes so partial responses can never
            # misassign one text's vector to another.
            out: list[Optional[list[float]]] = [None] * len(texts)
            seen: set[int] = set()
            for item in body["data"]:
                idx = item.get("index")
                if not isinstance(idx, int) or idx < 0 or idx >= len(texts):
                    logger.warning("Ignoring embedding with invalid index: %r", idx)
                    continue
                if idx in seen:
                    logger.warning("Ignoring duplicate embedding index: %d", idx)
                    continue
                seen.add(idx)
                vec = item.get("embedding")
                if isinstance(vec, list):
                    try:
                        out[idx] = self._fit_dim([float(x) for x in vec])
                    except (TypeError, ValueError):
                        out[idx] = None
                else:
                    out[idx] = None
            return out
        except Exception as error:
            logger.warning("Embedding response parse failed (%s); falling back", error)
            return [None] * len(texts)
