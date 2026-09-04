from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="UCOA Universal Agent Brain", version="2.0.0")

# Provider routing. Local Render model remains the deterministic fallback.
LOCAL_BASE_URL = os.getenv("UCOA_MODEL_BASE_URL", "").rstrip("/")
LOCAL_MODEL = os.getenv("UCOA_MODEL_NAME", "Qwen2.5-0.5B-Instruct-Q2_K")
LOCAL_API_KEY = os.getenv("UCOA_MODEL_API_KEY", "")
HF_ROUTER_URL = os.getenv("UCOA_HF_ROUTER_URL", "https://router.huggingface.co/v1").rstrip("/")
HF_TOKEN = os.getenv("HF_TOKEN", "")
REASONING_MODEL = os.getenv("UCOA_REASONING_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
VISION_SPACE_URL = os.getenv("UCOA_VISION_SPACE_URL", "https://akhaliq-qwen3-vl-2b-instruct.hf.space").rstrip("/")
VISION_MODEL = os.getenv("UCOA_VISION_MODEL", "Qwen/Qwen3-VL-2B-Instruct")
VISION_ENABLED = os.getenv("UCOA_LOCAL_VISION", "true").lower() == "true"
EXTERNAL_BASE_URL = os.getenv("UCOA_FALLBACK_BASE_URL", "").rstrip("/")
EXTERNAL_API_KEY = os.getenv("UCOA_FALLBACK_API_KEY", "")
EXTERNAL_MODEL = os.getenv("UCOA_FALLBACK_MODEL", "")
AGENT_TOKEN = os.getenv("UCOA_AGENT_TOKEN", "")
DB_PATH = Path(os.getenv("UCOA_STATE_DB", "/opt/render/project/src/.ucoa-local/state.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ACTIONS = ["open_url", "open_app_by_name", "click_any_text", "type_into_any", "share_attachment", "tap", "long_press", "swipe", "back", "home", "wait", "observe", "done"]
DANGEROUS_WORDS = ["password", "passcode", "pin", "otp", "verification code", "token", "card number", "cvv", "شراء", "دفع", "حذف", "مراسلة", "إرسال", "كلمة المرور", "رمز التحقق", "بطاقة"]
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ucoa-brain")
JOBS: dict[str, dict[str, Any]] = {}
JOB_LOCK = threading.Lock()
DB_LOCK = threading.Lock()

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
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL)")
    conn.commit()
    return conn


def ensure_session(session_id: str | None, title: str = "UCOA session") -> str:
    sid = session_id or uuid.uuid4().hex
    now = __import__("time").time()
    with DB_LOCK:
        conn = db()
        try:
            conn.execute("INSERT OR IGNORE INTO sessions(id,title,created_at,updated_at) VALUES(?,?,?,?)", (sid, title, now, now))
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, sid))
            conn.commit()
        finally:
            conn.close()
    return sid


def remember(session_id: str | None, kind: str, payload: Any) -> str:
    sid = ensure_session(session_id)
    now = __import__("time").time()
    with DB_LOCK:
        conn = db()
        try:
            conn.execute("INSERT INTO events(id,session_id,kind,payload,created_at) VALUES(?,?,?,?,?)", (uuid.uuid4().hex, sid, kind, json.dumps(payload, ensure_ascii=False), now))
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, sid))
            conn.commit()
        finally:
            conn.close()
    return sid


def recent_events(session_id: str | None, limit: int = 16) -> list[dict[str, Any]]:
    if not session_id:
        return []
    ensure_session(session_id)
    with DB_LOCK:
        conn = db()
        try:
            rows = conn.execute("SELECT kind,payload FROM events WHERE session_id=? ORDER BY created_at DESC LIMIT ?", (session_id, max(1, min(limit, 64)))).fetchall()
        finally:
            conn.close()
    result: list[dict[str, Any]] = []
    for kind, payload in reversed(rows):
        try:
            result.append({"kind": kind, **json.loads(payload)})
        except Exception:
            result.append({"kind": kind, "text": payload})
    return result


def auth(authorization: str | None) -> None:
    if AGENT_TOKEN and authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid agent token")


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        value = json.loads(match.group(0))
        if isinstance(value, dict):
            return value
    raise ValueError("Model did not return a JSON object")


def http_chat(base_url: str, api_key: str, model: str, system: str, user: str, image_b64: str | None = None, timeout: int = 120) -> str:
    if not base_url or not model:
        raise RuntimeError("provider not configured")
    content: Any = user
    if image_b64:
        content = [
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": int(os.getenv("UCOA_MAX_TOKENS", "96")),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
    }
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with urlopen(Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST"), timeout=timeout) as response:
            body = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"provider request failed: {exc}") from exc
    return str(body.get("choices", [{}])[0].get("message", {}).get("content", ""))


