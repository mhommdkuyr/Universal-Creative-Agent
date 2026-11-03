import asyncio
import base64
import contextlib
import hashlib
import html
import json
import os
import secrets
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://colab-mcp-bridge.onrender.com").rstrip("/")
MCP_RESOURCE = os.environ.get("MCP_RESOURCE_URI", BASE_URL + "/mcp")
MCP_BEARER_TOKEN = os.environ.get("MCP_BEARER_TOKEN", "")
AGENT_BEARER_TOKEN = os.environ.get("AGENT_BEARER_TOKEN", "")
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "")
if not MCP_BEARER_TOKEN or not AGENT_BEARER_TOKEN:
    raise RuntimeError("Set MCP_BEARER_TOKEN and AGENT_BEARER_TOKEN in the Render environment.")
if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET or not OAUTH_REDIRECT_URI:
    raise RuntimeError("Set OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, and OAUTH_REDIRECT_URI in Render.")

mcp = FastMCP("Google Colab Bridge", instructions=(
    "A private bridge to the user's currently connected Google Colab runtime. "
    "The notebook must have the bridge client cell running. Execute code only "
    "when explicitly requested by the connected user."
))
active_agent: WebSocket | None = None
connected_at: float | None = None
agent_lock = asyncio.Lock()
send_lock = asyncio.Lock()
pending_lock = asyncio.Lock()
pending: dict[str, asyncio.Future] = {}
# OAuth tokens are process-local for this single-instance free deployment.
# Re-authorize after a service restart; use shared storage before scaling horizontally.
oauth_codes: dict[str, dict[str, Any]] = {}
oauth_access: dict[str, dict[str, Any]] = {}
oauth_refresh: dict[str, dict[str, Any]] = {}

def connected() -> bool:
    return active_agent is not None and active_agent.application_state == WebSocketState.CONNECTED

async def dispatch_to_colab(op: str, payload: dict[str, Any], timeout: int = 120) -> str:
    request_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    async with pending_lock:
        pending[request_id] = future
    try:
        async with agent_lock:
            socket = active_agent
        if socket is None or socket.application_state != WebSocketState.CONNECTED:
            return json.dumps({"ok": False, "error": "Colab is not connected. Run the bridge client cell in Colab first."}, ensure_ascii=False)
        async with send_lock:
            await socket.send_json({"id": request_id, "op": op, **payload})
        try:
            result = await asyncio.wait_for(future, timeout=max(5, min(int(timeout), 180)))
        except asyncio.TimeoutError:
            result = {"ok": False, "error": f"Colab did not respond within {timeout} seconds."}
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Bridge error: {type(exc).__name__}: {exc}"}, ensure_ascii=False)
    finally:
        async with pending_lock:
            pending.pop(request_id, None)

@mcp.tool()
async def colab_status() -> str:
    """Check whether a Google Colab runtime is connected to this bridge."""
    return json.dumps({"bridge": "online", "colab_connected": connected(),
        "connected_seconds_ago": round(time.time() - connected_at, 1) if connected_at else None,
        "next_step": None if connected() else "Open the Colab notebook and run the bridge client cell."}, ensure_ascii=False)

@mcp.tool()
async def colab_run_python(code: str, timeout_seconds: int = 120) -> str:
    """Run Python code inside the connected Colab runtime and return captured stdout, stderr, and errors."""
    if not code.strip():
        return json.dumps({"ok": False, "error": "The code argument is empty."}, ensure_ascii=False)
    return await dispatch_to_colab("run_python", {"code": code}, timeout_seconds)

@mcp.tool()
async def colab_list_files(path: str = "/content") -> str:
    """List files in a directory under /content in the connected Colab runtime."""
    return await dispatch_to_colab("list_files", {"path": path}, 30)

@mcp.tool()
async def colab_read_file(path: str) -> str:
    """Read a UTF-8 text file under /content in the connected Colab runtime, limited to 1 MiB."""
    return await dispatch_to_colab("read_file", {"path": path}, 30)

def oauth_error(error: str, status: int = 400):
    return JSONResponse({"error": error}, status_code=status, headers={"Cache-Control": "no-store"})

def parse_form(raw: bytes) -> dict[str, str]:
    parsed = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
    return {k: v[-1] for k, v in parsed.items()}

