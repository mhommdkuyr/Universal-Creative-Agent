from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "ucoa_autonomous_dev.py"
spec = importlib.util.spec_from_file_location("ucoa_autonomous_dev", MODULE_PATH)
assert spec and spec.loader
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def test_safe_target_allows_application_source():
    assert agent.safe_target("server/example.py").as_posix().endswith("server/example.py")
    assert agent.safe_target("tests/example.py").as_posix().endswith("tests/example.py")


def test_safe_target_rejects_workflows_and_traversal():
    for path in (".github/workflows/ci.yml", "../outside.py", "server/../outside.py"):
        try:
            agent.safe_target(path)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe path accepted: {path}")


def test_parse_full_file_edit_and_delete():
    response = (
        "===FILE tests/generated.py===\n"
        "def value():\n"
        "    return 7\n"
        "===END FILE tests/generated.py===\n"
        "===DELETE docs/old.txt==="
    )
    edits, deletes = agent.parse_edits(response)
    assert edits[next(p for p in edits if p.as_posix().endswith("tests/generated.py"))].startswith("def value")
    assert any(p.as_posix().endswith("docs/old.txt") for p in deletes)


def test_experiential_defaults_match_chat_completions_contract():
    assert agent.BASE_URL == "https://api.experientiallabs.ai/v1"
    assert agent.MODEL == "claude-fable-5.1"


def test_call_openai_uses_chat_completions_gateway(monkeypatch):
    monkeypatch.setenv("EXPLABS_API_KEY", "xpl_test_key")
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "===FILE tests/generated.py===\nvalue = 1\n===END FILE tests/generated.py==="}}]
            }).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(agent.urllib.request, "urlopen", fake_urlopen)
    result = agent.call_openai("Inspect this repository")

    assert result.startswith("===FILE tests/generated.py===")
    assert captured["url"] == "https://api.experientiallabs.ai/v1/chat/completions"
    assert captured["method"] == "POST"
    assert captured["authorization"] == "Bearer xpl_test_key"
    assert captured["timeout"] == 180
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "claude-fable-5.1"
    assert body["stream"] is False
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "Inspect this repository"
    assert body["max_tokens"] == 16000
