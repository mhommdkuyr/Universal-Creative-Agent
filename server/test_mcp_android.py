import asyncio
import os
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

os.environ.setdefault("UCOA_MCP_TOKEN", "test-mcp-token")

import mcp_android  # noqa: E402


def rpc(method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return asyncio.run(mcp_android.handle_rpc(message))


def test_mcp_initialize_modern_protocol():
    result = rpc(
        "initialize",
        {
            "protocolVersion": "2026-07-28",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        },
    )
    assert result["jsonrpc"] == "2.0"
    assert result["result"]["protocolVersion"] == "2026-07-28"
    assert result["result"]["serverInfo"]["name"]


def test_mcp_server_discover():
    result = rpc("server/discover")
    assert result["result"]["protocolVersion"] == "2026-07-28"
    assert result["result"]["capabilities"]["tools"]["listChanged"] is False


def test_mcp_tools_list_exposes_android_contract():
    result = rpc("tools/list")
    names = {tool["name"] for tool in result["result"]["tools"]}
    assert names == {
        "android_devices",
        "android_run_task",
        "android_task_status",
        "android_wait_task",
    }

    run_task = next(t for t in result["result"]["tools"] if t["name"] == "android_run_task")
    assert run_task["inputSchema"]["required"] == ["task"]
    assert run_task["annotations"]["readOnlyHint"] is False


def test_mcp_auth_constant_time_helper():
    assert mcp_android._authorized("Bearer test-mcp-token") is True
    assert mcp_android._authorized("Bearer wrong-token") is False
    assert mcp_android._authorized(None) is False


def test_unknown_method_is_jsonrpc_error():
    result = rpc("not/a/method")
    assert result["error"]["code"] == -32601


@pytest.mark.parametrize("protocol", ["2026-07-28", "2025-11-25", "unknown"])
def test_initialize_never_returns_unsupported_protocol(protocol):
    result = rpc("initialize", {"protocolVersion": protocol})
    assert result["result"]["protocolVersion"] in mcp_android.SUPPORTED_PROTOCOLS
