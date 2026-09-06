import base64
import json

import pytest

from server import provider_router as pr


class _Resp:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def _patch(monkeypatch, responses):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, timeout))
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return _Resp(value)

    monkeypatch.setattr(pr, "urlopen", fake_urlopen)
    return calls


def _configure(monkeypatch):
    monkeypatch.setenv("UCOA_GEMINI_API_KEY", "test")
    monkeypatch.delenv("UCOA_OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("UCOA_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("UCOA_CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("UCOA_GROQ_API_KEY", raising=False)
    for name, state in pr._BREAKERS.items():
        state.failures = 0
        state.opened_at = 0.0
    pr._VISION_CACHE.clear()


def test_gemini_text_call(monkeypatch):
    _configure(monkeypatch)
    calls = _patch(monkeypatch, [{"choices": [{"message": {"content": '{"ok":true}'}}]}])
    raw, provider = pr.call("system", "user")
    assert provider == "gemini"
    assert raw == '{"ok":true}'
    assert calls and "/chat/completions" in calls[0][0]


def test_failover_after_primary_error(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("UCOA_CEREBRAS_API_KEY", "test-c")
    # Text order is Cerebras -> Groq -> Gemini. Groq is unconfigured, so a
    # Cerebras failure falls through to Gemini.
    responses = [RuntimeError("boom"), {"choices": [{"message": {"content": "ok"}}]}]
    calls = _patch(monkeypatch, responses)
    raw, provider = pr.call("system", "user")
    assert raw == "ok"
    assert provider == "gemini"
    assert len(calls) == 2


def test_circuit_breaker_skips_open_provider(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("UCOA_CEREBRAS_API_KEY", "test-c")
    import time

    pr._BREAKERS["cerebras"].opened_at = time.monotonic()
    responses = [{"choices": [{"message": {"content": "ok"}}]}]
    calls = _patch(monkeypatch, responses)
    raw, provider = pr.call("system", "user")
    assert provider == "gemini"
    assert len(calls) == 1


def test_json_extraction():
    assert pr._extract_json("```json\n{\"a\":1}\n```") == {"a": 1}
    assert pr._extract_json("prefix {\"a\":2} suffix") == {"a": 2}
    with pytest.raises(ValueError):
        pr._extract_json("not json")


def test_vision_cache(monkeypatch):
    _configure(monkeypatch)
    image = base64.b64encode(b"fake-image").decode()
    body = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "screen_summary": "ok",
                                    "elements": [],
                                    "visible_goal_state": "x",
                                    "confidence": 0.9,
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }
    calls = _patch(monkeypatch, [body])
    first, p1 = pr.visual("task", "[]", image)
    second, p2 = pr.visual("task", "[]", image)
    assert first == second
    assert p1 == p2 == "gemini"
    assert len(calls) == 1
