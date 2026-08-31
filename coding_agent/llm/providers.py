"""LLM provider implementations.

Uses langchain-openai's ChatOpenAI pointed at OpenRouter (which is OpenAI-compatible).
"""

import logging
import os
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no python-dotenv dependency)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ or not os.environ.get(key, "").strip()):
            os.environ[key] = value


def _find_dotenv() -> Path:
    """Find .env in CWD ancestry, then module ancestry."""
    cwd = Path.cwd().resolve()
    for d in (cwd, *cwd.parents):
        candidate = d / ".env"
        if candidate.is_file():
            return candidate
    module_dir = Path(__file__).resolve().parent.parent
    for d in (module_dir, *module_dir.parents):
        candidate = d / ".env"
        if candidate.is_file():
            return candidate
    return cwd / ".env"


def create_openrouter_llm(
    model: Optional[str] = None,
    temperature: float = 0,
    max_tokens: int = 2048,
):
    """Create a ChatOpenAI instance configured for OpenRouter.

    Returns a langchain chat model that can be used for both
    structured calls and streaming.
    """
    _load_dotenv(_find_dotenv())

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key or api_key == "your-openrouter-api-key-here":
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env or set the env var."
        )

    model = model or os.getenv("CODING_AGENT_OPENROUTER_MODEL", "openrouter/auto")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError(
            "langchain-openai is required. Install with: pip install langchain-openai"
        ) from exc

    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/mohith1306/coding-agent",
            "X-Title": "Coding Agent",
        },
    )

    logger.info("Created OpenRouter LLM: model=%s", model)
    return llm


def create_openrouter_llm_streaming(
    model: Optional[str] = None,
    temperature: float = 0,
    max_tokens: int = 2048,
):
    """Create a streaming-capable ChatOpenAI for OpenRouter."""
    return create_openrouter_llm(model=model, temperature=temperature, max_tokens=max_tokens)
