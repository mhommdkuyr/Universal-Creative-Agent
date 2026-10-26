#!/usr/bin/env python3
"""MCP client for Google's official browser-connected Colab server.

The official server bridges to a notebook open in a browser connected to the
same local MCP process. ADC JSON alone does not create that browser connection.
"""
from __future__ import annotations
import asyncio
import json
import os
import pathlib
import sys
import time
import traceback
from typing import Any
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
RESULT = OUT / "colab_result.txt"
TOOLS_FILE = OUT / "colab_mcp_tools.json"
DEFAULT_TASK = ROOT / "tasks/current_task.py"
SOURCE = "git+https://github.com/googlecolab/colab-mcp"
CONNECTION_TOOL = "open_colab_browser_connection"
CODE_KEYS = ("code", "python_code", "source", "cell_code", "code_text", "contents", "content")

def emit(line: str, lines: list[str]) -> None:
    lines.append(str(line))
    print(line, flush=True)

def model_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        try:
            result = obj.model_dump(mode="json", by_alias=True)
            return result if isinstance(result, dict) else {"value": result}
        except Exception:
            pass
    if isinstance(obj, dict):
        return obj
    return {"repr": repr(obj)}

def tool_info(tool: Any) -> tuple[str, dict[str, Any], str]:
    d = model_dict(tool)
    name = str(d.get("name") or getattr(tool, "name", ""))
    schema = d.get("inputSchema") or d.get("input_schema") or getattr(tool, "inputSchema", {}) or {}
    desc = str(d.get("description") or getattr(tool, "description", "") or "")
    return name, schema if isinstance(schema, dict) else {}, desc

def requested_code() -> tuple[str, str]:
    path_arg = os.environ.get("SCRIPT_PATH", "").strip()
    code_arg = os.environ.get("TASK_CODE", "")
    if path_arg:
        p = (ROOT / path_arg).resolve()
        if p == ROOT or ROOT not in p.parents:
            raise ValueError("script_path must remain inside the repository.")
        if not p.is_file() or p.suffix.lower() != ".py":
            raise FileNotFoundError(f"script_path must name an existing .py file: {path_arg}")
        return p.read_text(encoding="utf-8"), str(p.relative_to(ROOT))
    if code_arg.strip():
        return code_arg, "workflow_dispatch.task_code"
    if not DEFAULT_TASK.is_file():
        raise FileNotFoundError(f"Default task not found: {DEFAULT_TASK}")
    return DEFAULT_TASK.read_text(encoding="utf-8"), "tasks/current_task.py"

def result_text(result: Any) -> str:
    pieces = []
    for item in (getattr(result, "content", None) or []):
        d = model_dict(item)
        if d.get("type") == "text" and d.get("text") is not None:
            pieces.append(str(d["text"]))
        elif hasattr(item, "text"):
            pieces.append(str(item.text))
        else:
            pieces.append(json.dumps(d, ensure_ascii=False, default=str))
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured:
        pieces.append("Structured result: " + json.dumps(structured, ensure_ascii=False, default=str))
    return "\n".join(pieces).strip() or json.dumps(model_dict(result), ensure_ascii=False, default=str)

def find_executor(tools: list[Any]) -> tuple[Any, str] | None:
    found = []
    for tool in tools:
        name, schema, desc = tool_info(tool)
        props = schema.get("properties") or {}
        if not isinstance(props, dict):
            continue
        code_key = next((key for key in CODE_KEYS if key in props), None)
        if not code_key or not any(k in name.lower() for k in ("execute", "run", "eval")):
            continue
        required = schema.get("required") or []
        if any(key != code_key for key in required):
            continue
        score = (4 if "execute" in name.lower() else 0)
        score += (2 if "python" in name.lower() or "code" in name.lower() else 0)
        score += (2 if code_key == "code" else 0)
        found.append((score, tool, code_key))
    found.sort(key=lambda x: x[0], reverse=True)
    return (found[0][1], found[0][2]) if found else None

async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    start = time.time()
    try:
        code, source = requested_code()
        emit(f"Task source: {source}", lines)
        emit(f"Code length: {len(code)} characters", lines)
        emit("Launching official Google Colab MCP via uvx.", lines)
        params = StdioServerParameters(
            command=os.environ.get("COLAB_MCP_COMMAND", "uvx"),
            args=[SOURCE],
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = list((await session.list_tools()).tools or [])

                def save_tools(items: list[Any]) -> None:
                    data = []
                    for item in items:
                        n, s, d = tool_info(item)
                        data.append({"name": n, "description": d, "inputSchema": s})
                    TOOLS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

                save_tools(tools)
                emit("Initial available tools: " + (", ".join(tool_info(t)[0] for t in tools) or "(none)"), lines)
                executor = find_executor(tools)
                if executor is None:
                    can_connect = any(tool_info(t)[0] == CONNECTION_TOOL for t in tools)
                    if can_connect:
                        emit("No execution tool yet; trying official browser connection (up to configured timeout).", lines)
                        timeout = max(10, int(os.environ.get("COLAB_MCP_TIMEOUT_SECONDS", "75")))
                        try:
                            res = await asyncio.wait_for(session.call_tool(CONNECTION_TOOL, {}), timeout=timeout)
                            emit("Browser connection response: " + result_text(res), lines)
                        except asyncio.TimeoutError:
                            emit("Browser connection attempt timed out.", lines)
                        await asyncio.sleep(2)
                        tools = list((await session.list_tools()).tools or [])
                        save_tools(tools)
                        emit("Tools after connection attempt: " + (", ".join(tool_info(t)[0] for t in tools) or "(none)"), lines)
                        executor = find_executor(tools)
                if executor is None:
                    raise RuntimeError(
                        "Colab execution tools are unavailable. The official googlecolab/colab-mcp server "
                        "requires a Colab notebook UI/browser to connect to this same MCP process. It is not "
                        "a headless Colab runtime API; COLAB_CREDENTIALS/ADC alone cannot create the browser "
                        "connection, and GitHub-hosted Actions has no interactive browser attached. "
                        "No task code was executed in Colab."
                    )
                tool, code_key = executor
                name = tool_info(tool)[0]
                emit(f"Execution tool selected: {name}; code field: {code_key}", lines)
                result = await session.call_tool(name, {code_key: code})
                emit("===== Tool response =====", lines)
                emit(result_text(result), lines)
                emit("===== End tool response =====", lines)
                if getattr(result, "isError", getattr(result, "is_error", False)):
                    raise RuntimeError(f"MCP tool {name} returned an error.")
                emit("MCP tool returned without an error flag; inspect output for task-level success.", lines)
        emit(f"Elapsed seconds: {time.time() - start:.1f}", lines)
        RESULT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        details = f"\nERROR: {type(exc).__name__}: {exc}\nTraceback:\n{traceback.format_exc()}"
        lines.extend(details.rstrip().splitlines())
        RESULT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(details, file=sys.stderr, flush=True)
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
