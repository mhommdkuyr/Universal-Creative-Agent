from __future__ import annotations

import json, os, re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="UCOA Universal Agent Brain", version="1.2.0")
MODEL_BASE_URL = os.getenv("UCOA_MODEL_BASE_URL", "").rstrip("/")
MODEL_API_KEY = os.getenv("UCOA_MODEL_API_KEY", "")
MODEL_NAME = os.getenv("UCOA_MODEL_NAME", "")
AGENT_TOKEN = os.getenv("UCOA_AGENT_TOKEN", "")
LOCAL_VISION = os.getenv("UCOA_LOCAL_VISION", "false").lower() == "true"
ACTIONS = ["open_url", "open_app_by_name", "click_any_text", "type_into_any", "share_attachment", "tap", "long_press", "swipe", "back", "home", "wait", "observe", "done"]

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
    installed_apps: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=lambda: ACTIONS.copy())

def auth(authorization: str | None) -> None:
    if AGENT_TOKEN and authorization != f"Bearer {AGENT_TOKEN}": raise HTTPException(status_code=401, detail="Invalid agent token")

def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"): text = re.sub(r"^```(?:json)?\s*", "", text); text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        if isinstance(value, dict): return value
    except json.JSONDecodeError: pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            value = json.loads(match.group(0))
            if isinstance(value, dict): return value
        except json.JSONDecodeError: pass
    raise ValueError("Model did not return a JSON object")

def model_call(system: str, user: str, image_b64: str | None = None) -> str:
    if not MODEL_BASE_URL or not MODEL_NAME: raise RuntimeError("AI brain is not configured: UCOA_MODEL_BASE_URL/UCOA_MODEL_NAME")
    multimodal = bool(image_b64) and LOCAL_VISION
    user_content: Any
    if multimodal:
        user_content = [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]
    else:
        user_content = user
    payload = {"model": MODEL_NAME, "temperature": 0.1, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}]}
    url = MODEL_BASE_URL if MODEL_BASE_URL.endswith("/chat/completions") else MODEL_BASE_URL + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if MODEL_API_KEY: headers["Authorization"] = f"Bearer {MODEL_API_KEY}"
    timeout = int(os.getenv("UCOA_MODEL_TIMEOUT", "120"))
    try:
        with urlopen(Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST"), timeout=timeout) as response:
            body = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError) as exc: raise RuntimeError(f"model request failed: {exc}") from exc
    return str(body.get("choices", [{}])[0].get("message", {}).get("content", ""))

PLAN_SYSTEM = """You are UCOA, a universal computer-use agent planner. Understand Arabic or English. Do not assume any app is pre-programmed. Plan for arbitrary Android apps and browsers using generic visible UI actions. Return ONLY valid JSON {\"summary\":string,\"steps\":string[]}. Use 3-6 short concrete steps. No markdown."""
STEP_SYSTEM = """You are UCOA, a universal GUI computer-use agent controlling Android. Use the textual UI tree, task, installed apps, recent history, and any available screenshot. Choose exactly ONE next action. Allowed actions: open_url, open_app_by_name, click_any_text, type_into_any, share_attachment, tap, long_press, swipe, back, home, wait, observe, done. Prefer semantic targets. If screenshot is unavailable, rely on the UI tree and task. Return ONLY valid JSON {\"action\":string,\"params\":object,\"message\":string,\"done\":boolean,\"wait_after_ms\":integer}. Set done=true only after the requested outcome is visibly verified. Recover from failures by observing and selecting another valid action."""

@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "brain_configured": bool(MODEL_BASE_URL and MODEL_NAME), "model": MODEL_NAME or None, "local_vision": LOCAL_VISION}

@app.post("/v1/agent/plan")
def plan(req: PlanRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    try:
        payload = {"task": req.task, "attachments": req.attachments[:20], "device": req.device}
        result = extract_json(model_call(PLAN_SYSTEM, json.dumps(payload, ensure_ascii=False)))
        steps = result.get("steps") if isinstance(result.get("steps"), list) else []
        if not steps: raise ValueError("Model returned no plan steps")
        return {"summary": str(result.get("summary", "خطة عالمية مولدة بواسطة عقل AI")), "steps": [str(x) for x in steps[:8]]}
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/v1/agent/step")
def step(req: StepRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    prompt = json.dumps({"task": req.task, "step": req.step, "max_steps": req.max_steps, "history": req.history[-8:], "ui_tree": req.ui_tree[:30000], "installed_apps": req.installed_apps[:120], "attachments": req.attachments[:20], "capabilities": req.capabilities}, ensure_ascii=False)
    try: result = extract_json(model_call(STEP_SYSTEM, prompt, req.screenshot_base64))
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc
    action = str(result.get("action", "observe")); action = action if action in ACTIONS else "observe"
    result.update({"action": action, "params": result.get("params") if isinstance(result.get("params"), dict) else {}, "done": bool(result.get("done", action == "done")), "wait_after_ms": max(150, min(5000, int(result.get("wait_after_ms", 700)))), "message": str(result.get("message", ""))})
    return result
