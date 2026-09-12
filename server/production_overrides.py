"""Production-safe overrides for planning and Android control.

Production requests use a resilient provider router for each action decision.
The mobile APK keeps the same API contract, so cloud fixes do not require a
new APK installation.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import Header

import app_v3
import app_v4_runtime
import provider_router

_BASE_REASONING = app_v3.reasoning
_BASE_VISUAL = app_v3.visual
_BASE_CALL_VISION = app_v3.call_vision

RECOVERY_PROVIDER = "ucoa-resilient-fallback"


def _extract_plan(raw: str) -> tuple[list[str], str]:
    value = app_v3.extract_json(raw)
    steps = value.get("steps") if isinstance(value.get("steps"), list) else []
    steps = [str(x).strip() for x in steps if str(x).strip()]
    if len(steps) < 2:
        raise ValueError("planner returned fewer than two executable steps")
    return steps[:6], str(value.get("summary") or "خطة قابلة للتحقق")


def _save_plan(sid: str, req: Any, result: dict[str, Any], persist: bool = True) -> dict[str, Any]:
    if persist:
        app_v3.remember(sid, "plan", result)
        app_v3.save_state(sid, {"phase": "planned", "task": req.task, "step": 0, "plan": result})
    return result


def run_plan(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    payload = json.dumps({"task": req.task, "attachments": req.attachments[:8], "device": req.device, "memory": app_v3.memory(sid, 12)}, ensure_ascii=False)
    try:
        raw, provider = provider_router.reasoning(app_v4_runtime.PLANNER, payload)
        steps, summary = _extract_plan(raw)
        return _save_plan(sid, req, {"summary": summary, "steps": steps, "output_mode": "primary_provider_router", "provider": provider, "session_id": sid})
    except Exception as exc:
        task = req.task.lower()
        aliases = {"يوتيوب":"YouTube","youtube":"YouTube","واتساب":"WhatsApp","whatsapp":"WhatsApp","كاب كات":"CapCut","capcut":"CapCut","كانفا":"Canva","canva":"Canva","كروم":"Chrome","chrome":"Chrome","انستجرام":"Instagram","instagram":"Instagram","تليجرام":"Telegram","telegram":"Telegram"}
        app_name = next((label for key, label in aliases.items() if key in task), None)
        steps = [f"افتح {app_name} وحقق من ظهور واجهته." if app_name else "افتح التطبيق أو الموقع المطلوب للمهمة.", f"نفذ الطلب داخل {app_name} وفق العناصر الظاهرة على الشاشة." if app_name else "نفذ المطلوب اعتمادًا على الشاشة الحالية والنص المدخل.", "تحقق بصريًا من النتيجة المطلوبة ولا تعلن النجاح قبل إثباتها."]
        return _save_plan(sid, req, {"summary":"خطة احتياطية قابلة للمراجعة والتنفيذ","steps":steps,"output_mode":"resilient_fallback","provider":RECOVERY_PROVIDER,"session_id":sid,"error":str(exc)})


def _fallback_action(req: Any) -> dict[str, Any]:
    task, ui = req.task.lower(), req.ui_tree.lower(); merged = task + " " + ui
    if req.step == 0:
        for key, label in (("يوتيوب","YouTube"),("youtube","YouTube"),("واتساب","WhatsApp"),("whatsapp","WhatsApp"),("capcut","CapCut"),("كاب كات","CapCut"),("canva","Canva"),("كانفا","Canva"),("chrome","Chrome"),("كروم","Chrome")):
            if key in task:
                return {"action":"open_app_by_name","params":{"app_name":label},"message":f"فتح {label}","done":False,"wait_after_ms":1000,"confidence":0.8}
    for label in ("continue","متابعة","التالي","موافق","ok","submit","إرسال"):
        if label in merged:
            return {"action":"click_any_text","params":{"texts":[label]},"message":"اختيار هدف ظاهر ثم التحقق من التغير","done":False,"wait_after_ms":700,"confidence":0.7}
    return {"action":"observe","params":{},"message":"لم يثبت الهدف بعد؛ إعادة الملاحظة بدل التخمين","done":False,"wait_after_ms":700,"confidence":0.2}


def _save_step(sid: str, req: Any, value: dict[str, Any]) -> dict[str, Any]:
    value["session_id"] = sid
    value["verification"] = app_v3.safety(req.task, value, req.approved_risks)
    app_v3.remember(sid, "decision", value)
    app_v3.save_state(sid, {"phase":"executing","task":req.task,"step":req.step,"last_decision":value})
    return value


def run_step(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    # The former production path called the heavyweight Gradio Qwen Space
    # inside the synchronous Render request. A provider failure could therefore
    # surface to the APK as an HTTP 502 before the fallback decision arrived.
    visual_observation: dict[str, Any] = {"screen_summary":"current Android UI evidence","elements":[],"confidence":0.0}
    vision_provider = "none"
    try:
        if req.screenshot_base64:
            visual_observation, vision_provider = provider_router.visual(req.task, req.ui_tree, req.screenshot_base64)
        else:
            visual_observation = {"screen_summary":"UI tree only; no screenshot supplied","elements":[],"confidence":0.2}
        controller_payload = json.dumps({
            "task": req.task,
            "step": req.step,
            "ui_tree": req.ui_tree[:18000],
            "visual": visual_observation,
            "history": req.history[-10:],
            "installed_apps": req.installed_apps[:250],
            "capabilities": req.capabilities,
        }, ensure_ascii=False)
        raw, provider = provider_router.reasoning(app_v4_runtime.CONTROLLER, controller_payload)
        result = app_v4_runtime._normalize_action(app_v3.extract_json(raw), req.screenshot_base64)
        result.update({
            "provider": provider,
            "reasoning_provider": provider,
            "vision_provider": vision_provider,
            "output_mode": "provider_router_multimodal" if req.screenshot_base64 else "provider_router_text",
            "visual_observation": visual_observation,
        })
        return _save_step(sid, req, result)
    except Exception as exc:
        result = _fallback_action(req)
        result.update({
            "provider": RECOVERY_PROVIDER,
            "reasoning_provider": RECOVERY_PROVIDER,
            "vision_provider": vision_provider or RECOVERY_PROVIDER,
            "output_mode": "resilient_fallback",
            "visual_observation": visual_observation,
            "error": str(exc),
        })
        return _save_step(sid, req, result)


# Preserve the result-verification endpoint contract for the existing APK while
# routing verification to the V4 screenshot-aware verifier.
app_v3.app.routes[:] = [r for r in app_v3.app.routes if getattr(r, "path", "") != "/v1/agent/verify-result"]
@app_v3.app.post("/v1/agent/verify-result")
def production_verify_result(req: app_v3.ResultVerifyRequest, authorization: str | None = Header(default=None)):
    app_v3.auth(authorization)
    return app_v4_runtime.verify_result(req)

app_v3.run_plan = run_plan
app_v3.run_step = run_step
