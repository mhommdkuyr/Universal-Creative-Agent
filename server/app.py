from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="UCOA Universal Agent Brain", version="1.0.0")

MODEL_BASE_URL = os.getenv("UCOA_MODEL_BASE_URL", "").rstrip("/")
MODEL_API_KEY = os.getenv("UCOA_MODEL_API_KEY", "")
MODEL_NAME = os.getenv("UCOA_MODEL_NAME", "")
AGENT_TOKEN = os.getenv("UCOA_AGENT_TOKEN", "")

ACTIONS = [
    "open_url", "open_app_by_name", "click_any_text", "type_into_any",
    "tap", "long_press", "swipe", "back", "home", "wait", "observe", "done"
]


class PlanRequest(BaseModel):
    task: str
    attachments: list[str] = Field(default_factory=list)
    device: dict[str, Any] = Field(default_factory=dict)


class StepRequest(BaseModel):
    task: str
    step: int = 0
    max_steps: int = 60
    history: list[dict[str, Any]] = Field(default_factory=list)
    ui_tree: str = "[]"
    screenshot_base64: str | None = None
    capabilities: list[str] = Field(default_factory=lambda: ACTIONS.copy())


def auth(authorization: str | None) -> None:
    if AGENT_TOKEN and authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid agent token")


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\\s*", "", text)
        text = re.sub(r"\\s*```$", "", text)
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\\{.*\\}", text, re.S)
    if match:
        try:
            value = json.loads(match.group(0))
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    raise ValueError("Model did not return a JSON object")


def model_call(system: str, user: str, image_b64: str | None = None) -> str:
    if not MODEL_BASE_URL or not MODEL_NAME:
        raise RuntimeError("AI brain is not configured: UCOA_MODEL_BASE_URL/UCOA_MODEL_NAME")
    content: list[dict[str, Any]] = [{"type": "text", "text": user}]
    if image_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
    payload = {
        "model": MODEL_NAME,
        "temperature": 0.1,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
    }
    url = MODEL_BASE_URL if MODEL_BASE_URL.endswith("/chat/completions") else MODEL_BASE_URL + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if MODEL_API_KEY:
        headers["Authorization"] = f"Bearer {MODEL_API_KEY}"
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=int(os.getenv("UCOA_MODEL_TIMEOUT", "90"))) as response:
            body = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"model request failed: {exc}") from exc
    return str(body.get("choices", [{}])[0].get("message", {}).get("content", ""))


PLAN_SYSTEM = """You are UCOA, a universal computer-use agent planner. Understand Arabic or English tasks.
Do not assume a named app is pre-programmed. The phone agent can operate arbitrary visible Android apps and browsers through semantic UI controls and screenshots.
Return ONLY JSON: {\"summary\":string,\"steps\":string[]}. Make the steps concrete, ordered, and end-to-end."""

STEP_SYSTEM = """You are UCOA, a universal GUI computer-use agent. You control an Android phone.
At every turn, inspect the UI tree and screenshot (when supplied), compare them with the task and action history, and choose exactly ONE next action.
You may use only these actions: open_url, open_app_by_name, click_any_text, type_into_any, tap, long_press, swipe, back, home, wait, observe, done.
Never fabricate coordinates when a semantic target is visible. Use tap only when screenshot evidence gives a clear coordinate.
Return ONLY JSON with this schema:
{\"action\":string,\"params\":object,\"message\":string,\"done\":boolean,\"wait_after_ms\":integer}
Declare done=true only when the requested outcome is actually visible/verified. On recoverable failure choose another observation or corrective action instead of giving up."""


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "brain_configured": bool(MODEL_BASE_URL and MODEL_NAME), "model": MODEL_NAME or None}


@app.post("/v1/agent/plan")
def plan(req: PlanRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    prompt = json.dumps({"task": req.task, "attachments": req.attachments, "device": req.device}, ensure_ascii=False)
    try:
        result = extract_json(model_call(PLAN_SYSTEM, prompt))
        steps = result.get("steps") if isinstance(result.get("steps"), list) else []
        return {"summary": str(result.get("summary", "خطة عالمية مولدة بواسطة عقل AI")), "steps": [str(x) for x in steps]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/agent/step")
def step(req: StepRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    prompt = json.dumps({
        "task": req.task, "step": req.step, "max_steps": req.max_steps,
        "history": req.history[-12:], "ui_tree": req.ui_tree[:50000],
        "capabilities": req.capabilities,
    }, ensure_ascii=False)
    try:
        result = extract_json(model_call(STEP_SYSTEM, prompt, req.screenshot_base64))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    action = str(result.get("action", "observe"))
    if action not in ACTIONS:
        action = "observe"
    result["action"] = action
    result["params"] = result.get("params") if isinstance(result.get("params"), dict) else {}
    result["done"] = bool(result.get("done", action == "done"))
    result["wait_after_ms"] = max(150, min(5000, int(result.get("wait_after_ms", 700))))
    result["message"] = str(result.get("message", ""))
    return result
