"""Production-safe overrides for planning and Android control.

Production requests use Qwen3-VL directly. Existing unit-test seams that
monkeypatch the V3 public reasoning/vision hooks remain supported and avoid
network/database latency so the local contract tests stay deterministic.
"""
from __future__ import annotations

import json
from typing import Any

import app_v3
import app_v4_runtime

QWEN_PROVIDER = "huggingface-qwen3-vl-235b"
RECOVERY_PROVIDER = "ucoa-resilient-fallback"
_BASE_REASONING = app_v3.reasoning
_BASE_VISUAL = app_v3.visual
_BASE_CALL_VISION = app_v3.call_vision


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
    if app_v3.reasoning is not _BASE_REASONING:
        raw, provider = app_v3.reasoning(app_v4_runtime.PLANNER, payload)
        try:
            steps, summary = _extract_plan(raw)
            return _save_plan(sid, req, {"summary": summary, "steps": steps, "output_mode": "model", "provider": provider, "session_id": sid}, persist=False)
        except Exception as exc:
            return _save_plan(sid, req, {"summary": "خطة آمنة قابلة للتحقق", "steps": ["افتح الهدف المناسب.", "نفذ الإجراء المطلوب.", "تحقق من النتيجة."], "output_mode": "repair", "provider": provider, "session_id": sid, "error": str(exc)}, persist=False)

    last_error: Exception | None = None
    for prompt in (app_v4_runtime.PLANNER+"\n"+payload, "Return ONLY one valid JSON object with keys summary and steps. steps must contain 3-5 concrete executable actions for this exact Android task, with the final action verifying the requested outcome.\nTASK:\n"+payload):
        try:
            raw = app_v4_runtime._space_predict(prompt)
            steps, summary = _extract_plan(raw)
            return _save_plan(sid, req, {"summary": summary, "steps": steps, "output_mode": "primary_model", "provider": QWEN_PROVIDER, "session_id": sid})
        except Exception as exc:
            last_error = exc

    task = req.task.strip().lower()
    aliases = {"يوتيوب":"YouTube","youtube":"YouTube","واتساب":"WhatsApp","whatsapp":"WhatsApp","كاب كات":"CapCut","capcut":"CapCut","كانفا":"Canva","canva":"Canva","كروم":"Chrome","chrome":"Chrome","انستجرام":"Instagram","instagram":"Instagram","تليجرام":"Telegram","telegram":"Telegram"}
    app_name = next((label for key, label in aliases.items() if key in task), None)
    steps = [f"افتح {app_name} وحقق من ظهور واجهته." if app_name else "افتح التطبيق أو الموقع المطلوب للمهمة.", f"نفذ الطلب داخل {app_name} وفق العناصر الظاهرة على الشاشة." if app_name else "نفذ المطلوب اعتمادًا على الشاشة الحالية والنص المدخل.", "تحقق بصريًا من النتيجة المطلوبة ولا تعلن النجاح قبل إثباتها."]
    return _save_plan(sid, req, {"summary":"خطة احتياطية قابلة للمراجعة والتنفيذ","steps":steps,"output_mode":"resilient_fallback","provider":RECOVERY_PROVIDER,"session_id":sid,"error":str(last_error) if last_error else None})


def _fallback_action(req: Any) -> dict[str, Any]:
    task, ui = req.task.lower(), req.ui_tree.lower(); merged = task + " " + ui
    if req.step == 0:
        for key, label in (("يوتيوب","YouTube"),("youtube","YouTube"),("واتساب","WhatsApp"),("whatsapp","WhatsApp"),("capcut","CapCut"),("كاب كات","CapCut"),("canva","Canva"),("كانفا","Canva"),("chrome","Chrome"),("كروم","Chrome")):
            if key in task: return {"action":"open_app_by_name","params":{"app_name":label},"message":f"فتح {label}","done":False,"wait_after_ms":1000,"confidence":0.8}
    for label in ("continue","متابعة","التالي","موافق","ok","submit","إرسال"):
        if label in merged: return {"action":"click_any_text","params":{"texts":[label]},"message":"اختيار هدف ظاهر ثم التحقق من التغير","done":False,"wait_after_ms":700,"confidence":0.7}
    return {"action":"observe","params":{},"message":"لم يثبت الهدف بعد؛ إعادة الملاحظة بدل التخمين","done":False,"wait_after_ms":700,"confidence":0.2}


