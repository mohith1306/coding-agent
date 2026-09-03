"""OpenRouter embeddings client for semantic memory.

Uses the OpenAI-compatible ``/api/v1/embeddings`` endpoint with a
configurable (default free) embedding model. All failures return None —
embeddings are best-effort: a rate-limit or outage must never block
a memory write or a retrieval (callers fall back to keyword search).

Env:
    CODING_AGENT_EMBED_MODEL  model slug (default: nvidia/nemotron-3-embed-1b:free, dim 2048)
    CODING_AGENT_EMBED_DIM    expected vector dimension (default: 2048)
    CODING_AGENT_EMBEDDINGS   "off" disables all embedding calls (default: on)
"""

import json
import logging
import os
from typing import Optional
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "nvidia/nemotron-3-embed-1b:free"
DEFAULT_DIM = 2048
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

    def __init__(self, api_key: str = "", model: str = "") -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model = model or embed_model()

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
            items = sorted(body["data"], key=lambda d: d.get("index", 0))
            out: list[Optional[list[float]]] = []
            for item in items:
                vec = item.get("embedding")
                out.append([float(x) for x in vec] if isinstance(vec, list) else None)
            # Pad/truncate defensively to input length
            while len(out) < len(texts):
                out.append(None)
            return out[:len(texts)]
        except Exception as error:
            logger.warning("Embedding response parse failed (%s); falling back", error)
            return [None] * len(texts)
