"""Provider configuration for free LLM APIs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    env_key: str
    model: str
    rpm: int
    rpd: int
    api_key: str = ""

    def __post_init__(self) -> None:
        self.api_key = os.environ.get(self.env_key, "")


PROVIDERS: List[ProviderConfig] = [
    ProviderConfig(
        name="google",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        env_key="GEMINI_API_KEY",
        model="gemini-3.6-flash",
        rpm=30, rpd=14400,
    ),
    ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        env_key="GROQ_API_KEY",
        model="qwen/qwen3.6-27b",
        rpm=30, rpd=1000,
    ),
    ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        env_key="OPENROUTER_API_KEY",
        model="minimax/minimax-m3:free",
        rpm=20, rpd=1000,
    ),
    ProviderConfig(
        name="openrouter_nvidia",
        base_url="https://openrouter.ai/api/v1",
        env_key="OPENROUTER_API_KEY",
        model="nvidia/nemotron-3-super-120b-a12b:free",
        rpm=20, rpd=1000,
    ),
]


def get_available_providers() -> List[ProviderConfig]:
    seen: set[str] = set()
    result: List[ProviderConfig] = []
    for p in PROVIDERS:
        key = f"{p.base_url}:{p.model}"
        if p.api_key and key not in seen:
            result.append(p)
            seen.add(key)
    return result


def get_total_rpd() -> int:
    return sum(p.rpd for p in get_available_providers())
