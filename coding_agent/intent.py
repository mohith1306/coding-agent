from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Optional
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
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_model = os.getenv("CODING_AGENT_OPENROUTER_MODEL", "openrouter/auto")
        self.openrouter_fallback = (
            self.provider != "openrouter"
            and bool(self.openrouter_api_key)
            and self.openrouter_api_key not in {"your-openrouter-api-key-here", ""}
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

        if self.api_key in {"your-openai-api-key-here", "your-gemini-api-key-here", "your-groq-api-key-here"}:
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
                reason=f"Intent parser failed: {self._safe_error_message(error)}",
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
            if self.gemini_fallback:
                try:
                    logger.warning(
                        "Primary provider %s failed (%s); falling back to Gemini %s",
                        self.provider,
                        self._safe_error_message(error),
                        self.gemini_model,
                    )
                    return self._call_gemini_raw(
                        system_prompt,
                        user_message,
                        json_mode,
                        model=self.gemini_model,
                        api_key=self.gemini_api_key,
                    )
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as gemini_error:
                    error = gemini_error

            if self.openrouter_fallback:
                logger.warning(
                    "Fallback providers failed (%s); falling back to OpenRouter %s",
                    self._safe_error_message(error),
                    self.openrouter_model,
                )
                return self._call_openrouter_raw(
                    system_prompt,
                    user_message,
                    json_mode,
                    model=self.openrouter_model,
                    api_key=self.openrouter_api_key,
                )

            raise

    def _call_primary_raw(self, system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        if self.provider == "gemini":
            return self._call_gemini_raw(system_prompt, user_message, json_mode)

        if self.provider == "openai":
            return self._call_openai_raw(system_prompt, user_message, json_mode)

        if self.provider == "groq":
            return self._call_groq_raw(system_prompt, user_message, json_mode)

        if self.provider == "openrouter":
            return self._call_openrouter_raw(system_prompt, user_message, json_mode, model=self.model, api_key=self.api_key)

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

    def _call_groq(self, user_message: str) -> dict[str, object]:
        content = self._call_groq_raw(self.prompt_path.read_text(encoding="utf-8"), user_message, json_mode=True)
        parsed = json.loads(content)

        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")

        return parsed

    def _call_groq_raw(self, system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        logger.info("Calling Groq with model %s", self.model)
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
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
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
        if self.openrouter_fallback:
            logger.info("OpenRouter fallback enabled (model %s)", self.openrouter_model)

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

        return os.getenv("OPENAI_API_KEY", "")

    def _api_key_name(self) -> str:
        if self.provider == "gemini":
            return "GEMINI_API_KEY"

        if self.provider == "groq":
            return "GROQ_API_KEY"

        if self.provider == "openrouter":
            return "OPENROUTER_API_KEY"

        return "OPENAI_API_KEY"

    def _default_model(self) -> str:
        if self.provider == "gemini":
            return "gemini-2.0-flash"

        if self.provider == "groq":
            return "llama-3.1-8b-instant"

        if self.provider == "openrouter":
            return "nvidia/nemotron-3-super-120b-a12b:free"

        return "gpt-4o-mini"

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
