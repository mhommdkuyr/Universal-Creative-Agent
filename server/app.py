from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="UCOA Universal Agent Brain", version="2.1.0")
ACTIONS = ["open_url", "open_app_by_name", "click_any_text", "type_into_any", "share_attachment", "tap", "long_press", "swipe", "back", "home", "wait", "observe", "done"]
DANGEROUS_WORDS = ["password", "passcode", "pin", "otp", "verification code", "token", "card number", "cvv", "شراء", "دفع", "حذف", "إرسال", "كلمة المرور", "رمز التحقق", "بطاقة"]

LOCAL_BASE_URL = os.getenv("UCOA_MODEL_BASE_URL", "").rstrip("/")
LOCAL_MODEL = os.getenv("UCOA_MODEL_NAME", "Qwen2.5-0.5B-Instruct-Q2_K")
LOCAL_API_KEY = os.getenv("UCOA_MODEL_API_KEY", "")
HF_ROUTER_URL = os.getenv("UCOA_HF_ROUTER_URL", "https://router.huggingface.co/v1").rstrip("/")
HF_TOKEN = os.getenv("HF_TOKEN", "")
REASONING_MODEL = os.getenv("UCOA_REASONING_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
VISION_MODEL = os.getenv("UCOA_VISION_MODEL", "Qwen/Qwen3-VL-2B-Instruct")
VISION_SPACE_URL = os.getenv("UCOA_VISION_SPACE_URL", "https://akhaliq-qwen3-vl-2b-instruct.hf.space").rstrip("/")
VISION_ENABLED = os.getenv("UCOA_LOCAL_VISION", "true").lower() == "true"
EXTERNAL_BASE_URL = os.getenv("UCOA_FALLBACK_BASE_URL", "").rstrip("/")
EXTERNAL_API_KEY = os.getenv("UCOA_FALLBACK_API_KEY", "")
EXTERNAL_MODEL = os.getenv("UCOA_FALLBACK_MODEL", "")
AGENT_TOKEN = os.getenv("UCOA_AGENT_TOKEN", "")
DB_PATH = Path(os.getenv("UCOA_STATE_DB", "/opt/render/project/src/.ucoa-local/state.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict[str, Any]] = {}
JOB_LOCK = threading.Lock()
DB_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ucoa-brain")

class PlanRequest(BaseModel):
    task: str
    attachments: list[str] = Field(default_factory=list)
    device: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None

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
    session_id: str | None = None
    approved_risks: bool = False

class VerifyRequest(BaseModel):
    task: str
    decision: dict[str, Any]
    approved_risks: bool = False
    session_id: str | None = None

class SessionRequest(BaseModel):
    session_id: str | None = None
    title: str = "UCOA session"


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL)")
    c.commit()
    return c


def ensure_session(sid: str | None, title: str = "UCOA session") -> str:
    sid = sid or uuid.uuid4().hex
    now = time.time()
    with DB_LOCK:
        c = db()
        try:
            c.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?,?)", (sid, title, now, now))
            c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, sid))
            c.commit()
        finally:
            c.close()
    return sid


def remember(sid: str | None, kind: str, payload: Any) -> str:
    sid = ensure_session(sid)
    now = time.time()
    with DB_LOCK:
        c = db()
        try:
            c.execute("INSERT INTO events VALUES(?,?,?,?,?)", (uuid.uuid4().hex, sid, kind, json.dumps(payload, ensure_ascii=False), now))
            c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, sid))
            c.commit()
        finally:
            c.close()
    return sid


def memory(sid: str | None, limit: int = 16) -> list[dict[str, Any]]:
    if not sid:
        return []
    ensure_session(sid)
    with DB_LOCK:
        c = db()
        try:
            rows = c.execute("SELECT kind,payload FROM events WHERE session_id=? ORDER BY created_at DESC LIMIT ?", (sid, min(max(limit, 1), 64))).fetchall()
        finally:
            c.close()
    out = []
    for kind, payload in reversed(rows):
        try:
            out.append({"kind": kind, **json.loads(payload)})
        except Exception:
            out.append({"kind": kind, "text": payload})
    return out


def auth(authorization: str | None) -> None:
    if AGENT_TOKEN and authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(401, "Invalid agent token")


def extract_json(text: str) -> dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        x = json.loads(t)
        if isinstance(x, dict):
            return x
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        x = json.loads(m.group(0))
        if isinstance(x, dict):
            return x
    raise ValueError("no JSON object")


