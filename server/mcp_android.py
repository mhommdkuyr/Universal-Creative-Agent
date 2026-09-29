from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
from typing import Any

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

import app_v3
from device_bridge import (
    DB_PATH,
    _active_device_ids,
    _ensure_schema,
    _insert_command,
    _preferred_active_device_id,
)
from remote_ops import _pg_conn

# MCP compatibility: ChatGPT connects to remote MCP servers. Support the modern
# 2026 protocol shape plus the 2025 handshake used by older clients.
MODERN_PROTOCOL = "2026-07-28"
LEGACY_PROTOCOL = "2025-11-25"
SUPPORTED_PROTOCOLS = (MODERN_PROTOCOL, LEGACY_PROTOCOL)

SERVER_NAME = os.getenv("UCOA_MCP_SERVER_NAME", "UCOA Android Control")
SERVER_VERSION = os.getenv("UCOA_MCP_SERVER_VERSION", "1.0.0")


TOOLS: list[dict[str, Any]] = [
    {
        "name": "android_devices",
        "description": "List connected UCOA Android devices that have recently checked in. Does not expose session tokens.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "android_run_task",
        "description": "Execute an explicit user-requested task on a connected Android phone through UCOA AccessibilityService. The Android client observes the UI before and after actions and reports verification evidence. Use this for real device actions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "minLength": 1, "maxLength": 8000},
                "install_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 120, "default": 5},
                "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
            },
            "required": ["task"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "android_task_status",
        "description": "Read the current status and result evidence for an Android task previously queued through UCOA.",
        "inputSchema": {
            "type": "object",
            "properties": {"command_id": {"type": "string", "minLength": 8, "maxLength": 128}},
            "required": ["command_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "android_wait_task",
        "description": "Wait for an Android task to reach a terminal state, returning the final execution result or a pending snapshot when the timeout is reached.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command_id": {"type": "string", "minLength": 8, "maxLength": 128},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
            },
            "required": ["command_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
]


def _expected_token() -> str:
    # Prefer a dedicated MCP secret. Falling back to the existing master token keeps
    # the deployment compatible until a dedicated secret is added in Render.
    return os.getenv("UCOA_MCP_TOKEN", "").strip() or os.getenv("UCOA_AGENT_TOKEN", "").strip()


def _authorized(authorization: str | None) -> bool:
    expected = _expected_token()
    if not expected or not authorization or not authorization.startswith("Bearer "):
        return False
    supplied = authorization[7:].strip()
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _jsonrpc_error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return {
        "content": [{"type": "text", "text": payload}],
        "structuredContent": {"result": value},
        "isError": is_error,
    }


def _active_device_details() -> list[dict[str, Any]]:
    _ensure_schema()
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT install_id, device, app_version, last_seen_at "
                        "FROM ucoa_client_sessions WHERE expires_at > now() "
                        "AND last_seen_at > now() - interval '90 seconds' "
                        "ORDER BY last_seen_at DESC"
                    )
                    rows = cur.fetchall()
            conn.close()
            out = []
            for install_id, device, app_version, last_seen in rows:
                meta = device if isinstance(device, dict) else {}
                out.append({
                    "install_id": str(install_id),
                    "manufacturer": str(meta.get("manufacturer", "")),
                    "model": str(meta.get("model", "")),
                    "android": meta.get("android"),
                    "app_version": str(app_version or ""),
                    "last_seen": last_seen.isoformat() if last_seen else None,
                })
            return out
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        rows = conn.execute(
            "SELECT install_id, device, app_version, last_seen_at FROM client_sessions "
            "WHERE expires_at > ? AND last_seen_at > ? ORDER BY last_seen_at DESC",
            (time.time(), time.time() - 90),
        ).fetchall()
        out = []
        for install_id, device, app_version, last_seen in rows:
            try:
                meta = json.loads(device) if isinstance(device, str) else (device or {})
            except Exception:
                meta = {}
            out.append({
                "install_id": str(install_id),
                "manufacturer": str(meta.get("manufacturer", "")),
                "model": str(meta.get("model", "")),
                "android": meta.get("android"),
                "app_version": str(app_version or ""),
                "last_seen": float(last_seen) if last_seen else None,
            })
        return out
    finally:
        conn.close()


def _command_snapshot(command_id: str) -> dict[str, Any]:
    _ensure_schema()
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id,install_id,kind,payload,status,created_at,claimed_at,completed_at,result "
                        "FROM ucoa_device_commands WHERE id=%s",
                        (command_id,),
                    )
                    row = cur.fetchone()
            conn.close()
            if not row:
                raise HTTPException(404, "Android task not found")
            return {
                "id": row[0], "install_id": row[1], "kind": row[2], "payload": row[3], "status": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
                "claimed_at": row[6].isoformat() if row[6] else None,
                "completed_at": row[7].isoformat() if row[7] else None,
                "result": row[8],
            }
        except HTTPException:
            raise
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        row = conn.execute(
            "SELECT id,install_id,kind,payload,status,created_at,claimed_at,completed_at,result "
            "FROM device_commands WHERE id=?",
            (command_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Android task not found")

        def parse(value: Any) -> Any:
            try:
                return json.loads(value) if isinstance(value, str) else value
            except Exception:
                return value

        return {
            "id": row[0], "install_id": row[1], "kind": row[2], "payload": parse(row[3]), "status": row[4],
            "created_at": row[5], "claimed_at": row[6], "completed_at": row[7], "result": parse(row[8]),
        }
    finally:
        conn.close()


def _choose_device(requested_install_id: str | None) -> str:
    active = _active_device_ids()
    if not active:
        raise HTTPException(
            409,
            "No active Android device session found. Open UCOA and enable AccessibilityService first.",
        )
    requested = (requested_install_id or "").strip()
    if requested:
        if requested not in active:
            raise HTTPException(409, "Requested Android device is not currently online")
        return requested
    return _preferred_active_device_id() or active[0]


async def _poll_command(command_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, min(int(timeout_seconds), 120))
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = _command_snapshot(command_id)
        if last.get("status") in {"completed", "failed", "cancelled"}:
            return last
        await asyncio.sleep(1)
    return last or _command_snapshot(command_id)


def _call_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "android_devices":
        devices = _active_device_details()
        return {"ok": True, "count": len(devices), "devices": devices}

    if name == "android_run_task":
        task = str(args.get("task", "")).strip()
        if not task:
            raise HTTPException(400, "task is required")
        install_id = _choose_device(args.get("install_id"))
        idempotency = str(args.get("idempotency_key", "")).strip()[:128]
        if not idempotency:
            idempotency = hashlib.sha256(f"mcp:{install_id}:{task}".encode("utf-8")).hexdigest()[:48]
        req = type("McpCommand", (), {
            "kind": "task",
            "task": task,
            "attachments": [],
            "metadata": {
                "source": "chatgpt-mcp",
                "evidence_required": True,
                "idempotency_key": idempotency,
            },
        })()
        queued = _insert_command(install_id, req)
        wait_seconds = int(args.get("wait_seconds", 5) or 0)
        if wait_seconds <= 0:
            return queued
        # The async RPC dispatcher performs the wait when the HTTP event loop is active.
        return queued

    if name == "android_task_status":
        command_id = str(args.get("command_id", "")).strip()
        if not command_id:
            raise HTTPException(400, "command_id is required")
        return _command_snapshot(command_id)

    if name == "android_wait_task":
        raise HTTPException(500, "android_wait_task must be handled by async dispatcher")

    raise HTTPException(404, f"Unknown MCP tool: {name}")


async def handle_rpc(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = str(message.get("method", ""))
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None

    if method in {"ping", "notifications/ping"}:
        return _jsonrpc_result(request_id, {})

    if method == "server/discover":
        return _jsonrpc_result(request_id, {
            "protocolVersion": MODERN_PROTOCOL,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {"listChanged": False}},
        })

    if method == "initialize":
        requested = str(params.get("protocolVersion", LEGACY_PROTOCOL))
        chosen = requested if requested in SUPPORTED_PROTOCOLS else LEGACY_PROTOCOL
        return _jsonrpc_result(request_id, {
            "protocolVersion": chosen,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "Use android_devices before real execution. Use android_run_task for explicit user-requested phone actions. Treat completion as valid only when the Android client returns completion_verified_by_ucoa=true or an explicit terminal failure.",
        })

    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": TOOLS})

    if method != "tools/call":
        return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")

    name = str(params.get("name", ""))
    args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if not name:
        return _jsonrpc_error(request_id, -32602, "Tool name is required")

    try:
        if name == "android_wait_task":
            command_id = str(args.get("command_id", "")).strip()
            if not command_id:
                raise HTTPException(400, "command_id is required")
            value = await _poll_command(command_id, int(args.get("timeout_seconds", 30) or 30))
        else:
            if name not in {t["name"] for t in TOOLS}:
                raise HTTPException(404, f"Unknown MCP tool: {name}")
            value = _call_tool(name, args)
            if name == "android_run_task" and int(args.get("wait_seconds", 5) or 0) > 0:
                value = await _poll_command(value["command_id"], int(args.get("wait_seconds", 5) or 5))
        return _jsonrpc_result(request_id, _tool_result(value))
    except HTTPException as exc:
        return _jsonrpc_result(request_id, _tool_result({"ok": False, "error": exc.detail}, is_error=True))
    except Exception as exc:
        return _jsonrpc_result(
            request_id,
            _tool_result({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, is_error=True),
        )


def _stream_json(message: dict[str, Any]):
    async def gen():
        yield "event: message\n"
        yield "data: " + json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _http_response(message: dict[str, Any] | None, request: Request) -> Response:
    if message is None:
        return Response(status_code=202)
    accept = request.headers.get("accept", "")
    only_sse = "text/event-stream" in accept and "application/json" not in accept
    if only_sse:
        return _stream_json(message)
    return JSONResponse(
        message,
        headers={"Mcp-Protocol-Version": str(message.get("result", {}).get("protocolVersion", MODERN_PROTOCOL))},
    )


@app_v3.app.post("/mcp")
async def mcp_endpoint(request: Request, authorization: str | None = Header(default=None)):
    if not _expected_token():
        return JSONResponse(
            {"error": "MCP authentication is not configured on the server"},
            status_code=503,
        )
    if not _authorized(authorization):
        return JSONResponse(
            {"error": "Invalid MCP authorization"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        message = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return JSONResponse(
            _jsonrpc_error(None, -32600, "Invalid JSON-RPC 2.0 request"),
            status_code=400,
        )
    return _http_response(await handle_rpc(message), request)


@app_v3.app.get("/mcp")
async def mcp_get():
    return Response(
        "UCOA MCP uses POST /mcp (Streamable HTTP).",
        status_code=405,
        headers={"Allow": "POST"},
    )