def vision_space_chat(prompt: str, image_b64: str) -> str:
    """Use the public HF Qwen3-VL-2B ZeroGPU Space when a direct HF token is not configured."""
    try:
        from gradio_client import Client, handle_file
    except ImportError as exc:
        raise RuntimeError("gradio_client is not installed") from exc
    suffix = ".jpg"
    raw = base64.b64decode(image_b64)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(raw)
        tmp.flush()
        client = Client(VISION_SPACE_URL, verbose=False)
        message = {"text": prompt, "files": [handle_file(tmp.name)]}
        result = client.predict(message, [], api_name="/qwen_chat_fn")
        return str(result)


def call_vision(system: str, user: str, image_b64: str) -> tuple[str, str]:
    if not VISION_ENABLED or not image_b64:
        raise RuntimeError("vision disabled")
    if HF_TOKEN:
        try:
            raw = http_chat(HF_ROUTER_URL, HF_TOKEN, VISION_MODEL, system, user, image_b64, timeout=120)
            return raw, "huggingface-router"
        except Exception:
            pass
    raw = vision_space_chat(system + "\n" + user, image_b64)
    return raw, "huggingface-space"


def model_route(role: str, system: str, user: str, image_b64: str | None = None) -> tuple[str, str]:
    # Vision first when a screenshot/image exists.
    if image_b64 and VISION_ENABLED:
        try:
            return call_vision(system, user, image_b64)
        except Exception:
            pass
    # Strong reasoning path when HF Inference Providers is authenticated.
    if role == "reasoning" and HF_TOKEN:
        try:
            return http_chat(HF_ROUTER_URL, HF_TOKEN, REASONING_MODEL, system, user, None, timeout=150), "huggingface-router"
        except Exception:
            pass
    # Optional future external provider.
    if EXTERNAL_BASE_URL and EXTERNAL_MODEL:
        try:
            return http_chat(EXTERNAL_BASE_URL, EXTERNAL_API_KEY, EXTERNAL_MODEL, system, user, image_b64, timeout=150), "external-fallback"
        except Exception:
            pass
    # Local Render model.
    return http_chat(LOCAL_BASE_URL, LOCAL_API_KEY, LOCAL_MODEL, system, user, None, timeout=int(os.getenv("UCOA_MODEL_TIMEOUT", "180"))), "render-local"


def safety_check(task: str, decision: dict[str, Any], approved_risks: bool = False) -> dict[str, Any]:
    action = str(decision.get("action", "observe"))
    params = decision.get("params") if isinstance(decision.get("params"), dict) else {}
    text = (task + " " + json.dumps(params, ensure_ascii=False)).lower()
    reasons: list[str] = []
    if action not in ACTIONS:
        reasons.append("unsupported_action")
    if action == "type_into_any" and any(word in text for word in DANGEROUS_WORDS):
        reasons.append("sensitive_input")
    if action == "share_attachment":
        reasons.append("external_share")
    if any(word in text for word in DANGEROUS_WORDS) and action in {"tap", "click_any_text", "type_into_any", "open_url", "open_app_by_name"}:
        reasons.append("high_impact_task")
    blocked = bool(reasons) and not approved_risks
    return {"allowed": not blocked, "requires_confirmation": blocked, "reasons": reasons, "policy_version": "1.0"}


def verify_decision(req: VerifyRequest) -> dict[str, Any]:
    verdict = safety_check(req.task, req.decision, req.approved_risks)
    remember(req.session_id, "verification", {"decision": req.decision, "verdict": verdict})
    return verdict


def fallback_plan(raw: str, task: str) -> dict[str, Any]:
    clean = re.sub(r"\s+", " ", raw).strip()
    chunks = [x.strip(" •-–—\t") for x in re.split(r"[\n.!؟]+", clean) if x.strip()]
    if not chunks:
        chunks = [task]
    steps = chunks[:3]
    if len(steps) == 1:
        steps = ["ابدأ بتنفيذ المطلوب على الشاشة.", "نفذ الإجراء المطلوب ثم تحقق من النتيجة."]
    return {"summary": clean[:220] or "خطة مولدة بواسطة العقل", "steps": steps, "output_mode": "repair"}


def fallback_step(raw: str, req: StepRequest) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", raw).strip().lower()
    ui = req.ui_tree.lower()
    for label in ["continue", "التالي", "متابعة", "موافق", "ok", "تأكيد", "submit", "إرسال"]:
        if label.lower() in text or label.lower() in ui:
            return {"action": "click_any_text", "params": {"text": label}, "message": "اختيار الزر الظاهر على الشاشة", "done": False, "wait_after_ms": 700, "output_mode": "repair"}
    if any(k in text for k in ["رجوع", "back"]):
        return {"action": "back", "params": {}, "message": "رجوع", "done": False, "wait_after_ms": 500, "output_mode": "repair"}
    if any(k in text for k in ["انتظر", "wait"]):
        return {"action": "wait", "params": {"ms": 1000}, "message": "انتظار استقرار الشاشة", "done": False, "wait_after_ms": 1000, "output_mode": "repair"}
    return {"action": "observe", "params": {}, "message": raw[:240], "done": False, "wait_after_ms": 500, "output_mode": "repair"}

