import json
from unittest import mock

from urllib.error import HTTPError

from coding_agent.intent import IntentParser


def test_parser_loads_env_from_parent_directory(monkeypatch, tmp_path) -> None:
    root = tmp_path / "project"
    child = root / "web" / "backend"
    child.mkdir(parents=True)
    (root / ".env").write_text(
        "OPENROUTER_API_KEY=sk-or-v1-test\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(child)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    parser = IntentParser()

    assert parser.api_key == "sk-or-v1-test"


def test_parser_returns_unknown_when_no_api_key() -> None:
    parser = IntentParser()
    parser.api_key = ""

    intent = parser.parse("create a file")

    assert intent.name == "unknown"
    assert "OPENROUTER_API_KEY is not set" in intent.reason


def test_parser_returns_unknown_when_placeholder_key() -> None:
    parser = IntentParser()
    parser.api_key = "your-openrouter-api-key-here"

    intent = parser.parse("create a file")

    assert intent.name == "unknown"
    assert "placeholder" in intent.reason


def test_parse_returns_intent_on_success() -> None:
    parser = IntentParser()
    parser.api_key = "sk-or-v1-test"

    def fake_call(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        return json.dumps({"intent": "create_file", "target": "test.py", "confidence": 0.9})

    with mock.patch.object(parser, "_call_openrouter_raw", fake_call):
        intent = parser.parse("create test.py")

    assert intent.name == "create_file"
    assert intent.target == "test.py"


def test_parse_returns_unknown_on_http_error() -> None:
    parser = IntentParser()
    parser.api_key = "sk-or-v1-test"

    def fake_call(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        raise HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)

    with mock.patch.object(parser, "_call_openrouter_raw", fake_call):
        intent = parser.parse("create a file")

    assert intent.name == "unknown"
    assert "rate-limited" in intent.reason


def test_parse_includes_recent_history_in_system_prompt() -> None:
    parser = IntentParser()
    parser.api_key = "sk-or-v1-test"
    captured = {}

    def fake_call(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        captured["system_prompt"] = system_prompt
        return json.dumps({"intent": "explain", "confidence": 0.9})

    with mock.patch.object(parser, "_call_openrouter_raw", fake_call):
        parser.parse(
            "what does this do?",
            history=[{"user": "tell me about this project", "agent": "This is a Python app..."}],
        )

    assert "Recent conversation context" in captured["system_prompt"]
    assert "tell me about this project" in captured["system_prompt"]


def test_parse_ignores_empty_history() -> None:
    parser = IntentParser()
    parser.api_key = "sk-or-v1-test"
    captured = {}

    def fake_call(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        captured["system_prompt"] = system_prompt
        return json.dumps({"intent": "explain", "confidence": 0.9})

    with mock.patch.object(parser, "_call_openrouter_raw", fake_call):
        parser.parse("what does this do?", history=[])

    assert "Recent conversation context" not in captured["system_prompt"]


def test_generate_calls_openrouter() -> None:
    parser = IntentParser()
    parser.api_key = "sk-or-v1-test"
    captured = {}

    def fake_call(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        captured["system_prompt"] = system_prompt
        captured["user_message"] = user_message
        return "Generated code content"

    with mock.patch.object(parser, "_call_openrouter_raw", fake_call):
        result = parser.generate("You are a code generator", "create a hello world script")

    assert result == "Generated code content"
    assert captured["system_prompt"] == "You are a code generator"
    assert captured["user_message"] == "create a hello world script"


def test_stream_yields_chunks() -> None:
    parser = IntentParser()
    parser.api_key = "sk-or-v1-test"
    chunks = ["Hel", "lo", " world"]

    def fake_stream(system_prompt: str, user_message: str):
        yield from chunks

    with mock.patch.object(parser, "_stream_openrouter_raw", fake_stream):
        result = list(parser.stream("system", "hi"))

    assert result == chunks


def test_stream_falls_back_to_non_streaming_on_failure() -> None:
    parser = IntentParser()
    parser.api_key = "sk-or-v1-test"
    calls = []

    def fake_stream(system_prompt: str, user_message: str):
        raise HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)

    def fake_nonstream(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        calls.append("nonstream")
        return "fallback answer"

    with mock.patch.object(parser, "_stream_openrouter_raw", fake_stream), mock.patch.object(parser, "_call_openrouter_raw", fake_nonstream):
        result = list(parser.stream("system", "hi"))

    assert result == ["fallback answer"]
    assert calls == ["nonstream"]


def test_stream_reraises_after_partial_output() -> None:
    parser = IntentParser()
    parser.api_key = "sk-or-v1-test"

    def fake_stream(system_prompt: str, user_message: str):
        yield "partial"
        raise HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)

    with mock.patch.object(parser, "_stream_openrouter_raw", fake_stream):
        try:
            list(parser.stream("system", "hi"))
        except HTTPError:
            pass
        else:
            raise AssertionError("expected HTTPError to propagate after partial output")
