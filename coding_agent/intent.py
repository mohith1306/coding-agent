from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Iterator, Optional
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
    """Parses coding-agent requests with an LLM via OpenRouter only."""

    def __init__(self, model: str = "") -> None:
        dotenv_path = self._find_dotenv_path()
        self._load_dotenv(dotenv_path)
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.model = model or os.getenv("CODING_AGENT_OPENROUTER_MODEL", "openrouter/auto")
        self.max_tokens = int(os.getenv("CODING_AGENT_MAX_TOKENS", "2048"))
        self.prompt_path = Path(__file__).parent / "prompts" / "intent_system_prompt.md"
        self._log_configuration(dotenv_path)

    def _find_dotenv_path(self) -> Path:
        """Find .env in CWD ancestry first, then in package ancestry."""
        cwd = Path.cwd().resolve()
        for candidate_dir in (cwd, *cwd.parents):
            candidate = candidate_dir / ".env"
            if candidate.is_file():
                return candidate

        module_dir = Path(__file__).resolve().parent
        for candidate_dir in (module_dir, *module_dir.parents):
            candidate = candidate_dir / ".env"
            if candidate.is_file():
                return candidate

        return cwd / ".env"

    def parse(self, user_message: str, history: Optional[list[dict[str, str]]] = None) -> Intent:
        if not self.api_key:
            return Intent(
                name="unknown",
                confidence=0.0,
                reason="OPENROUTER_API_KEY is not set. Add it to .env before using the LLM intent parser.",
                raw_message=user_message,
            )

        if self.api_key in {"your-openrouter-api-key-here", ""}:
            return Intent(
                name="unknown",
                confidence=0.0,
                reason="OPENROUTER_API_KEY still contains the placeholder value in .env.",
                raw_message=user_message,
            )

        try:
            parsed = self._call_llm(user_message, history=history)
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
        return self._call_openrouter_raw(system_prompt, user_message, json_mode=False)

    def stream(self, system_prompt: str, user_message: str) -> Iterator[str]:
        """Yield text chunks as they arrive from OpenRouter.

        If the streaming call fails before producing any content, falls back to
        the non-streaming response.
        """
        emitted = False
        try:
            for chunk in self._stream_openrouter_raw(system_prompt, user_message):
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
            yield self._call_openrouter_raw(system_prompt, user_message, json_mode=False)

    def _stream_openrouter_raw(self, system_prompt: str, user_message: str) -> Iterator[str]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/mohith1306/coding-agent",
            "X-Title": "Coding Agent",
        }
        logger.info("Streaming from OpenRouter with model %s", self.model)
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

    def _call_llm(self, user_message: str, history: Optional[list[dict[str, str]]] = None) -> dict[str, object]:
        system_prompt = self.prompt_path.read_text(encoding="utf-8")
        if history:
            history_block = self._format_history(history)
            system_prompt = f"{system_prompt}\n\nRecent conversation context:\n{history_block}"
        content = self._call_openrouter_raw(system_prompt, user_message, json_mode=True)
        parsed = json.loads(content)

        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")

        return parsed

    def _format_history(self, history: list[dict[str, str]]) -> str:
        lines = []
        for entry in history[-6:]:
            user = str(entry.get("user", "")).strip()
            agent = str(entry.get("agent", "")).strip()
            if not user:
                continue
            lines.append(f"User: {user}")
            if agent:
                lines.append(f"Agent: {agent[:500]}")
        return "\n".join(lines) if lines else ""

    def _call_openrouter_raw(self, system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        logger.info("Calling OpenRouter with model %s", self.model)
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
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
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

            if key not in os.environ or not os.environ.get(key, "").strip():
                os.environ[key] = value

    def _log_configuration(self, dotenv_path: Path) -> None:
        logger.info("Intent parser provider: openrouter")
        logger.info("Intent parser model: %s", self.model)

        source = f"{dotenv_path.name} or an env var" if dotenv_path.is_file() else "an env var"
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY is not set (provide it via %s)", source)
            return

        if self.api_key in {"your-openrouter-api-key-here", ""}:
            logger.warning("OPENROUTER_API_KEY is present but still uses the placeholder value")
            return

        logger.info("OPENROUTER_API_KEY is configured")

    def _failure_reason(self, error: Exception) -> str:
        if isinstance(error, HTTPError) and error.code == 429:
            return (
                "OpenRouter is currently rate-limited (HTTP 429). "
                "The free-tier daily quota may be exhausted. Wait for the daily reset "
                "or add credits to OpenRouter, then try again."
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