def http_chat(base: str, key: str, model: str, system: str, user: str, image_b64: str | None = None, timeout: int = 120) -> str:
    if not base or not model:
        raise RuntimeError("provider not configured")
    content: Any = user
    if image_b64:
        content = [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]
    payload = {"model": model, "temperature": 0, "max_tokens": int(os.getenv("UCOA_MAX_TOKENS", "96")), "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with urlopen(Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST"), timeout=timeout) as r:
            body = json.loads(r.read().decode())
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"provider request failed: {exc}") from exc
    return str(body.get("choices", [{}])[0].get("message", {}).get("content", ""))


def vision_space(prompt: str, image_b64: str) -> str:
    from gradio_client import Client, handle_file
    raw = base64.b64decode(image_b64)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as f:
        f.write(raw); f.flush()
        client = Client(VISION_SPACE_URL, verbose=False)
        message = {"text": prompt, "files": [handle_file(f.name)]}
        return str(client.predict(message, [], api_name="/qwen_chat_fn"))


def call_vision(prompt: str, image_b64: str) -> tuple[str, str]:
    if not VISION_ENABLED:
        raise RuntimeError("vision disabled")
    if HF_TOKEN:
        try:
            return http_chat(HF_ROUTER_URL, HF_TOKEN, VISION_MODEL, "Analyze the provided Android screen precisely. Return factual visual observations only.", prompt, image_b64, 120), "huggingface-router"
        except Exception:
            pass
    return vision_space(prompt, image_b64), "huggingface-space"


def reasoning(system: str, user: str) -> tuple[str, str]:
    if HF_TOKEN:
        try:
            return http_chat(HF_ROUTER_URL, HF_TOKEN, REASONING_MODEL, system, user, None, 150), "huggingface-router"
        except Exception:
            pass
    if EXTERNAL_BASE_URL and EXTERNAL_MODEL:
        try:
            return http_chat(EXTERNAL_BASE_URL, EXTERNAL_API_KEY, EXTERNAL_MODEL, system, user, None, 150), "external-fallback"
        except Exception:
            pass
    return http_chat(LOCAL_BASE_URL, LOCAL_API_KEY, LOCAL_MODEL, system, user, None, int(os.getenv("UCOA_MODEL_TIMEOUT", "180"))), "render-local"


def safety(task: str, decision: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    action = str(decision.get("action", "observe"))
    params = decision.get("params") if isinstance(decision.get("params"), dict) else {}
    text = (task + " " + json.dumps(params, ensure_ascii=False)).lower()
    reasons = []
    if action not in ACTIONS: reasons.append("unsupported_action")
    if action == "share_attachment": reasons.append("external_share")
    if action == "type_into_any" and any(w in text for w in DANGEROUS_WORDS): reasons.append("sensitive_input")
    if any(w in text for w in DANGEROUS_WORDS) and action in {"tap", "click_any_text", "type_into_any", "open_url", "open_app_by_name"}: reasons.append("high_impact_task")
    blocked = bool(reasons) and not approved
    return {"allowed": not blocked, "requires_confirmation": blocked, "reasons": reasons, "policy_version": "1.1"}


def fallback_plan(raw: str, task: str) -> dict[str, Any]:
    clean = re.sub(r"\s+", " ", raw).strip()
    parts = [x.strip(" •-–—\t") for x in re.split(r"[\n.!؟]+", clean) if x.strip()][:3]
    if len(parts) < 2: parts = ["افهم الشاشة والهدف الحالي.", "نفذ الإجراء المطلوب ثم تحقق من النتيجة."]
    return {"summary": clean[:240] or task[:240], "steps": parts, "output_mode": "repair"}


def fallback_step(raw: str, req: StepRequest) -> dict[str, Any]:
    t = re.sub(r"\s+", " ", raw).strip().lower(); ui = req.ui_tree.lower()
    for label in ["continue", "التالي", "متابعة", "موافق", "ok", "تأكيد", "submit", "إرسال"]:
        if label in t or label in ui:
            return {"action": "click_any_text", "params": {"text": label}, "message": "اختيار زر واضح", "done": False, "wait_after_ms": 700}
    if "back" in t or "رجوع" in t: return {"action": "back", "params": {}, "message": "رجوع", "done": False, "wait_after_ms": 500}
    return {"action": "observe", "params": {}, "message": raw[:220], "done": False, "wait_after_ms": 500}

PLAN_SYSTEM = "You are UCOA planner. Return only compact JSON {summary,steps}. Produce 2-5 concrete ordered steps. Never claim an action already succeeded."
STEP_SYSTEM = "You are UCOA Android reasoning controller. Use task, visual observation, UI tree, history, memory and capabilities. Return only compact JSON {action,params,message,done,wait_after_ms}. Choose exactly one allowed action. Never claim success before verification."


def submit(kind: str, fn) -> dict[str, Any]:
    jid = uuid.uuid4().hex
    with JOB_LOCK: JOBS[jid] = {"status": "pending", "kind": kind}
    def run() -> None:
        with JOB_LOCK: JOBS[jid]["status"] = "running"
        try:
            with JOB_LOCK: JOBS[jid].update(status="completed", result=fn())
        except Exception as exc:
            with JOB_LOCK: JOBS[jid].update(status="failed", error=str(exc))
    EXECUTOR.submit(run)
    return {"job_id": jid, "status": "pending"}


def job(jid: str) -> dict[str, Any]:
    with JOB_LOCK: x = dict(JOBS.get(jid, {}))
    if not x: raise HTTPException(404, "Unknown job")
    if x.get("status") == "failed": raise HTTPException(503, x.get("error", "job failed"))
    return x

@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "brain_configured": bool(LOCAL_BASE_URL and LOCAL_MODEL), "model": LOCAL_MODEL, "local_vision": VISION_ENABLED, "vision_model": VISION_MODEL, "vision_provider": "huggingface-router-or-space" if VISION_ENABLED else None, "reasoning_model": REASONING_MODEL, "reasoning_provider": "huggingface-router" if HF_TOKEN else "render-local-fallback", "external_fallback_configured": bool(EXTERNAL_BASE_URL and EXTERNAL_MODEL), "state_persistence": True, "verifier": True, "routing": True, "version": app.version}

