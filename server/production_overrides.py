"""Production-safe overrides for planning and Android control.

This module is imported after app_v3/app_v4_runtime are initialized so the
FastAPI handlers call these functions directly instead of falling through to
legacy provider routing.
"""
from __future__ import annotations

import json
import re
from typing import Any

import app_v3
import app_v4_runtime

QWEN_PROVIDER = "huggingface-qwen3-vl-235b"
RECOVERY_PROVIDER = "ucoa-resilient-fallback"


def _extract_plan(raw: str) -> tuple[list[str], str]:
    value = app_v3.extract_json(raw)
    steps = value.get("steps") if isinstance(value.get("steps"), list) else []
    steps = [str(x).strip() for x in steps if str(x).strip()]
    if len(steps) < 2:
        raise ValueError("planner returned fewer than two executable steps")
    summary = str(value.get("summary") or "خطة قابلة للتحقق")
    return steps[:6], summary


def run_plan(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    payload = json.dumps(
        {
            "task": req.task,
            "attachments": req.attachments[:8],
            "device": req.device,
            "memory": app_v3.memory(sid, 12),
        },
        ensure_ascii=False,
    )
    last_error: Exception | None = None
    prompts = [
        app_v4_runtime.PLANNER + "\n" + payload,
        (
            "Return ONLY one valid JSON object with keys summary and steps. "
            "steps must contain 3-5 concrete executable actions for this exact Android task, "
            "with the final action verifying the requested outcome.\nTASK:\n" + payload
        ),
    ]
    for prompt in prompts:
        try:
            raw = app_v4_runtime._space_predict(prompt)
            steps, summary = _extract_plan(raw)
            result = {
                "summary": summary,
                "steps": steps,
                "output_mode": "primary_model",
                "provider": QWEN_PROVIDER,
                "session_id": sid,
            }
            app_v3.remember(sid, "plan", result)
            app_v3.save_state(sid, {"phase": "planned", "task": req.task, "step": 0, "plan": result})
            return result
        except Exception as exc:
            last_error = exc

    # Deterministic safety-net: never return provider=repair just because a
    # transient cloud response was malformed. Keep enough structure for the
    # Android UI to present a real plan and require human approval.
    task = req.task.strip()
    app_name = None
    aliases = {
        "يوتيوب": "YouTube", "youtube": "YouTube", "واتساب": "WhatsApp",
        "whatsapp": "WhatsApp", "كاب كات": "CapCut", "capcut": "CapCut",
        "كانفا": "Canva", "canva": "Canva", "كروم": "Chrome", "chrome": "Chrome",
        "انستجرام": "Instagram", "instagram": "Instagram", "تليجرام": "Telegram",
        "telegram": "Telegram",
    }
    lowered = task.lower()
    for key, label in aliases.items():
        if key in lowered:
            app_name = label
            break
    steps = [
        f"افتح {app_name} وحقق من ظهور واجهته." if app_name else "افتح التطبيق أو الموقع المطلوب للمهمة.",
        f"نفذ الطلب داخل {app_name} وفق العناصر الظاهرة على الشاشة." if app_name else "نفذ المطلوب اعتمادًا على الشاشة الحالية والنص المدخل.",
        "تحقق بصريًا من النتيجة المطلوبة ولا تعلن النجاح قبل إثباتها.",
    ]
    result = {
        "summary": "خطة احتياطية قابلة للمراجعة والتنفيذ",
        "steps": steps,
        "output_mode": "resilient_fallback",
        "provider": RECOVERY_PROVIDER,
        "session_id": sid,
        "error": str(last_error) if last_error else None,
    }
    app_v3.remember(sid, "plan", result)
    app_v3.save_state(sid, {"phase": "planned", "task": req.task, "step": 0, "plan": result})
    return result


def _fallback_action(req: Any) -> dict[str, Any]:
    task = req.task.lower()
    ui = req.ui_tree.lower()
    merged = task + " " + ui
    if req.step == 0:
        for key, label in (
            ("يوتيوب", "YouTube"), ("youtube", "YouTube"), ("واتساب", "WhatsApp"),
            ("whatsapp", "WhatsApp"), ("capcut", "CapCut"), ("كاب كات", "CapCut"),
            ("canva", "Canva"), ("كانفا", "Canva"), ("chrome", "Chrome"),
            ("كروم", "Chrome"),
        ):
            if key in task:
                return {
                    "action": "open_app_by_name",
                    "params": {"app_name": label},
                    "message": f"فتح {label}",
                    "done": False,
                    "wait_after_ms": 1000,
                    "confidence": 0.8,
                }
    for label in ("continue", "متابعة", "التالي", "موافق", "ok", "submit", "إرسال"):
        if label in merged:
            return {
                "action": "click_any_text",
                "params": {"texts": [label]},
                "message": "اختيار هدف ظاهر ثم التحقق من التغير",
                "done": False,
                "wait_after_ms": 700,
                "confidence": 0.7,
            }
    return {
        "action": "observe",
        "params": {},
        "message": "لم يثبت الهدف بعد؛ إعادة الملاحظة بدل التخمين",
        "done": False,
        "wait_after_ms": 700,
        "confidence": 0.2,
    }


def run_step(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    evidence = json.dumps(
        {
            "task": req.task,
            "step": req.step,
            "history": req.history[-10:],
            "ui_tree": req.ui_tree[:18000],
            "installed_apps": req.installed_apps[:250],
            "capabilities": req.capabilities,
        },
        ensure_ascii=False,
    )
    last_error: Exception | None = None
    prompts = [
        app_v4_runtime.CONTROLLER + "\nCURRENT EVIDENCE:\n" + evidence,
        (
            "Choose exactly one Android action and return ONLY valid JSON using the schema from the "
            "system instructions. Do not describe the plan. Decide from the current screenshot, UI "
            "tree and task.\nCURRENT EVIDENCE:\n" + evidence
        ),
    ]
    for prompt in prompts:
        try:
            raw = app_v4_runtime._space_predict(prompt, req.screenshot_base64)
            value = app_v3.extract_json(raw)
            value = app_v4_runtime._normalize_action(value, req.screenshot_base64)
            value.update(
                {
                    "provider": QWEN_PROVIDER,
                    "vision_provider": QWEN_PROVIDER,
                    "output_mode": "primary_multimodal",
                    "visual_observation": {
                        "screen_summary": "Qwen3-VL live cloud observation",
                        "elements": [],
                        "confidence": value.get("confidence", 0.0),
                    },
                    "session_id": sid,
                }
            )
            value["verification"] = app_v3.safety(req.task, value, req.approved_risks)
            app_v3.remember(sid, "decision", value)
            app_v3.save_state(sid, {"phase": "executing", "task": req.task, "step": req.step, "last_decision": value})
            return value
        except Exception as exc:
            last_error = exc

    value = _fallback_action(req)
    value.update(
        {
            "provider": RECOVERY_PROVIDER,
            "vision_provider": RECOVERY_PROVIDER,
            "output_mode": "resilient_fallback",
            "visual_observation": {
                "screen_summary": "الحماية الاحتياطية: تم اتخاذ قرار محافظ من الأدلة المتاحة",
                "elements": [],
                "confidence": value.get("confidence", 0.0),
            },
            "session_id": sid,
            "error": str(last_error) if last_error else None,
        }
    )
    value["verification"] = app_v3.safety(req.task, value, req.approved_risks)
    app_v3.remember(sid, "decision", value)
    app_v3.save_state(sid, {"phase": "executing", "task": req.task, "step": req.step, "last_decision": value})
    return value


app_v3.run_plan = run_plan
app_v3.run_step = run_step
