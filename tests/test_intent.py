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
    return parser


def test_llm_raw_falls_back_to_gemini_when_primary_fails() -> None:
    parser = _parser_with_fallback()
    calls = []

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
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

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        raise HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, None)

    with mock.patch.object(parser, "_call_groq_raw", fake_groq), mock.patch.object(parser, "_call_gemini_raw", mock.Mock(side_effect=AssertionError("must not be called"))):
        try:
            parser._call_llm_raw("system", "create files")
        except HTTPError as error:
            assert error.code == 429
        else:
            raise AssertionError("expected HTTPError to propagate")


def test_parse_returns_unknown_when_both_providers_fail() -> None:
    parser = _parser_with_fallback()

    def fake_groq(system_prompt: str, user_message: str, json_mode: bool = False) -> str:
        raise HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, None)

    def fake_gemini(system_prompt: str, user_message: str, json_mode: bool = False, model=None, api_key=None) -> str:
        raise HTTPError("https://generativelanguage.googleapis.com", 500, "Internal", {}, None)

    with mock.patch.object(parser, "_call_groq_raw", fake_groq), mock.patch.object(parser, "_call_gemini_raw", fake_gemini):
        intent = parser.parse("create a todo app")

    assert intent.name == "unknown"
    assert "Intent parser failed" in intent.reason
