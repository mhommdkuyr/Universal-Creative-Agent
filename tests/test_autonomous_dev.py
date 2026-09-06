from __future__ import annotations

import importlib.util
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
