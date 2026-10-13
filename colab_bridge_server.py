import asyncio
import contextlib
import io
import json
import os
import secrets
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

MCP_BEARER_TOKEN = os.environ.get("MCP_BEARER_TOKEN", "")
AGENT_BEARER_TOKEN = os.environ.get("AGENT_BEARER_TOKEN", "")

if not MCP_BEARER_TOKEN or not AGENT_BEARER_TOKEN:
    raise RuntimeError("Set MCP_BEARER_TOKEN and AGENT_BEARER_TOKEN in the Render environment.")

mcp = FastMCP(
    "Google Colab Bridge",
    instructions=(
        "A private bridge to the user's currently connected Google Colab runtime. "
        "The notebook must have the bridge client cell running. Execute code only "
        "when explicitly requested by the connected user."
    ),
)

active_agent: WebSocket | None = None
connected_at: float | None = None
agent_lock = asyncio.Lock()
send_lock = asyncio.Lock()
pending_lock = asyncio.Lock()
pending: dict[str, asyncio.Future] = {}


def connected() -> bool:
    return (
        active_agent is not None
        and active_agent.application_state == WebSocketState.CONNECTED
    )


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
            return json.dumps(
                {"ok": False, "error": "Colab is not connected. Run the bridge client cell in Colab first."},
                ensure_ascii=False,
            )

        message = {"id": request_id, "op": op, **payload}
        async with send_lock:
            await socket.send_json(message)

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
    return json.dumps({
        "bridge": "online",
        "colab_connected": connected(),
        "connected_seconds_ago": round(time.time() - connected_at, 1) if connected_at else None,
        "next_step": None if connected() else "Open the Colab notebook and run the bridge client cell.",
    }, ensure_ascii=False)


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


async def root(_request):
    return PlainTextResponse("Google Colab Bridge is running. The MCP endpoint is /mcp.")


async def healthz(_request):
    return JSONResponse({"ok": True, "service": "google-colab-mcp-bridge", "colab_connected": connected()})


async def agent_websocket(websocket: WebSocket):
    global active_agent, connected_at

    supplied = websocket.headers.get("authorization", "")
    expected = f"Bearer {AGENT_BEARER_TOKEN}"
    if not secrets.compare_digest(supplied, expected):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    async with agent_lock:
        old_socket = active_agent
        active_agent = websocket
        connected_at = time.time()

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
        # Connection failures should not leak request data into logs.
        pass
    finally:
        async with agent_lock:
            if active_agent is websocket:
                active_agent = None
                connected_at = None
        async with pending_lock:
            for future in list(pending.values()):
                if not future.done():
                    future.set_result({"ok": False, "error": "The Colab runtime disconnected."})


class MCPBearerMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").rstrip("/") == "/mcp":
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            supplied = headers.get(b"authorization", b"").decode("latin-1")
            if not secrets.compare_digest(supplied, f"Bearer {MCP_BEARER_TOKEN}"):
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    async with mcp.session_manager.run():
        yield


mcp_asgi = mcp.streamable_http_app(
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
)

starlette_app = Starlette(
    routes=[
        Route("/", root, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
        WebSocketRoute("/agent/ws", agent_websocket),
        Mount("/", app=mcp_asgi),
    ],
    lifespan=lifespan,
)
app = MCPBearerMiddleware(starlette_app)
