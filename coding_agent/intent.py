from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Callable, Iterator, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Intent:
    name: str
    target: str = ""
    args: Optional[dict[str, object]] = None
    confidence: float = 0.0
    requires_confirmation: bool = False
    reason: str = ""
    raw_message: str = ""


class IntentParser:
    """Parses coding-agent requests with an LLM."""

    def __init__(self) -> None:
        dotenv_path = Path.cwd() / ".env"
        self._load_dotenv(dotenv_path)
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()
        self.model = os.getenv(
            "CODING_AGENT_INTENT_MODEL"
            if self.provider != "openrouter"
            else "CODING_AGENT_OPENROUTER_MODEL",
            self._default_model(),
        )
        self.api_key = self._api_key_for_provider()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("CODING_AGENT_GEMINI_MODEL", "gemini-2.0-flash")
        self.gemini_fallback = (
            self.provider != "gemini"
            and bool(self.gemini_api_key)
            and self.gemini_api_key not in {"your-gemini-api-key-here", ""}
        )
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_model = os.getenv("CODING_AGENT_GROQ_MODEL", "llama-3.3-70b-versatile")
        self.groq_fallback = (
            self.provider != "groq"
            and bool(self.groq_api_key)
            and self.groq_api_key not in {"your-groq-api-key-here", ""}
        )
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_model = os.getenv("CODING_AGENT_OPENROUTER_MODEL", "openrouter/auto")
        self.openrouter_fallback = (
            self.provider != "openrouter"
            and bool(self.openrouter_api_key)
            and self.openrouter_api_key not in {"your-openrouter-api-key-here", ""}
        )
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.deepseek_model = os.getenv("CODING_AGENT_DEEPSEEK_MODEL", "deepseek-chat")
        self.deepseek_fallback = (
            self.provider != "deepseek"
            and bool(self.deepseek_api_key)
            and self.deepseek_api_key not in {"your-deepseek-api-key-here", ""}
        )
        self.max_tokens = int(os.getenv("CODING_AGENT_MAX_TOKENS", "2048"))
        self.prompt_path = Path(__file__).parent / "prompts" / "intent_system_prompt.md"
        self._log_configuration(dotenv_path)

    def parse(self, user_message: str) -> Intent:
        if not self.api_key:
            return Intent(
                name="unknown",
                confidence=0.0,
                reason=f"{self._api_key_name()} is not set. Add it to .env before using the LLM intent parser.",
                raw_message=user_message,
            )

        if self.api_key in {"your-openai-api-key-here", "your-gemini-api-key-here", "your-groq-api-key-here", "your-deepseek-api-key-here"}:
            return Intent(
                name="unknown",
                confidence=0.0,
                reason=f"{self._api_key_name()} still contains the placeholder value in .env.",
                raw_message=user_message,
            )

        try:
            parsed = self._call_llm(user_message)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as error:
            return Intent(
                name="unknown",
                confidence=0.0,
                reason=self._failure_reason(error),
                raw_message=user_message,
            )

        return Intent(
            name=str(parsed.get("intent", "unknown")),
            target=str(parsed.get("target", "")),
            args=parsed.get("args") if isinstance(parsed.get("args"), dict) else {},
            confidence=float(parsed.get("confidence", 0.0)),
            requires_confirmation=bool(parsed.get("requires_confirmation", False)),
            reason=str(parsed.get("reason", "")),
            raw_message=user_message,
        )

    def generate(self, system_prompt: str, user_message: str) -> str:
        logger.info("Generating content with model %s", self.model)
        return self._call_llm_raw(system_prompt, user_message, json_mode=False)

    def stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        """Yield text chunks as they arrive from the primary provider.

        If the streaming call fails before producing any content, falls back to
        the non-streaming chain (including Gemini/OpenRouter fallbacks).
        """
        emitted = False
        try:
            for chunk in self._stream_primary_raw(system_prompt, user_message):
                if chunk:
                    emitted = True
                    yield chunk
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as error:
            if emitted:
                raise
            logger.warning(
                "Streaming failed (%s); falling back to non-streaming response",
                self._safe_error_message(error),
            )
            yield self._call_llm_raw(system_prompt, user_message, json_mode=False)

    def _stream_primary_raw(self, system_prompt: str, user_message: str) -> Iterator[str]:
        if self.provider == "gemini":
            yield from self._stream_gemini_raw(system_prompt, user_message)
            return

        yield from self._stream_openai_compatible_raw(system_prompt, user_message)

    def _stream_openai_compatible_raw(self, system_prompt: str, user_message: str) -> Iterator[str]:
        url, headers = self._openai_compatible_target()
        logger.info("Streaming from %s with model %s", self.provider, self.model)
        payload: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urlopen(request, timeout=120) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, json.JSONDecodeError):
                    delta = None
                if delta:
                    yield delta

    def _openai_compatible_target(self) -> tuple[str, dict[str, str]]:
        if self.provider == "groq":
            return (
                "https://api.groq.com/openai/v1/chat/completions",
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "CodingAgent/0.1",
                },
            )

        if self.provider == "deepseek":
            return (
                "https://api.deepseek.com/chat/completions",
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )

        if self.provider == "openai":
            return (
                "https://api.openai.com/v1/chat/completions",
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )

        return (
            "https://openrouter.ai/api/v1/chat/completions",
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/mohith1306/coding-agent",
                "X-Title": "Coding Agent",
            },
        )

    def _stream_gemini_raw(self, system_prompt: str, user_message: str) -> Iterator[str]:
        model = self.model
        api_key = self.api_key
        logger.info("Streaming from Gemini with model %s", model)
        payload: dict[str, object] = {
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_message}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self.max_tokens,
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={api_key}"
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request, timeout=120) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if not data:
                    continue
                try:
                    parts = json.loads(data)["candidates"][0]["content"]["parts"]
                    text = "".join(p.get("text", "") for p in parts)
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    text = ""
                if text:
                    yield text

    def _call_llm(self, user_message: str) -> dict[str, object]:
        system_prompt = self.prompt_path.read_text(encoding="utf-8")
        content = self._call_llm_raw(system_prompt, user_message, json_mode=True)
        parsed = json.loads(content)

        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")

        return parsed

    def _call_llm_raw(self, system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        try:
            return self._call_primary_raw(system_prompt, user_message, json_mode)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as error:
            for name, call in self._fallback_calls():
                try:
                    logger.warning(
                        "Fallback provider %s (reason: %s)",
                        name,
                        self._safe_error_message(error),
                    )
                    return call(system_prompt, user_message, json_mode)
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as fallback_error:
                    error = fallback_error
            raise

    def _fallback_calls(self) -> list[tuple[str, Callable]]:
        calls = []
        if self.gemini_fallback:
            calls.append(
                (
                    "Gemini",
                    lambda sp, um, jm: self._call_gemini_raw(
                        sp, um, jm, model=self.gemini_model, api_key=self.gemini_api_key
                    ),
                )
            )
        if self.groq_fallback:
            calls.append(
                (
                    "Groq",
                    lambda sp, um, jm: self._call_groq_raw(
                        sp, um, jm, model=self.groq_model, api_key=self.groq_api_key
                    ),
                )
            )
        if self.openrouter_fallback:
            calls.append(
                (
                    "OpenRouter",
                    lambda sp, um, jm: self._call_openrouter_raw(
                        sp, um, jm, model=self.openrouter_model, api_key=self.openrouter_api_key
                    ),
                )
            )
        if self.deepseek_fallback:
            calls.append(
                (
                    "DeepSeek",
                    lambda sp, um, jm: self._call_deepseek_raw(
                        sp, um, jm, model=self.deepseek_model, api_key=self.deepseek_api_key
                    ),
                )
            )
        return calls

    def _call_primary_raw(self, system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        if self.provider == "gemini":
            return self._call_gemini_raw(system_prompt, user_message, json_mode)

        if self.provider == "openai":
            return self._call_openai_raw(system_prompt, user_message, json_mode)

        if self.provider == "groq":
            return self._call_groq_raw(system_prompt, user_message, json_mode)

        if self.provider == "openrouter":
            return self._call_openrouter_raw(system_prompt, user_message, json_mode, model=self.model, api_key=self.api_key)

        if self.provider == "deepseek":
            return self._call_deepseek_raw(system_prompt, user_message, json_mode)

        raise ValueError(f"Unsupported LLM_PROVIDER: {self.provider}")

    def _call_openai(self, user_message: str) -> dict[str, object]:
        content = self._call_openai_raw(self.prompt_path.read_text(encoding="utf-8"), user_message)
        parsed = json.loads(content)

        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")

        return parsed

    def _call_openai_raw(self, system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        logger.info("Calling OpenAI with model %s", self.model)
        payload: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))

        logger.info("OpenAI returned a response")
        return body["choices"][0]["message"]["content"]

    def _call_openrouter_raw(self, system_prompt: str, user_message: str, json_mode: bool = False, model: Optional[str] = None, api_key: Optional[str] = None) -> str:
        model = model or self.model
        api_key = api_key or self.api_key
        logger.info("Calling OpenRouter with model %s", model)
        payload: dict[str, object] = {
            "model": model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/mohith1306/coding-agent",
                "X-Title": "Coding Agent",
            },
            method="POST",
        )

        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))

        logger.info("OpenRouter returned a response")
        return body["choices"][0]["message"]["content"]

    def _call_deepseek_raw(self, system_prompt: str, user_message: str, json_mode: bool = False, model: Optional[str] = None, api_key: Optional[str] = None) -> str:
        model = model or self.model
        api_key = api_key or self.api_key
        logger.info("Calling DeepSeek with model %s", model)
        payload: dict[str, object] = {
            "model": model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))

        logger.info("DeepSeek returned a response")
        return body["choices"][0]["message"]["content"]

    def _call_groq(self, user_message: str) -> dict[str, object]:
        content = self._call_groq_raw(self.prompt_path.read_text(encoding="utf-8"), user_message, json_mode=True)
        parsed = json.loads(content)

        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")

        return parsed

    def _call_groq_raw(self, system_prompt: str, user_message: str, json_mode: bool = False, model: Optional[str] = None, api_key: Optional[str] = None) -> str:
        model = model or self.model
        api_key = api_key or self.api_key
        logger.info("Calling Groq with model %s", model)
        payload: dict[str, object] = {
            "model": model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "CodingAgent/0.1",
            },
            method="POST",
        )

        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))

        logger.info("Groq returned a response")
        return body["choices"][0]["message"]["content"]

    def _call_gemini(self, user_message: str) -> dict[str, object]:
        content = self._call_gemini_raw(self.prompt_path.read_text(encoding="utf-8"), user_message, json_mode=True)
        parsed = json.loads(content)

        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")

        return parsed

    def _call_gemini_raw(self, system_prompt: str, user_message: str, json_mode: bool = False, model: Optional[str] = None, api_key: Optional[str] = None) -> str:
        model = model or self.model
        api_key = api_key or self.api_key
        logger.info("Calling Gemini with model %s", model)
        payload: dict[str, object] = {
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_message}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self.max_tokens,
            },
        }
        if json_mode:
            payload["generationConfig"]["response_mime_type"] = "application/json"  # type: ignore[attr-defined]
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))

        logger.info("Gemini returned a response")
        return body["candidates"][0]["content"]["parts"][0]["text"]

    def _load_dotenv(self, path: Path) -> None:
        if not path.is_file():
            logger.warning(".env file not found at %s", path)
            return

        logger.info("Loading environment variables from %s", path)

        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()

            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            os.environ.setdefault(key, value)

    def _log_configuration(self, dotenv_path: Path) -> None:
        logger.info("Intent parser provider: %s", self.provider)
        logger.info("Intent parser model: %s", self.model)
        if self.gemini_fallback:
            logger.info("Gemini fallback enabled (model %s)", self.gemini_model)
        if self.groq_fallback:
            logger.info("Groq fallback enabled (model %s)", self.groq_model)
        if self.openrouter_fallback:
            logger.info("OpenRouter fallback enabled (model %s)", self.openrouter_model)
        if self.deepseek_fallback:
            logger.info("DeepSeek fallback enabled (model %s)", self.deepseek_model)

        key_name = self._api_key_name()
        source = f"{dotenv_path.name} or an env var" if dotenv_path.is_file() else "an env var"
        if not self.api_key:
            logger.warning("%s is not set (provide it via %s)", key_name, source)
            return

        if self.api_key in {
            "your-openai-api-key-here",
            "your-gemini-api-key-here",
            "your-groq-api-key-here",
            "your-openrouter-api-key-here",
            "your-deepseek-api-key-here",
        }:
            logger.warning("%s is present but still uses the placeholder value", key_name)
            return

        logger.info("%s is configured", key_name)

    def _api_key_for_provider(self) -> str:
        if self.provider == "gemini":
            return os.getenv("GEMINI_API_KEY", "")

        if self.provider == "groq":
            return os.getenv("GROQ_API_KEY", "")

        if self.provider == "openrouter":
            return os.getenv("OPENROUTER_API_KEY", "")

        if self.provider == "deepseek":
            return os.getenv("DEEPSEEK_API_KEY", "")

        return os.getenv("OPENAI_API_KEY", "")

    def _api_key_name(self) -> str:
        if self.provider == "gemini":
            return "GEMINI_API_KEY"

        if self.provider == "groq":
            return "GROQ_API_KEY"

        if self.provider == "openrouter":
            return "OPENROUTER_API_KEY"

        if self.provider == "deepseek":
            return "DEEPSEEK_API_KEY"

        return "OPENAI_API_KEY"

    def _default_model(self) -> str:
        if self.provider == "gemini":
            return "gemini-2.0-flash"

        if self.provider == "groq":
            return "llama-3.1-8b-instant"

        if self.provider == "openrouter":
            return "nvidia/nemotron-3-super-120b-a12b:free"

        if self.provider == "deepseek":
            return "deepseek-chat"

        return "gpt-4o-mini"

    def _failure_reason(self, error: Exception) -> str:
        if isinstance(error, HTTPError) and error.code == 429:
            return (
                "All LLM providers are currently rate-limited (HTTP 429). "
                "The free-tier daily quota may be exhausted. Wait for the daily reset "
                "or add credits to a provider (e.g. $10 on OpenRouter unlocks 1000 "
                "free-model requests/day), then try again."
            )
        return f"Intent parser failed: {self._safe_error_message(error)}"

    def _safe_error_message(self, error: Exception) -> str:
        if isinstance(error, HTTPError):
            try:
                body = error.read().decode("utf-8", errors="replace")
                return f"HTTP Error {error.code}: {body}"
            except Exception:
                return f"HTTP Error {error.code}"
            finally:
                try:
                    error.close()
                except Exception:
                    pass

        return str(error)
