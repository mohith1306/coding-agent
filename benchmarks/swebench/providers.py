"""Multi-provider LLM rotation with rate-limit awareness."""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from openai import OpenAI

from .config import ProviderConfig, get_available_providers

logger = logging.getLogger(__name__)


class ProviderRotation:
    """Round-robin LLM client across multiple free-tier providers.

    Tracks per-provider usage and automatically skips providers
    that have hit their daily rate limit.
    """

    def __init__(self, providers: Optional[List[ProviderConfig]] = None) -> None:
        self.providers = providers or get_available_providers()
        if not self.providers:
            raise ValueError(
                "No providers available. Set at least one API key:\n"
                "  GOOGLE_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY, or OPENROUTER_API_KEY"
            )
        self._index = 0
        self._daily_counts: dict[str, int] = {p.name: 0 for p in self.providers}
        self._last_reset: float = time.time()
        self._clients: dict[str, OpenAI] = {}

    def _maybe_reset_daily(self) -> None:
        """Reset daily counters if a new day has started."""
        now = time.time()
        if now - self._last_reset > 86400:
            self._daily_counts = {p.name: 0 for p in self.providers}
            self._last_reset = now

    def _get_client(self, provider: ProviderConfig) -> OpenAI:
        if provider.name not in self._clients:
            self._clients[provider.name] = OpenAI(
                api_key=provider.api_key,
                base_url=provider.base_url,
            )
        return self._clients[provider.name]

    def _pick_provider(self) -> ProviderConfig:
        """Pick next provider that hasn't hit its daily limit."""
        self._maybe_reset_daily()
        for _ in range(len(self.providers)):
            p = self.providers[self._index % len(self.providers)]
            self._index += 1
            if self._daily_counts[p.name] < p.rpd:
                return p
        # All providers exhausted — pick the one with most remaining
        best = max(self.providers, key=lambda p: p.rpd - self._daily_counts[p.name])
        logger.warning(
            "All providers near daily limit. Using %s (%d/%d used)",
            best.name, self._daily_counts[best.name], best.rpd,
        )
        return best

    def chat(
        self,
        messages: List[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion request with provider rotation.

        Returns the assistant message content.
        Retries once with a different provider on failure.
        """
        last_error: Optional[Exception] = None
        attempts = min(len(self.providers), 3)

        for _ in range(attempts):
            provider = self._pick_provider()
            client = self._get_client(provider)
            use_model = model or provider.model

            try:
                response = client.chat.completions.create(
                    model=use_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                self._daily_counts[provider.name] += 1
                # Handle cases where response content might be None
                choice = response.choices[0] if response.choices else None
                if choice is None or choice.message is None:
                    raise RuntimeError(f"Empty response from {provider.name}")
                content = choice.message.content or ""
                if not content:
                    raise RuntimeError(f"Empty content from {provider.name}")
                logger.debug(
                    "Provider %s responded (%d chars)",
                    provider.name, len(content),
                )
                return content
            except Exception as e:
                last_error = e
                logger.warning(
                    "Provider %s failed: %s. Retrying with next provider.",
                    provider.name, str(e)[:200],
                )
                self._daily_counts[provider.name] += 1  # count failed too

        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    @property
    def usage(self) -> dict[str, int]:
        """Current daily usage per provider."""
        return dict(self._daily_counts)

    @property
    def primary_provider(self) -> str:
        """Name of the current primary provider."""
        return self.providers[0].name