def cleanup_oauth():
    now = time.time()
    for store in (oauth_codes, oauth_access, oauth_refresh):
        for key in list(store):
            if store[key].get("expires_at", 0) <= now:
                store.pop(key, None)

def valid_client(client_id: str, client_secret: str | None = None) -> bool:
    if not secrets.compare_digest(client_id or "", OAUTH_CLIENT_ID):
        return False
    return client_secret is None or secrets.compare_digest(client_secret, OAUTH_CLIENT_SECRET)

def get_client_credentials(request: Request, form: dict[str, str]):
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:], validate=True).decode()
            return decoded.split(":", 1)
        except Exception:
            return "", ""
    return form.get("client_id", ""), form.get("client_secret", "")

async def protected_resource(_request: Request):
    return JSONResponse({"resource": MCP_RESOURCE, "authorization_servers": [BASE_URL],
        "bearer_methods_supported": ["header"], "scopes_supported": ["mcp:tools"]},
        headers={"Cache-Control": "public, max-age=300"})

async def authorization_server_metadata(_request: Request):
    return JSONResponse({"issuer": BASE_URL, "authorization_endpoint": BASE_URL + "/authorize",
        "token_endpoint": BASE_URL + "/token", "response_types_supported": ["code"],
        "response_modes_supported": ["query"], "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"], "scopes_supported": ["mcp:tools"]},
        headers={"Cache-Control": "public, max-age=300"})

