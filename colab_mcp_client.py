# Google Colab MCP Bridge client
# Run this cell in your Colab notebook and leave it running while using the remote MCP tools.
# The token is private. Do not publish this cell or its output in a public notebook.

!pip -q install "websockets>=14,<16"

import asyncio
import contextlib
import io
import json
import os
import pathlib
import traceback
import websockets
from contextlib import redirect_stdout, redirect_stderr

BRIDGE_WS_URL = "wss://YOUR-RENDER-SERVICE.onrender.com/agent/ws"
AGENT_TOKEN = "PASTE_THE_AGENT_BEARER_TOKEN_FROM_RENDER_ENV_HERE"

async def _handle_colab_bridge_message(ws, request):
    request_id = request.get("id")
    op = request.get("op")

    try:
        if op == "run_python":
            code = request.get("code", "")
            out = io.StringIO()
            err = io.StringIO()
            namespace = globals()
            with redirect_stdout(out), redirect_stderr(err):
                exec(compile(code, "<remote-colab>", "exec"), namespace, namespace)
            response = {
                "id": request_id,
                "ok": True,
                "stdout": out.getvalue()[-30000:],
                "stderr": err.getvalue()[-12000:],
            }

        elif op == "list_files":
            root = pathlib.Path("/content").resolve()
            path = pathlib.Path(request.get("path") or "/content").resolve()
            if path != root and root not in path.parents:
                raise ValueError("Only paths under /content are allowed.")
            if not path.exists():
                raise FileNotFoundError(str(path))
            if not path.is_dir():
                raise NotADirectoryError(str(path))
            entries = []
            for item in sorted(path.iterdir(), key=lambda x: x.name.lower())[:500]:
                entries.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                })
            response = {"id": request_id, "ok": True, "path": str(path), "entries": entries}

        elif op == "read_file":
            root = pathlib.Path("/content").resolve()
            path = pathlib.Path(request.get("path") or "").resolve()
            if path != root and root not in path.parents:
                raise ValueError("Only paths under /content are allowed.")
            if not path.is_file():
                raise FileNotFoundError(str(path))
            if path.stat().st_size > 1024 * 1024:
                raise ValueError("Files larger than 1 MiB are not read by this tool.")
            response = {
                "id": request_id,
                "ok": True,
                "path": str(path),
                "content": path.read_text(encoding="utf-8", errors="replace"),
            }
        else:
            raise ValueError("Unsupported bridge operation.")

    except Exception as exc:
        response = {
            "id": request_id,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-8000:],
        }

    await ws.send(json.dumps(response, ensure_ascii=False))

async def colab_mcp_bridge_client():
    if "YOUR-RENDER-SERVICE" in BRIDGE_WS_URL or "PASTE_THE_AGENT" in AGENT_TOKEN:
        raise ValueError("Replace BRIDGE_WS_URL and AGENT_TOKEN before running.")
    while True:
        try:
            print("Connecting to the Colab bridge…")
            async with websockets.connect(
                BRIDGE_WS_URL,
                additional_headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=10 * 1024 * 1024,
            ) as ws:
                print("Connected. Keep this cell running.")
                async for raw in ws:
                    message = json.loads(raw)
                    if message.get("type") == "connected":
                        print(message.get("message", "Connected"))
                        continue
                    await _handle_colab_bridge_message(ws, message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Bridge disconnected ({type(exc).__name__}: {exc}). Retrying in 5 seconds…")
            await asyncio.sleep(5)

await colab_mcp_bridge_client()