PLAN_SYSTEM = "You are UCOA planner. Return compact JSON with summary and 2-5 ordered steps. Think about the user's task, available device, previous session memory, and attachments. Never invent that an action succeeded."
STEP_SYSTEM = "You are UCOA Android operator. Choose exactly one allowed action using the current UI tree, screenshot, task, history and session memory. Return compact JSON {action,params,message,done,wait_after_ms}. Never claim success before verification."


def _submit(kind: str, fn) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    with JOB_LOCK:
        JOBS[job_id] = {"status": "pending", "kind": kind}

    def runner() -> None:
        with JOB_LOCK:
            JOBS[job_id]["status"] = "running"
        try:
            result = fn()
            with JOB_LOCK:
                JOBS[job_id].update(status="completed", result=result)
        except Exception as exc:
            with JOB_LOCK:
                JOBS[job_id].update(status="failed", error=str(exc))

    JOB_EXECUTOR.submit(runner)
    return {"job_id": job_id, "status": "pending"}


def _job(job_id: str) -> dict[str, Any]:
    with JOB_LOCK:
        result = dict(JOBS.get(job_id, {}))
    if not result:
        raise HTTPException(status_code=404, detail="Unknown job")
    if result.get("status") == "failed":
        raise HTTPException(status_code=503, detail=result.get("error", "job failed"))
    return result


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "brain_configured": bool(LOCAL_BASE_URL and LOCAL_MODEL),
        "model": LOCAL_MODEL,
        "local_vision": VISION_ENABLED,
        "vision_model": VISION_MODEL,
        "vision_provider": "huggingface-router-or-space" if VISION_ENABLED else None,
        "reasoning_model": REASONING_MODEL,
        "reasoning_provider": "huggingface-router" if HF_TOKEN else "render-local-fallback",
        "external_fallback_configured": bool(EXTERNAL_BASE_URL and EXTERNAL_MODEL),
        "structured_output": "best_effort_with_repair",
        "state_persistence": True,
        "verifier": True,
        "version": app.version,
    }


@app.post("/v1/agent/sessions")
def create_session(req: SessionRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return {"session_id": ensure_session(req.session_id, req.title)}


@app.get("/v1/agent/sessions/{session_id}")
def get_session(session_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return {"session_id": session_id, "events": recent_events(session_id, 48)}


@app.post("/v1/agent/verify")
def verify(req: VerifyRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return verify_decision(req)


@app.post("/v1/agent/plan")
def plan(req: PlanRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return _submit("plan", lambda: _run_plan(req))


def _run_plan(req: PlanRequest) -> dict[str, Any]:
    sid = ensure_session(req.session_id, "UCOA task")
    memory = recent_events(sid, 12)
    prompt = {"task": req.task, "attachments": req.attachments[:8], "device": req.device, "memory": memory[-12:]}
    raw, provider = model_route("reasoning", PLAN_SYSTEM, json.dumps(prompt, ensure_ascii=False))
    try:
        result = extract_json(raw)
        steps = result.get("steps") if isinstance(result.get("steps"), list) else []
        if steps:
            final = {"summary": str(result.get("summary", "خطة مولدة بواسطة الذكاء الاصطناعي")), "steps": [str(x) for x in steps[:5]], "output_mode": "model", "provider": provider, "session_id": sid}
            remember(sid, "plan", final)
            return final
    except Exception:
        pass
    final = fallback_plan(raw, req.task)
    final.update(provider=provider, session_id=sid)
    remember(sid, "plan", final)
    return final


@app.get("/v1/agent/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return _job(job_id)


@app.post("/v1/agent/step")
def step(req: StepRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    auth(authorization)
    return _submit("step", lambda: _run_step(req))


def _run_step(req: StepRequest) -> dict[str, Any]:
    sid = ensure_session(req.session_id, "UCOA execution")
    memory = recent_events(sid, 16)
    prompt = json.dumps({
        "task": req.task,
        "step": req.step,
        "history": req.history[-6:],
        "session_memory": memory[-16:],
        "ui_tree": req.ui_tree[:14000],
        "apps": req.installed_apps[:100],
        "capabilities": req.capabilities,
    }, ensure_ascii=False)
    raw, provider = model_route("reasoning", STEP_SYSTEM, prompt, req.screenshot_base64 if VISION_ENABLED else None)
    try:
        result = extract_json(raw)
        action = str(result.get("action", "observe"))
        action = action if action in ACTIONS else "observe"
        result["action"] = action
        result["params"] = result.get("params") if isinstance(result.get("params"), dict) else {}
        result["done"] = bool(result.get("done", action == "done"))
        result["wait_after_ms"] = max(150, min(5000, int(result.get("wait_after_ms", 500))))
        result["message"] = str(result.get("message", ""))
    except Exception:
        result = fallback_step(raw, req)
    result["provider"] = provider
    result["session_id"] = sid
    result["verification"] = safety_check(req.task, result, req.approved_risks)
    remember(sid, "decision", result)
    return result
