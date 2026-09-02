"""Multi-provider LLM rotation with rate-limit awareness."""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from openai import OpenAI

from .config import ProviderConfig, get_available_providers

logger = logging.getLogger(__name__)


class ProviderRotation:
    def __init__(self, providers: Optional[List[ProviderConfig]] = None) -> None:
        self.providers = providers or get_available_providers()
        if not self.providers:
            raise ValueError("No providers available")
        self._index = 0
        self._daily_counts: dict[str, int] = {p.name: 0 for p in self.providers}
        self._last_reset: float = time.time()
        self._clients: dict[str, OpenAI] = {}

    def _maybe_reset_daily(self) -> None:
        now = time.time()
        if now - self._last_reset > 86400:
            self._daily_counts = {p.name: 0 for p in self.providers}
            self._last_reset = now

    def _get_client(self, provider: ProviderConfig) -> OpenAI:
        if provider.name not in self._clients:
            self._clients[provider.name] = OpenAI(
                api_key=provider.api_key, base_url=provider.base_url,
            )
        return self._clients[provider.name]

    def _pick_provider(self) -> ProviderConfig:
        self._maybe_reset_daily()
        for _ in range(len(self.providers)):
            p = self.providers[self._index % len(self.providers)]
            self._index += 1
            if self._daily_counts[p.name] < p.rpd:
                return p
        return max(self.providers, key=lambda p: p.rpd - self._daily_counts[p.name])

    def chat(self, messages: List[dict[str, str]], model: Optional[str] = None,
             temperature: float = 0.0, max_tokens: int = 4096, **kwargs: Any) -> str:
        last_error: Optional[Exception] = None
        for _ in range(min(len(self.providers), 3)):
            provider = self._pick_provider()
            client = self._get_client(provider)
            use_model = model or provider.model
            try:
                response = client.chat.completions.create(
                    model=use_model, messages=messages,
                    temperature=temperature, max_tokens=max_tokens, **kwargs,
                )
                self._daily_counts[provider.name] += 1
                choice = response.choices[0] if response.choices else None
                if choice is None or choice.message is None:
                    raise RuntimeError(f"Empty response from {provider.name}")
                content = choice.message.content or ""
                if not content:
                    raise RuntimeError(f"Empty content from {provider.name}")
                return content
            except Exception as e:
                last_error = e
                self._daily_counts[provider.name] += 1
        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    @property
    def usage(self) -> dict[str, int]:
        return dict(self._daily_counts)