@app.post("/v1/agent/sessions")
def create_session(req: SessionRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization); return {"session_id": ensure_session(req.session_id, req.title)}

@app.get("/v1/agent/sessions/{session_id}")
def get_session(session_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization); return {"session_id": session_id, "events": memory(session_id, 48)}

@app.post("/v1/agent/verify")
def verify(req: VerifyRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization); return {"session_id": remember(req.session_id, "verification", {"decision": req.decision, "verdict": safety(req.task, req.decision, req.approved_risks)}), **safety(req.task, req.decision, req.approved_risks)}

@app.post("/v1/agent/plan")
def plan(req: PlanRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization); return submit("plan", lambda: run_plan(req))

def run_plan(req: PlanRequest) -> dict[str, Any]:
    sid = ensure_session(req.session_id, "UCOA task")
    prompt = json.dumps({"task": req.task, "attachments": req.attachments[:8], "device": req.device, "memory": memory(sid, 12)}, ensure_ascii=False)
    raw, provider = reasoning(PLAN_SYSTEM, prompt)
    try:
        x = extract_json(raw); steps = x.get("steps") if isinstance(x.get("steps"), list) else []
        if steps:
            out = {"summary": str(x.get("summary", "خطة مولدة بواسطة الذكاء الاصطناعي")), "steps": [str(s) for s in steps[:5]], "output_mode": "model", "provider": provider, "session_id": sid}
        else: raise ValueError
    except Exception:
        out = fallback_plan(raw, req.task); out.update(provider=provider, session_id=sid)
    remember(sid, "plan", out); return out

@app.get("/v1/agent/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization); return job(job_id)

@app.post("/v1/agent/step")
def step(req: StepRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization); return submit("step", lambda: run_step(req))

def run_step(req: StepRequest) -> dict[str, Any]:
    sid = ensure_session(req.session_id, "UCOA execution")
    visual = ""
    vision_provider = None
    if req.screenshot_base64 and VISION_ENABLED:
        try:
            visual, vision_provider = call_vision("Describe the current Android screen, identify visible controls, text, app identity, spatial relationships, dialogs and the most relevant target for the requested task. Be factual and concise.", req.screenshot_base64)
            remember(sid, "visual_observation", {"text": visual[:6000], "provider": vision_provider, "step": req.step})
        except Exception as exc:
            visual = f"vision_unavailable: {str(exc)[:240]}"
    prompt = json.dumps({"task": req.task, "step": req.step, "history": req.history[-8:], "session_memory": memory(sid, 16), "visual_observation": visual[:9000], "ui_tree": req.ui_tree[:14000], "apps": req.installed_apps[:100], "capabilities": req.capabilities}, ensure_ascii=False)
    raw, provider = reasoning(STEP_SYSTEM, prompt)
    try:
        result = extract_json(raw)
    except Exception:
        result = fallback_step(raw, req)
    action = str(result.get("action", "observe")); result["action"] = action if action in ACTIONS else "observe"
    result["params"] = result.get("params") if isinstance(result.get("params"), dict) else {}
    result["done"] = bool(result.get("done", result["action"] == "done"))
    result["wait_after_ms"] = max(150, min(5000, int(result.get("wait_after_ms", 700))))
    result["message"] = str(result.get("message", "")); result["provider"] = provider; result["vision_provider"] = vision_provider; result["visual_observation"] = visual[:6000]; result["session_id"] = sid
    result["verification"] = safety(req.task, result, req.approved_risks)
    remember(sid, "decision", result)
    return result
