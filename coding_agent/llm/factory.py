"""LLM factory — provider abstraction for the agent runtime."""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class LLMFactory:
    """Creates and caches LLM instances based on configuration.

    Supports OpenRouter (default), OpenAI, and Anthropic via env vars.
    """

    def __init__(self) -> None:
        self._instances: dict[str, object] = {}

    def get_llm(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0,
        max_tokens: int = 2048,
        streaming: bool = False,
    ):
        """Get an LLM instance for the given provider/model.

        Args:
            provider: "openrouter" (default), "openai", or "anthropic"
            model: Model identifier. Defaults to env var or provider default.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            streaming: Whether to enable streaming mode.

        Returns:
            A LangChain-compatible chat model.
        """
        provider = provider or os.getenv("CODING_AGENT_LLM_PROVIDER", "openrouter")
        cache_key = f"{provider}:{model or 'default'}:{temperature}:{max_tokens}:{streaming}"

        if cache_key in self._instances:
            return self._instances[cache_key]

        llm = self._create_provider(provider, model, temperature, max_tokens)
        self._instances[cache_key] = llm
        return llm

    def _create_provider(self, provider: str, model, temperature, max_tokens):
        if provider == "openrouter":
            from .providers import create_openrouter_llm
            return create_openrouter_llm(model=model, temperature=temperature, max_tokens=max_tokens)

        if provider == "openai":
            return self._create_openai(model, temperature, max_tokens)

        if provider == "anthropic":
            return self._create_anthropic(model, temperature, max_tokens)

        raise ValueError(f"Unknown LLM provider: {provider}")

    def _create_openai(self, model, temperature, max_tokens):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for OpenAI provider") from exc

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        return ChatOpenAI(
            model=model or "gpt-4o",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
        )

    def _create_anthropic(self, model, temperature, max_tokens):
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError("langchain-anthropic is required for Anthropic provider") from exc

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        return ChatAnthropic(
            model=model or "claude-sonnet-4-20250514",
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
        )


def create_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0,
    max_tokens: int = 2048,
    streaming: bool = False,
):
    """Convenience function to create an LLM instance."""
    factory = LLMFactory()
    return factory.get_llm(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
    )
