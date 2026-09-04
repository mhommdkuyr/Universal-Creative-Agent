from __future__ import annotations

import json, os, re, threading, uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="UCOA Universal Agent Brain", version="1.4.0")
MODEL_BASE_URL = os.getenv("UCOA_MODEL_BASE_URL", "").rstrip("/")
MODEL_API_KEY = os.getenv("UCOA_MODEL_API_KEY", "")
MODEL_NAME = os.getenv("UCOA_MODEL_NAME", "")
AGENT_TOKEN = os.getenv("UCOA_AGENT_TOKEN", "")
LOCAL_VISION = os.getenv("UCOA_LOCAL_VISION", "false").lower() == "true"
ACTIONS = ["open_url", "open_app_by_name", "click_any_text", "type_into_any", "share_attachment", "tap", "long_press", "swipe", "back", "home", "wait", "observe", "done"]
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ucoa-brain")
JOBS: dict[str, dict[str, Any]] = {}
JOB_LOCK = threading.Lock()

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
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        if isinstance(value, dict): return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        value = json.loads(match.group(0))
        if isinstance(value, dict): return value
    raise ValueError("Model did not return a JSON object")

def model_call(system: str, user: str, image_b64: str | None = None) -> str:
    if not MODEL_BASE_URL or not MODEL_NAME: raise RuntimeError("AI brain is not configured")
    multimodal = bool(image_b64) and LOCAL_VISION
    content: Any = user if not multimodal else [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]
    payload = {
        "model": MODEL_NAME,
        "temperature": 0,
        "max_tokens": int(os.getenv("UCOA_MAX_TOKENS", "64")),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
    }
    url = MODEL_BASE_URL if MODEL_BASE_URL.endswith("/chat/completions") else MODEL_BASE_URL + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if MODEL_API_KEY: headers["Authorization"] = f"Bearer {MODEL_API_KEY}"
    try:
        with urlopen(Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST"), timeout=int(os.getenv("UCOA_MODEL_TIMEOUT", "180"))) as response:
            body = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"model request failed: {exc}") from exc
    return str(body.get("choices", [{}])[0].get("message", {}).get("content", ""))

def _submit(kind: str, fn) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    with JOB_LOCK: JOBS[job_id] = {"status": "pending", "kind": kind}
    def runner() -> None:
        with JOB_LOCK: JOBS[job_id]["status"] = "running"
        try:
            result = fn()
            with JOB_LOCK: JOBS[job_id].update(status="completed", result=result)
        except Exception as exc:
            with JOB_LOCK: JOBS[job_id].update(status="failed", error=str(exc))
    JOB_EXECUTOR.submit(runner)
    return {"job_id": job_id, "status": "pending"}

def _job(job_id: str) -> dict[str, Any]:
    with JOB_LOCK: result = dict(JOBS.get(job_id, {}))
    if not result: raise HTTPException(status_code=404, detail="Unknown job")
    if result.get("status") == "failed": raise HTTPException(status_code=503, detail=result.get("error", "job failed"))
    return result

PLAN_SYSTEM = "You are UCOA. Return JSON only: {\"summary\":string,\"steps\":string[]}. Make a minimal 2-3 step plan for the user's task."
STEP_SYSTEM = "You control Android. Return JSON only: {\"action\": one allowed action, \"params\": object, \"message\": string, \"done\": boolean, \"wait_after_ms\": number}. Prefer click_any_text for visible UI labels."

@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "brain_configured": bool(MODEL_BASE_URL and MODEL_NAME), "model": MODEL_NAME or None, "local_vision": LOCAL_VISION}

@app.post("/v1/agent/plan")
def plan(req: PlanRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return _submit("plan", lambda: _run_plan(req))

def _run_plan(req: PlanRequest) -> dict[str, Any]:
    result = extract_json(model_call(PLAN_SYSTEM, json.dumps({"task": req.task, "attachments": req.attachments[:8]}, ensure_ascii=False)))
    steps = result.get("steps") if isinstance(result.get("steps"), list) else []
    if not steps: raise ValueError("Model returned no plan steps")
    return {"summary": str(result.get("summary", "خطة مولدة بواسطة النموذج المحلي")), "steps": [str(x) for x in steps[:5]]}

@app.get("/v1/agent/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return _job(job_id)

@app.post("/v1/agent/step")
def step(req: StepRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return _submit("step", lambda: _run_step(req))

def _run_step(req: StepRequest) -> dict[str, Any]:
    prompt = json.dumps({"task": req.task, "step": req.step, "history": req.history[-4:], "ui_tree": req.ui_tree[:12000], "apps": req.installed_apps[:60], "capabilities": req.capabilities}, ensure_ascii=False)
    result = extract_json(model_call(STEP_SYSTEM, prompt, req.screenshot_base64))
    action = str(result.get("action", "observe")); action = action if action in ACTIONS else "observe"
    result["action"] = action
    result["params"] = result.get("params") if isinstance(result.get("params"), dict) else {}
    result["done"] = bool(result.get("done", action == "done"))
    result["wait_after_ms"] = max(150, min(5000, int(result.get("wait_after_ms", 500))))
    result["message"] = str(result.get("message", ""))
    return result
