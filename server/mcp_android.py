from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import urlencode

import jwt
from fastapi import Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

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
SERVER_VERSION = os.getenv("UCOA_MCP_SERVER_VERSION", "1.1.0")
RESOURCE_ID = os.getenv("UCOA_MCP_RESOURCE", "https://ucoa-agent-brain-69bo.onrender.com").rstrip("/")
OAUTH_ISSUER = os.getenv("UCOA_OAUTH_ISSUER", RESOURCE_ID).rstrip("/")
OAUTH_SCOPE = "ucoa:android"
ACCESS_TOKEN_TTL = 3600
REFRESH_TOKEN_TTL = 90 * 24 * 3600
CHATGPT_STABLE_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
CHATGPT_CALLBACK_REDIRECT_RE = re.compile(r"^https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]+$")


TOOLS: list[dict[str, Any]] = [
    {
        "name": "android_devices",
        "description": "List connected UCOA Android devices that have recently checked in. Does not expose session tokens.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "ucoa_profile",
        "description": "Return the identity associated with the authenticated UCOA connection.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "_meta": {"openai/profile": True},
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

for _tool in TOOLS:
    _tool["securitySchemes"] = [{"type": "oauth2", "scopes": [OAUTH_SCOPE]}]


def _expected_token() -> str:
    return os.getenv("UCOA_MCP_TOKEN", "").strip() or os.getenv("UCOA_AGENT_TOKEN", "").strip()


def _oauth_signing_secret() -> str:
    return os.getenv("UCOA_OAUTH_SIGNING_SECRET", "").strip() or _expected_token()


def _oauth_sqlite() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_oauth_codes (
            code TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            resource TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_oauth_refresh_tokens (
            token_hash TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            resource TEXT NOT NULL,
            scope TEXT NOT NULL,
            subject TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def _allowed_client_id(client_id: str) -> bool:
    return bool(client_id and (
        client_id == "https://chatgpt.com/oauth/client.json"
        or client_id.startswith("https://chatgpt.com/oauth/")
    ))


def _allowed_redirect_uri(redirect_uri: str) -> bool:
    return redirect_uri == CHATGPT_STABLE_REDIRECT or bool(CHATGPT_CALLBACK_REDIRECT_RE.fullmatch(redirect_uri))


def _normalize_resource(resource: str | None) -> str:
    value = str(resource or "").strip().rstrip("/")
    return RESOURCE_ID if value in {"", RESOURCE_ID, RESOURCE_ID + "/mcp"} else value


def _oauth_metadata() -> dict[str, Any]:
    return {
        "issuer": OAUTH_ISSUER,
        "authorization_response_iss_parameter_supported": True,
        "authorization_endpoint": OAUTH_ISSUER + "/oauth/authorize",
        "token_endpoint": OAUTH_ISSUER + "/oauth/token",
        "client_id_metadata_document_supported": True,
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": [OAUTH_SCOPE],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "resource_parameter_supported": True,
    }


def _protected_resource_metadata() -> dict[str, Any]:
    return {
        "resource": RESOURCE_ID,
        "authorization_servers": [OAUTH_ISSUER],
        "scopes_supported": [OAUTH_SCOPE],
        "resource_documentation": RESOURCE_ID + "/health",
    }


def _issue_access_token(subject: str, client_id: str, scope: str) -> str:
    secret = _oauth_signing_secret()
    if not secret:
        raise HTTPException(503, "OAuth signing secret is not configured")
    now = int(time.time())
    return jwt.encode(
        {
            "iss": OAUTH_ISSUER,
            "sub": subject,
            "aud": RESOURCE_ID,
            "scope": scope,
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL,
            "jti": secrets.token_hex(16),
            "client_id": client_id,
        },
        secret,
        algorithm="HS256",
    )


def _verify_oauth_token(token: str) -> dict[str, Any] | None:
    secret = _oauth_signing_secret()
    if not secret or not token:
        return None
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=RESOURCE_ID,
            issuer=OAUTH_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        if OAUTH_SCOPE not in str(claims.get("scope", "")).split():
            return None
        return claims
    except Exception:
        return None


def _www_authenticate(error: str = "invalid_token", description: str = "OAuth authorization is required") -> str:
    safe_description = description.replace('"', "")
    return (
        'Bearer resource_metadata="' + RESOURCE_ID + '/.well-known/oauth-protected-resource", '
        'scope="' + OAUTH_SCOPE + '", error="' + error + '", error_description="' + safe_description + '"'
    )


def _authorized_claims(authorization: str | None) -> dict[str, Any] | None:
    supplied = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    if not supplied:
        return None
    claims = _verify_oauth_token(supplied)
    if claims:
        return claims
    expected = _expected_token()
    if expected and hmac.compare_digest(supplied, expected):
        return {"sub": "ucoa-legacy", "scope": OAUTH_SCOPE, "legacy": True}
    return None


def _authorized(authorization: str | None) -> bool:
    return _authorized_claims(authorization) is not None


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


def _call_tool(name: str, args: dict[str, Any], auth_claims: dict[str, Any] | None = None) -> Any:
    if name == "ucoa_profile":
        subject = str((auth_claims or {}).get("sub") or "ucoa-user")
        return {"id": subject, "name": "UCOA Android User", "scope": OAUTH_SCOPE}

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


async def handle_rpc(message: dict[str, Any], auth_claims: dict[str, Any] | None = None) -> dict[str, Any] | None:
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
            value = _call_tool(name, args, auth_claims)
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


@app_v3.app.get("/.well-known/oauth-protected-resource")
@app_v3.app.get("/.well-known/oauth-protected-resource/mcp")
@app_v3.app.get("/mcp/.well-known/oauth-protected-resource")
@app_v3.app.get("/mcp/.well-known/oauth-protected-resource/mcp")
async def oauth_protected_resource_metadata():
    return JSONResponse(_protected_resource_metadata())


@app_v3.app.get("/.well-known/oauth-authorization-server")
@app_v3.app.get("/.well-known/oauth-authorization-server/mcp")
@app_v3.app.get("/mcp/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata():
    return JSONResponse(_oauth_metadata())


@app_v3.app.get("/.well-known/openid-configuration")
@app_v3.app.get("/.well-known/openid-configuration/mcp")
@app_v3.app.get("/mcp/.well-known/openid-configuration")
async def openid_configuration():
    return JSONResponse(_oauth_metadata())


@app_v3.app.get("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize(request: Request):
    q = request.query_params
    client_id = q.get("client_id", "")
    redirect_uri = q.get("redirect_uri", "")
    response_type = q.get("response_type", "")
    code_challenge = q.get("code_challenge", "")
    challenge_method = q.get("code_challenge_method", "")
    resource = _normalize_resource(q.get("resource"))
    scope = q.get("scope", OAUTH_SCOPE)
    state = q.get("state")
    valid = (
        _allowed_client_id(client_id)
        and _allowed_redirect_uri(redirect_uri)
        and response_type == "code"
        and bool(code_challenge)
        and challenge_method == "S256"
        and resource == RESOURCE_ID
        and OAUTH_SCOPE in scope.split()
    )
    if not valid:
        return HTMLResponse("Invalid OAuth authorization request.", status_code=400)
    safe_client = client_id.replace("&", "&amp;").replace('"', "&quot;")
    safe_redirect = redirect_uri.replace("&", "&amp;").replace('"', "&quot;")
    safe_challenge = code_challenge.replace("&", "&amp;").replace('"', "&quot;")
    safe_state = (state or "").replace("&", "&amp;").replace('"', "&quot;")
    safe_scope = scope.replace("&", "&amp;").replace('"', "&quot;")
    return HTMLResponse(
        f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
        <title>ربط UCOA مع ChatGPT</title><meta name="viewport" content="width=device-width,initial-scale=1">
        <style>body{{font-family:sans-serif;max-width:560px;margin:48px auto;padding:24px;line-height:1.7}}
        button{{padding:12px 20px;font-size:16px;cursor:pointer}}</style></head>
        <body><h2>السماح لـ ChatGPT بالوصول إلى UCOA</h2>
        <p>سيتم منح ChatGPT صلاحية استخدام أدوات التحكم بجهاز Android المتصل عبر UCOA.</p>
        <p>النطاق المطلوب: <b>{OAUTH_SCOPE}</b></p>
        <form method="post" action="/oauth/authorize">
        <input type="hidden" name="client_id" value="{safe_client}">
        <input type="hidden" name="redirect_uri" value="{safe_redirect}">
        <input type="hidden" name="response_type" value="{response_type}">
        <input type="hidden" name="code_challenge" value="{safe_challenge}">
        <input type="hidden" name="code_challenge_method" value="{challenge_method}">
        <input type="hidden" name="resource" value="{resource}">
        <input type="hidden" name="scope" value="{safe_scope}">
        <input type="hidden" name="state" value="{safe_state}">
        <button type="submit">السماح والمتابعة</button></form></body></html>"""
    )


@app_v3.app.post("/oauth/authorize")
async def oauth_authorize_submit(request: Request):
    form = await request.form()
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    response_type = str(form.get("response_type", ""))
    code_challenge = str(form.get("code_challenge", ""))
    challenge_method = str(form.get("code_challenge_method", ""))
    resource = _normalize_resource(str(form.get("resource", "")))
    scope = str(form.get("scope", OAUTH_SCOPE))
    state = str(form.get("state", "")) or None
    if not (
        _allowed_client_id(client_id)
        and _allowed_redirect_uri(redirect_uri)
        and response_type == "code"
        and code_challenge
        and challenge_method == "S256"
        and resource == RESOURCE_ID
        and OAUTH_SCOPE in scope.split()
    ):
        return HTMLResponse("Invalid OAuth authorization request.", status_code=400)
    if not _oauth_signing_secret():
        return _auth_error_redirect(redirect_uri, "server_error", "OAuth signing secret is not configured", state)
    now = time.time()
    code = secrets.token_urlsafe(48)
    conn = _oauth_sqlite()
    try:
        conn.execute(
            "INSERT INTO mcp_oauth_codes(code,client_id,redirect_uri,code_challenge,resource,scope,subject,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (code, client_id, redirect_uri, code_challenge, resource, scope, "ucoa-user", now, now + 300),
        )
        conn.commit()
    finally:
        conn.close()
    params = {"code": code, "iss": OAUTH_ISSUER}
    if state:
        params["state"] = state
    return RedirectResponse(redirect_uri + "?" + urlencode(params), status_code=302)


@app_v3.app.post("/oauth/token")
async def oauth_token(request: Request):
    form = await request.form()
    grant_type = str(form.get("grant_type", ""))
    client_id = str(form.get("client_id", ""))
    if not _allowed_client_id(client_id):
        return JSONResponse({"error": "invalid_client"}, status_code=401)

    if grant_type == "authorization_code":
        code = str(form.get("code", ""))
        redirect_uri = str(form.get("redirect_uri", ""))
        verifier = str(form.get("code_verifier", ""))
        if not code or not verifier or not _allowed_redirect_uri(redirect_uri):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        conn = _oauth_sqlite()
        try:
            row = conn.execute(
                "SELECT code,client_id,redirect_uri,code_challenge,resource,scope,subject,created_at,expires_at FROM mcp_oauth_codes WHERE code=?",
                (code,),
            ).fetchone()
            if row:
                conn.execute("DELETE FROM mcp_oauth_codes WHERE code=?", (code,))
                conn.commit()
        finally:
            conn.close()

        if not row:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        _, stored_client, stored_redirect, code_challenge, resource, scope, subject, _, expires_at = row
        requested_resource = _normalize_resource(str(form.get("resource", "")))
        if (
            stored_client != client_id
            or stored_redirect != redirect_uri
            or requested_resource != RESOURCE_ID
            or resource != RESOURCE_ID
            or time.time() > float(expires_at)
        ):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        if not hmac.compare_digest(base64url_sha256(verifier), code_challenge):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        access = _issue_access_token(subject, client_id, scope)
        refresh = secrets.token_urlsafe(64)
        conn = _oauth_sqlite()
        try:
            conn.execute(
                "INSERT INTO mcp_oauth_refresh_tokens(token_hash,client_id,resource,scope,subject,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                (hashlib.sha256(refresh.encode("utf-8")).hexdigest(), client_id, resource, scope, subject, time.time(), time.time() + REFRESH_TOKEN_TTL),
            )
            conn.commit()
        finally:
            conn.close()

        return JSONResponse({
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
            "refresh_token": refresh,
            "scope": scope,
        })

    if grant_type == "refresh_token":
        refresh = str(form.get("refresh_token", ""))
        if not refresh:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        token_hash = hashlib.sha256(refresh.encode("utf-8")).hexdigest()
        conn = _oauth_sqlite()
        try:
            row = conn.execute(
                "SELECT token_hash,client_id,resource,scope,subject,expires_at FROM mcp_oauth_refresh_tokens WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
        finally:
            conn.close()
        if not row or row[1] != client_id or row[2] != RESOURCE_ID or time.time() > float(row[5]):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        access = _issue_access_token(str(row[4]), client_id, str(row[3]))
        return JSONResponse({
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
            "refresh_token": refresh,
            "scope": str(row[3]),
        })

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


def _auth_error_redirect(redirect_uri: str, error: str, description: str, state: str | None = None) -> RedirectResponse:
    params = {"error": error, "error_description": description, "iss": OAUTH_ISSUER}
    if state:
        params["state"] = state
    return RedirectResponse(redirect_uri + "?" + urlencode(params), status_code=302)


def base64url_sha256(value: str) -> str:
    import base64
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii").rstrip("=")


@app_v3.app.post("/mcp")
async def mcp_endpoint(request: Request, authorization: str | None = Header(default=None)):
    if not _oauth_signing_secret():
        return JSONResponse(
            {"error": "MCP OAuth signing secret is not configured on the server"},
            status_code=503,
        )
    auth_claims = _authorized_claims(authorization)
    if not auth_claims:
        return JSONResponse(
            {"error": "OAuth authorization is required"},
            status_code=401,
            headers={"WWW-Authenticate": _www_authenticate()},
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
    return _http_response(await handle_rpc(message, auth_claims), request)


@app_v3.app.get("/mcp")
async def mcp_get():
    return Response(
        "OAuth required. Use the protected-resource metadata endpoint to discover authorization.",
        status_code=401,
        headers={"WWW-Authenticate": _www_authenticate()},
    )