async def authorize(request: Request):
    cleanup_oauth()
    q = request.query_params
    client_id, redirect_uri = q.get("client_id", ""), q.get("redirect_uri", "")
    state, challenge = q.get("state", ""), q.get("code_challenge", "")
    if not valid_client(client_id):
        return oauth_error("invalid_client", 401)
    if redirect_uri != OAUTH_REDIRECT_URI:
        return oauth_error("redirect_uri_mismatch")
    if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256" or len(challenge) < 43:
        return oauth_error("invalid_request: authorization code with PKCE S256 is required")
    if q.get("resource", MCP_RESOURCE) != MCP_RESOURCE or not state:
        return oauth_error("invalid_target_or_state")
    hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v, quote=True)}">' for k, v in q.items())
    page = f"""<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>السماح بالاتصال</title><body style="font-family:system-ui;background:#111;color:#eee;max-width:620px;margin:8vh auto;padding:24px">
    <main style="border:1px solid #444;border-radius:18px;padding:24px"><h2>السماح لـ Gemini بالاتصال بجسر Google Colab؟</h2>
    <p>سيتمكن Gemini من فحص حالة جلسة Colab وتشغيل Python وعرض وقراءة الملفات ضمن القيود التي يطبقها الجسر.</p>
    <p>لا توافق إذا لم تكن أنت من بدأ ربط الخادم.</p><form method="post" action="/authorize/consent">{hidden}
    <button style="background:#d7e3ff;color:#111;border:0;border-radius:10px;padding:13px 24px;font-size:16px">السماح والمتابعة</button></form></main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})

async def authorize_consent(request: Request):
    cleanup_oauth()
    form = parse_form(await request.body())
    client_id, redirect_uri = form.get("client_id", ""), form.get("redirect_uri", "")
    state, challenge = form.get("state", ""), form.get("code_challenge", "")
    if not valid_client(client_id) or redirect_uri != OAUTH_REDIRECT_URI:
        return oauth_error("invalid_client_or_redirect", 401)
    if form.get("response_type") != "code" or form.get("code_challenge_method") != "S256":
        return oauth_error("invalid_request")
    resource = form.get("resource", MCP_RESOURCE)
    if resource != MCP_RESOURCE or not state:
        return oauth_error("invalid_target_or_state")
    code = secrets.token_urlsafe(40)
    oauth_codes[code] = {"client_id": client_id, "redirect_uri": redirect_uri,
        "challenge": challenge, "resource": resource, "expires_at": time.time() + 300}
    return RedirectResponse(redirect_uri + "?" + urlencode({"code": code, "state": state}), status_code=302)

async def token(request: Request):
    cleanup_oauth()
    form = parse_form(await request.body())
    client_id, client_secret = get_client_credentials(request, form)
    if not valid_client(client_id, client_secret):
        return oauth_error("invalid_client", 401)
    grant_type = form.get("grant_type", "")
    if grant_type == "authorization_code":
        code = form.get("code", "")
        record = oauth_codes.pop(code, None)
        if not record or record["expires_at"] <= time.time():
            return oauth_error("invalid_grant")
        if record["client_id"] != client_id or form.get("redirect_uri") != record["redirect_uri"]:
            return oauth_error("invalid_grant")
        verifier = form.get("code_verifier", "")
        digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if not secrets.compare_digest(digest, record["challenge"]):
            return oauth_error("invalid_grant")
        if form.get("resource", record["resource"]) != record["resource"]:
            return oauth_error("invalid_target")
        resource = record["resource"]
    elif grant_type == "refresh_token":
        refresh_token = form.get("refresh_token", "")
        record = oauth_refresh.pop(refresh_token, None)
        if not record or record["expires_at"] <= time.time() or record["client_id"] != client_id:
            return oauth_error("invalid_grant")
        resource = record["resource"]
    else:
        return oauth_error("unsupported_grant_type")
    access_token = secrets.token_urlsafe(40)
    refresh_token = secrets.token_urlsafe(48)
    oauth_access[access_token] = {"client_id": client_id, "resource": resource, "expires_at": time.time() + 3600}
    oauth_refresh[refresh_token] = {"client_id": client_id, "resource": resource, "expires_at": time.time() + 30 * 86400}
    return JSONResponse({"access_token": access_token, "token_type": "Bearer", "expires_in": 3600,
        "refresh_token": refresh_token, "scope": "mcp:tools"},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

async def root(_request: Request):
    return PlainTextResponse("Google Colab Bridge is running. The MCP endpoint is /mcp.")

async def healthz(_request: Request):
    return JSONResponse({"ok": True, "service": "google-colab-mcp-bridge",
        "colab_connected": connected(), "oauth": "enabled"})

async def agent_websocket(websocket: WebSocket):
    global active_agent, connected_at
    supplied = websocket.headers.get("authorization", "")
    if not secrets.compare_digest(supplied, f"Bearer {AGENT_BEARER_TOKEN}"):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    async with agent_lock:
        old_socket, active_agent, connected_at = active_agent, websocket, time.time()
    if old_socket is not None and old_socket is not websocket:
        with contextlib.suppress(Exception):
            await old_socket.close(code=4000, reason="A newer Colab session connected.")
    try:
        await websocket.send_json({"type": "connected", "message": "Colab bridge connection established."})
        while True:
            incoming = json.loads(await websocket.receive_text())
            request_id = str(incoming.get("id", ""))
            async with pending_lock:
                future = pending.get(request_id)
            if future is not None and not future.done():
                future.set_result(incoming)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        async with agent_lock:
            if active_agent is websocket:
                active_agent, connected_at = None, None
        async with pending_lock:
            for future in list(pending.values()):
                if not future.done():
                    future.set_result({"ok": False, "error": "The Colab runtime disconnected."})

class MCPBearerMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").rstrip("/") == "/mcp":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            supplied = headers.get(b"authorization", b"").decode("latin-1")
            token_value = supplied[7:] if supplied.startswith("Bearer ") else ""
            cleanup_oauth()
            valid_oauth = token_value in oauth_access and oauth_access[token_value]["resource"] == MCP_RESOURCE
            valid_legacy = secrets.compare_digest(supplied, f"Bearer {MCP_BEARER_TOKEN}")
            if not valid_oauth and not valid_legacy:
                response = JSONResponse({"error": "Unauthorized"}, status_code=401,
                    headers={"WWW-Authenticate": f'Bearer resource_metadata="{BASE_URL}/.well-known/oauth-protected-resource"'})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    async with mcp.session_manager.run():
        yield

mcp_asgi = mcp.streamable_http_app(
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["colab-mcp-bridge.onrender.com", "colab-mcp-bridge.onrender.com:*"],
    )
)
starlette_app = Starlette(routes=[
    Route("/", root, methods=["GET"]),
    Route("/healthz", healthz, methods=["GET"]),
    Route("/.well-known/oauth-protected-resource", protected_resource, methods=["GET"]),
    Route("/.well-known/oauth-authorization-server", authorization_server_metadata, methods=["GET"]),
    Route("/authorize", authorize, methods=["GET"]),
    Route("/authorize/consent", authorize_consent, methods=["POST"]),
    Route("/token", token, methods=["POST"]),
    WebSocketRoute("/agent/ws", agent_websocket),
    Mount("/", app=mcp_asgi),
], lifespan=lifespan)
app = MCPBearerMiddleware(starlette_app)