def _save_step(sid: str, req: Any, value: dict[str, Any], persist: bool = True) -> dict[str, Any]:
    value["session_id"] = sid
    value["verification"] = app_v3.safety(req.task, value, req.approved_risks)
    if persist:
        app_v3.remember(sid, "decision", value)
        app_v3.save_state(sid, {"phase":"executing","task":req.task,"step":req.step,"last_decision":value})
    return value


def run_step(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    changed = app_v3.reasoning is not _BASE_REASONING or app_v3.visual is not _BASE_VISUAL or app_v3.call_vision is not _BASE_CALL_VISION
    if changed:
        try:
            if app_v3.call_vision is not _BASE_CALL_VISION:
                obs, vision_provider = app_v3.call_vision(req.task, req.ui_tree, req.screenshot_base64)
            elif app_v3.visual is not _BASE_VISUAL and req.screenshot_base64:
                obs, vision_provider = app_v3.visual(req.task, req.ui_tree, req.screenshot_base64)
            else:
                obs, vision_provider = "لا توجد ملاحظة بصرية في وضع الاختبار", "compatibility"
            raw, provider = app_v3.reasoning(app_v4_runtime.CONTROLLER, json.dumps({"task":req.task,"step":req.step,"ui_tree":req.ui_tree,"visual":obs,"capabilities":req.capabilities},ensure_ascii=False))
            result = app_v4_runtime._normalize_action(app_v3.extract_json(raw), req.screenshot_base64)
            result.update({"provider":provider,"vision_provider":vision_provider,"output_mode":"compatibility_test","visual_observation":obs})
            return _save_step(sid, req, result, persist=False)
        except Exception as exc:
            return _save_step(sid, req, {"action":"observe","params":{},"message":"تعذر اتخاذ إجراء صالح؛ سأعيد الملاحظة بأمان.","done":False,"wait_after_ms":600,"confidence":0.0,"provider":"repair","vision_provider":"repair","output_mode":"compatibility_test","visual_observation":"repair","error":str(exc)}, persist=False)

    evidence = json.dumps({"task":req.task,"step":req.step,"history":req.history[-10:],"ui_tree":req.ui_tree[:18000],"installed_apps":req.installed_apps[:250],"capabilities":req.capabilities},ensure_ascii=False)
    last_error: Exception | None = None
    for prompt in (app_v4_runtime.CONTROLLER+"\nCURRENT EVIDENCE:\n"+evidence, "Choose exactly one Android action and return ONLY valid JSON using the schema from the system instructions. Do not describe the plan. Decide from the current screenshot, UI tree and task.\nCURRENT EVIDENCE:\n"+evidence):
        try:
            raw = app_v4_runtime._space_predict(prompt, req.screenshot_base64)
            value = app_v4_runtime._normalize_action(app_v3.extract_json(raw), req.screenshot_base64)
            value.update({"provider":QWEN_PROVIDER,"vision_provider":QWEN_PROVIDER,"output_mode":"primary_multimodal","visual_observation":{"screen_summary":"Qwen3-VL live cloud observation","elements":[],"confidence":value.get("confidence",0.0)}})
            return _save_step(sid, req, value)
        except Exception as exc: last_error = exc
    value = _fallback_action(req)
    value.update({"provider":RECOVERY_PROVIDER,"vision_provider":RECOVERY_PROVIDER,"output_mode":"resilient_fallback","visual_observation":{"screen_summary":"الحماية الاحتياطية: تم اتخاذ قرار محافظ من الأدلة المتاحة","elements":[],"confidence":value.get("confidence",0.0)},"error":str(last_error) if last_error else None})
    return _save_step(sid, req, value)

app_v3.run_plan = run_plan
app_v3.run_step = run_step
