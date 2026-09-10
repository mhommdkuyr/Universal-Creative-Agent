from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import app_v3
import provider_router

# Keep the development profile on a currently supported Gemini family model.
for _p in provider_router.PROVIDERS:
    if _p["name"] in {"gemini", "gemini-2"}:
        _p["default_model"] = os.getenv(_p["model_env"], "gemini-2.5-flash")

PLANNER_SYSTEM = """
أنت مخطط المهام في وكيل عملي يعمل على هاتف أندرويد حقيقي.
أعد كائنًا واحدًا بصيغة JSON فقط بهذا الشكل:
{"summary":"...","steps":["...","..."]}
أنشئ من خطوتين إلى ست خطوات قابلة للتنفيذ، واجعل آخر خطوة تتضمن تحققًا قابلًا للملاحظة.
لا تدّعِ نجاح أي خطوة قبل أن يثبته الجهاز.
""".strip()

CONTROLLER_SYSTEM = """
أنت المتحكم التنفيذي لوكيل عملي يعمل على هاتف أندرويد حقيقي.
الصورة المرفقة هي شاشة الهاتف الحالية، وشجرة الواجهة وقائمة التطبيقات أدلة إضافية.
أعد إجراءً واحدًا فقط بصيغة JSON، ولا تكتب أي شرح خارج JSON:
{"action":"open_url|open_app_by_name|click_any_text|type_into_any|share_attachment|tap|long_press|swipe|back|home|wait|observe|done","params":{},"message":"...","done":false,"wait_after_ms":500,"confidence":0.0,"coordinate_space":"normalized_1000|null","verification_goal":"..."}
لا تخترع عناصر غير ظاهرة. استخدم النقر على النص الظاهر عندما يكون ذلك ممكنًا.
استخدم إحداثيات مطبّعة من صفر إلى ألف عند اللمس.
إذا ظهرت نافذة مؤقتة أو إعلان قابل للتخطي فانتظر أو نفذ التخطي بدل إعلان فشل المهمة.
لا تستخدم done إلا عندما تكون حالة الهدف النهائية مثبتة بصريًا.
""".strip()


def _screen_size(image: str | None) -> tuple[int, int]:
    if not image:
        return 0, 0
    try:
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(base64.b64decode(image))) as im:
            return im.size
    except Exception:
        return 0, 0


def _normalize_action(value: dict[str, Any], image: str | None) -> dict[str, Any]:
    action = str(value.get("action", "observe"))
    if action not in app_v3.ACTIONS:
        raise ValueError("unsupported action")
    params = value.get("params") if isinstance(value.get("params"), dict) else {}
    result = dict(value)
    result["action"] = action
    result["params"] = params
    result["message"] = str(value.get("message", ""))
    result["done"] = bool(value.get("done", False)) or action == "done"
    result["wait_after_ms"] = max(150, min(5000, int(value.get("wait_after_ms", 500))))
    result["confidence"] = max(0.0, min(1.0, float(value.get("confidence", 0.0))))
    result["coordinate_space"] = value.get("coordinate_space")
    result["verification_goal"] = str(value.get("verification_goal", "تحقق من تغير الحالة"))
    if result["coordinate_space"] == "normalized_1000" and image:
        w, h = _screen_size(image)
        if w and h and action in {"tap", "long_press", "swipe"}:
            scales = {"x": w, "x1": w, "x2": w, "y": h, "y1": h, "y2": h}
            for key, scale in scales.items():
                if key in params:
                    params[key] = round(float(params[key]) * scale / 1000.0, 1)
            result["coordinate_space"] = "pixel"
    return result


def _call(system: str, payload: dict[str, Any], image: str | None = None) -> tuple[str, str]:
    return provider_router.call(system, json.dumps(payload, ensure_ascii=False), image)


def run_plan(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    payload = {
        "task": req.task,
        "attachments": req.attachments[:8],
        "device": req.device,
        "memory": app_v3.memory(sid, 12),
    }
    errors: list[str] = []
    try:
        raw, provider = _call(PLANNER_SYSTEM, payload)
        plan = app_v3.extract_json(raw)
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        if len(steps) < 2:
            raise ValueError("invalid plan")
        result = {
            "summary": str(plan.get("summary", "خطة قابلة للتحقق")),
            "steps": [str(x) for x in steps[:6]],
            "output_mode": "cloud_router",
            "provider": provider,
            "session_id": sid,
        }
    except Exception as exc:
        errors.append(str(exc))
        result = {
            "summary": "خطة قابلة للتحقق",
            "steps": ["افتح التطبيق الهدف.", "نفذ الإجراء المطلوب.", "تحقق من النتيجة."],
            "output_mode": "repair",
            "provider": "repair",
            "session_id": sid,
            "error": "; ".join(errors),
        }
    app_v3.remember(sid, "plan", result)
    app_v3.save_state(sid, {"phase": "planned", "task": req.task, "step": 0, "plan": result})
    return result


def run_step(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    payload = {
        "task": req.task,
        "step": req.step,
        "history": req.history[-10:],
        "ui_tree": req.ui_tree[:18000],
        "installed_apps": req.installed_apps[:250],
        "capabilities": req.capabilities,
        "approved_risks": req.approved_risks,
    }
    errors: list[str] = []
    provider = "repair"
    try:
        raw, provider = _call(CONTROLLER_SYSTEM, payload, req.screenshot_base64)
        result = _normalize_action(app_v3.extract_json(raw), req.screenshot_base64)
        result["output_mode"] = "cloud_router_multimodal"
    except Exception as exc:
        errors.append(str(exc))
        # Safe local fallback: do not guess a coordinate.
        result = app_v3.fallback_step(req, {"screen_summary": "cloud providers unavailable", "elements": []})
        result["confidence"] = min(float(result.get("confidence", 0.0)), 0.25)
        result["output_mode"] = "repair"
        result["error"] = "; ".join(errors)
    result["provider"] = provider
    result["vision_provider"] = provider
    result["session_id"] = sid
    result["visual_observation"] = {
        "screen_summary": "تمت معالجة الشاشة ضمن الاستدعاء السحابي متعدد الوسائط.",
        "elements": [],
        "confidence": result.get("confidence", 0.0),
    }
    result["verification"] = app_v3.safety(req.task, result, req.approved_risks)
    app_v3.remember(sid, "decision", result)
    app_v3.save_state(sid, {"phase": "executing", "task": req.task, "step": req.step, "last_decision": result})
    return result


def verify_result(req: Any) -> dict[str, Any]:
    return app_v3.independent_verify(req.task, req.action, req.before_ui_tree, req.after_ui_tree)


app_v3.run_plan = run_plan
app_v3.run_step = run_step
app_v3.verify_result = verify_result
