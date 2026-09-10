"""Production entrypoint for UCOA V4 with native Gemini + routed cloud fallbacks."""
from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error

import app_v4_runtime  # noqa: F401,E402
import cloud_runtime  # noqa: F401,E402
import app_v3
import openai_provider
import provider_router
import durable_state
from observability import init_sentry

init_sentry()
OPENAI_PRIMARY = os.getenv("UCOA_OPENAI_PRIMARY", "false").lower() == "true"

_VALID_GEMINI_MODELS = {
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
    "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite",
    "gemini-2.0-flash", "gemini-2.0-flash-lite",
}
_DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def _gemini_configured() -> bool:
    return any(os.getenv(k, "").strip() for k in ("UCOA_GEMINI_API_KEY", "GEMINI_API_KEY"))


def _gemini_key() -> str:
    return (os.getenv("UCOA_GEMINI_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip())


def _gemini_model() -> str:
    configured = os.getenv("UCOA_GEMINI_MODEL", "").strip()
    return configured if configured in _VALID_GEMINI_MODELS else _DEFAULT_GEMINI_MODEL


def _gemini_native(system: str, user: str, image: str | None = None) -> str:
    if not _gemini_configured():
        raise RuntimeError("Gemini API key not configured")
    parts = [{"text": user}]
    if image:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image}})
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": min(max(int(os.getenv("UCOA_PROVIDER_MAX_TOKENS", "512")), 64), 2048),
        },
    }
    if _gemini_model().startswith("gemini-3."):
        payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "low"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_gemini_model()}:generateContent"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": _gemini_key()},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    fragments = []
    for part in (candidates[0].get("content") or {}).get("parts", []):
        text = part.get("text") if isinstance(part, dict) else None
        if text:
            fragments.append(text)
    result = "".join(fragments).strip()
    if not result:
        raise RuntimeError("Gemini returned empty content")
    return result


def _qwen_native(system: str, user: str, image: str | None = None) -> str:
    """Use the production Qwen3-VL-235B Space as the final cloud fallback."""
    prompt = system + "\n" + user
    return app_v4_runtime._space_predict(prompt, image)


def _provider_reasoning(system, user):
    if _gemini_configured() and not OPENAI_PRIMARY:
        try:
            return _gemini_native(system, user), f"gemini:{_gemini_model()}"
        except Exception:
            pass
    if OPENAI_PRIMARY and openai_provider.configured():
        try:return openai_provider.reasoning(system, user), "openai"
        except Exception:pass
    try:return provider_router.reasoning(system, user)
    except Exception as primary_error:
        try:return _qwen_native(system, user), "huggingface-qwen3-vl-235b"
        except Exception:
            return app_v3._legacy_reasoning(system, user) if hasattr(app_v3, "_legacy_reasoning") else ("{\"action\":\"observe\"}", "repair")


def _provider_visual(task, ui_tree, image):
    if _gemini_configured() and image and not OPENAI_PRIMARY:
        try:
            system=("أنت محرك الرؤية لوكيل عملي على هاتف أندرويد. افحص لقطة الشاشة وشجرة الواجهة. "
                    "أعد JSON فقط: {\"screen_summary\":string,\"elements\":[{\"text\":string,\"role\":string,\"x\":number,\"y\":number}],\"visible_goal_state\":string,\"confidence\":number}. "
                    "لا تخترع عناصر غير ظاهرة، والإحداثيات بين صفر وألف.")
            user=json.dumps({"task":task,"ui_tree":ui_tree[:18000]}, ensure_ascii=False)
            return app_v3.extract_json(_gemini_native(system, user, image)), f"gemini:{_gemini_model()}"
        except Exception:
            pass
    if OPENAI_PRIMARY and openai_provider.configured():
        try:
            system=("You are UCOA visual perception. Inspect only the current Android screenshot and UI tree. "
                    "Return ONLY valid JSON: {\"screen_summary\":string,\"elements\":[{\"text\":string,\"role\":string,\"x\":number,\"y\":number}],\"visible_goal_state\":string,\"confidence\":number}. "
                    "Never invent unseen elements. Coordinates must be normalized to 0..1000.")
            user=json.dumps({"task":task,"ui_tree":ui_tree[:18000]},ensure_ascii=False)
            return app_v3.extract_json(openai_provider.visual(system,user,image)),"openai"
        except Exception:pass
    try:return provider_router.visual(task,ui_tree,image)
    except Exception as primary_error:
        try:
            system=("You are UCOA visual perception. Inspect only the current Android screenshot and UI tree. "
                    "Return ONLY valid JSON: {\"screen_summary\":string,\"elements\":[{\"text\":string,\"role\":string,\"x\":number,\"y\":number}],\"visible_goal_state\":string,\"confidence\":number}. "
                    "Never invent unseen elements. Coordinates must be normalized to 0..1000.")
            user=json.dumps({"task":task,"ui_tree":ui_tree[:18000]},ensure_ascii=False)
            return app_v3.extract_json(_qwen_native(system, user, image)), "huggingface-qwen3-vl-235b"
        except Exception:
            return app_v3._legacy_visual(task,ui_tree,image) if hasattr(app_v3, "_legacy_visual") else ({"screen_summary":"unavailable","elements":[]},"repair")

