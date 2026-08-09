import json
from unittest import mock

from urllib.error import HTTPError

from coding_agent.intent import IntentParser


def _parser_with_fallback() -> IntentParser:
    parser = IntentParser()
    parser.provider = "groq"
    parser.api_key = "gsk_test"
    parser.model = "llama-3.3-70b-versatile"
    parser.gemini_api_key = "fake-gemini-key"
    parser.gemini_model = "gemini-2.0-flash"
    parser.gemini_fallback = True
    parser.openrouter_api_key = "sk-or-v1-fake"
    parser.openrouter_model = "openrouter/auto"
    parser.openrouter_fallback = True
    parser.groq_api_key = "gsk_test"
    parser.groq_model = "llama-3.3-70b-versatile"
    parser.groq_fallback = False
    parser.deepseek_api_key = "sk-deep-fake"
    parser.deepseek_model = "deepseek-chat"
    parser.deepseek_fallback = False
    return parser


def test_llm_raw_falls_back_to_gemini_when_primary_fails() -> None:
    parser = _parser_with_fallback()
    calls = []

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append("groq")
        raise HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, None)

    def fake_gemini(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append(("gemini", model, api_key))
        return json.dumps({"intent": "create_files", "target": "x", "confidence": 0.9})

    with mock.patch.object(parser, "_call_groq_raw", fake_groq), mock.patch.object(parser, "_call_gemini_raw", fake_gemini):
        result = parser._call_llm_raw("system", "create files", json_mode=True)

    assert calls == ["groq", ("gemini", "gemini-2.0-flash", "fake-gemini-key")]
    assert json.loads(result)["intent"] == "create_files"


def test_no_fallback_when_gemini_key_absent() -> None:
    parser = _parser_with_fallback()
    parser.gemini_fallback = False
    parser.openrouter_fallback = False

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        raise HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, None)

    with mock.patch.object(parser, "_call_groq_raw", fake_groq), mock.patch.object(parser, "_call_gemini_raw", mock.Mock(side_effect=AssertionError("must not be called"))), mock.patch.object(parser, "_call_openrouter_raw", mock.Mock(side_effect=AssertionError("must not be called"))):
        try:
            parser._call_llm_raw("system", "create files")
        except HTTPError as error:
            assert error.code == 429
        else:
            raise AssertionError("expected HTTPError to propagate")


def test_falls_back_to_openrouter_when_gemini_also_fails() -> None:
    parser = _parser_with_fallback()
    calls = []

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append("groq")
        raise HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, None)

    def fake_gemini(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append("gemini")
        raise HTTPError("https://generativelanguage.googleapis.com", 429, "Too Many Requests", {}, None)

    def fake_openrouter(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append(("openrouter", model, api_key))
        return json.dumps({"intent": "create_project", "target": "todo-app", "confidence": 0.9})

    with mock.patch.object(parser, "_call_groq_raw", fake_groq), mock.patch.object(parser, "_call_gemini_raw", fake_gemini), mock.patch.object(parser, "_call_openrouter_raw", fake_openrouter):
        result = parser._call_llm_raw("system", "build a todo app", json_mode=True)

    assert calls == ["groq", "gemini", ("openrouter", "openrouter/auto", "sk-or-v1-fake")]
    assert json.loads(result)["intent"] == "create_project"


def test_no_openrouter_when_only_gemini_configured() -> None:
    parser = _parser_with_fallback()
    parser.openrouter_fallback = False
    calls = []

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append("groq")
        raise HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, None)

    def fake_gemini(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append("gemini")
        return json.dumps({"intent": "create_file", "target": "x", "confidence": 0.9})

    with mock.patch.object(parser, "_call_groq_raw", fake_groq), mock.patch.object(parser, "_call_gemini_raw", fake_gemini), mock.patch.object(parser, "_call_openrouter_raw", mock.Mock(side_effect=AssertionError("must not be called"))):
        result = parser._call_llm_raw("system", "create files")

    assert calls == ["groq", "gemini"]


def test_falls_back_to_deepseek_when_openrouter_also_fails() -> None:
    parser = _parser_with_fallback()
    parser.deepseek_fallback = True
    calls = []

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append("groq")
        raise HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, None)

    def fake_gemini(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append("gemini")
        raise HTTPError("https://generativelanguage.googleapis.com", 429, "Too Many Requests", {}, None)

    def fake_openrouter(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append("openrouter")
        raise HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)

    def fake_deepseek(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        calls.append(("deepseek", model, api_key))
        return json.dumps({"intent": "create_file", "target": "x", "confidence": 0.9})

    with mock.patch.object(parser, "_call_groq_raw", fake_groq), mock.patch.object(parser, "_call_gemini_raw", fake_gemini), mock.patch.object(parser, "_call_openrouter_raw", fake_openrouter), mock.patch.object(parser, "_call_deepseek_raw", fake_deepseek):
        result = parser._call_llm_raw("system", "create files")

    assert calls == ["groq", "gemini", "openrouter", ("deepseek", "deepseek-chat", "sk-deep-fake")]
    assert json.loads(result)["intent"] == "create_file"


def test_parse_returns_unknown_when_both_providers_fail() -> None:
    parser = _parser_with_fallback()

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        raise HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, None)

    def fake_gemini(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        raise HTTPError("https://generativelanguage.googleapis.com", 500, "Internal", {}, None)

    with mock.patch.object(parser, "_call_groq_raw", fake_groq), mock.patch.object(parser, "_call_gemini_raw", fake_gemini):
        intent = parser.parse("create a todo app")

    assert intent.name == "unknown"
    assert "rate-limited" in intent.reason


def test_stream_yields_chunks_from_openai_compatible_provider() -> None:
    parser = _parser_with_fallback()
    parser.provider = "openrouter"
    parser.api_key = "sk-or-v1-fake"
    parser.model = "nvidia/nemotron-3-super-120b-a12b:free"
    chunks = ["Hel", "lo", " world"]

    def fake_stream(system_prompt: str, user_message: str):
        yield from chunks

    with mock.patch.object(parser, "_stream_openai_compatible_raw", fake_stream):
        result = list(parser.stream("system", "hi"))

    assert result == chunks


def test_stream_falls_back_to_non_streaming_on_failure() -> None:
    parser = _parser_with_fallback()
    calls = []

    def fake_stream(system_prompt: str, user_message: str):
        raise HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)

    def fake_nonstream(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        calls.append("nonstream")
        return "fallback answer"

    with mock.patch.object(parser, "_stream_openai_compatible_raw", fake_stream), mock.patch.object(parser, "_call_llm_raw", fake_nonstream):
        result = list(parser.stream("system", "hi"))

    assert result == ["fallback answer"]
    assert calls == ["nonstream"]


def test_stream_reraises_after_partial_output() -> None:
    parser = _parser_with_fallback()

    def fake_stream(system_prompt: str, user_message: str):
        yield "partial"
        raise HTTPError("https://openrouter.ai", 429, "Too Many Requests", {}, None)

    with mock.patch.object(parser, "_stream_openai_compatible_raw", fake_stream), mock.patch.object(parser, "_call_llm_raw", mock.Mock(side_effect=AssertionError("must not fall back after partial output"))):
        try:
            list(parser.stream("system", "hi"))
        except HTTPError:
            pass
        else:
            raise AssertionError("expected HTTPError to propagate after partial output")