# Preserve original seams for tests before replacing runtime callables.
if not hasattr(app_v3, "_legacy_reasoning"):
    app_v3._legacy_reasoning = app_v3.reasoning
if not hasattr(app_v3, "_legacy_visual"):
    app_v3._legacy_visual = app_v3.visual

app_v3.reasoning = _provider_reasoning
app_v3.visual = _provider_visual
app_v3.call_vision = _provider_visual

_legacy_save_state = app_v3.save_state

def _durable_save_state(session_id, state):
    _legacy_save_state(session_id, state)
    try:
        task = str(state.get("task", "")); step = int(state.get("step", 0)); status = str(state.get("phase", "unknown"))
        durable_state.save_state(session_id, session_id, task, step, status, state)
    except Exception:
        pass
app_v3.save_state = _durable_save_state

@app_v3.app.get("/v1/providers/probe")
def providers_probe():
    rows = []
    if _gemini_configured():
        try:
            text = _gemini_native("Return ONLY JSON.", "Return exactly {\"ok\":true}.")
            rows.append({"provider":"gemini","model":_gemini_model(),"ok":True,"vision":True})
            runtime = {"ok":True,"provider":f"gemini:{_gemini_model()}"}
            return {"ok":True,"configured":True,"providers":rows,"runtime":runtime,"response":app_v3.extract_json(text)}
        except Exception as exc:
            rows.append({"provider":"gemini","model":_gemini_model(),"ok":False,"vision":True,"error":type(exc).__name__})
    try:
        result = provider_router.safe_text_probe()
    except Exception:
        result = {"ok":False,"configured":True,"providers":[]}
    runtime = result.get("runtime", {})
    if not runtime:
        try:
            _, provider = provider_router.reasoning("Return ONLY JSON.", "Return exactly {\"ok\":true}.")
            runtime = {"ok":True,"provider":provider}
        except Exception as exc:
            runtime = {"ok":False,"error":type(exc).__name__}
    result["runtime"] = runtime
    result["providers"] = rows + result.get("providers", [])
    result["ok"] = bool(runtime.get("ok")) or any(x.get("ok") for x in result["providers"])
    if not result["ok"]:
        try:
            text = _qwen_native("Return ONLY JSON: {\"ok\":true}.", "Return exactly {\"ok\":true}.")
            result = {
                "ok": True,
                "configured": True,
                "providers": result["providers"] + [{"provider":"huggingface-qwen3-vl-235b","model":os.getenv("UCOA_PRIMARY_VISION_MODEL", "Qwen/Qwen3-VL-235B-A22B-Instruct"),"ok":True,"vision":True}],
                "runtime": {"ok":True,"provider":"huggingface-qwen3-vl-235b"},
                "response": app_v3.extract_json(text),
            }
        except Exception as exc:
            result["qwen_fallback_error"] = type(exc).__name__
    return result

@app_v3.app.get("/v1/providers/models")
def providers_models():
    data=[]
    for p in provider_router.PROVIDERS:
        try:base,key,model,vision,key_name=provider_router._cfg(p)
        except Exception:continue
        data.append({"id":f"{p['name']}:{model}","provider":p["name"],"model":model,"vision":vision,"configured":True,"base_url":base})
    data.append({"id":"huggingface-qwen3-vl-235b:Qwen/Qwen3-VL-235B-A22B-Instruct","provider":"huggingface-qwen3-vl-235b","model":"Qwen/Qwen3-VL-235B-A22B-Instruct","vision":True,"configured":True,"base_url":"huggingface-space"})
    return {"object":"list","data":data}

@app_v3.app.post("/v1/agent/step")
def android_step(req: app_v3.StepRequest, authorization: str | None = None):
    app_v3.auth(authorization)
    runner = getattr(app_v3, "run_step", None)
    if not callable(runner):
        raise RuntimeError("step runtime not initialized")
    return app_v3.submit("step", lambda: runner(req))

@app_v3.app.get("/v1/agent/jobs/{jid}")
def android_job(jid: str, authorization: str | None = None):
    app_v3.auth(authorization)
    with app_v3.JOB_LOCK:
        job = dict(app_v3.JOBS.get(jid, {}))
    if not job:
        return {"status":"not_found","job_id":jid}
    return job

@app_v3.app.get("/v1/agent/state/{session_id}")
def get_agent_state(session_id: str):
    return durable_state.load_state(session_id) or {"task_id":session_id,"status":"not_found"}

@app_v3.app.get("/v1/agent/state/{session_id}/events")
def get_agent_events(session_id: str):
    return {"events":durable_state.recent_events(session_id)}

@app_v3.app.get("/v1/storage/status")
def storage_status():
    return {"durable_storage":durable_state.configured()}

app=app_v3.app
