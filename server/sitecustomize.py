"""Runtime compatibility patches loaded automatically by Python site init.

Keeps the installed Android client compatible with the V4 backend while making
cloud-provider routing resilient when a primary provider is unavailable or over quota.
"""
from __future__ import annotations

import os
import threading
from fastapi import Header, HTTPException

_PATCHED = False


def _external_provider_configured() -> bool:
    envs = (
        "UCOA_GEMINI_API_KEY",
        "GEMINI_API_KEY",
        "UCOA_GEMINI_API_KEY_2",
        "GEMINI_API_KEY_2",
        "HF_TOKEN",
        "UCOA_DEEPSEEK_API_KEY",
        "UCOA_CEREBRAS_API_KEY",
        "UCOA_GROQ_API_KEY",
        "UCOA_OMNIROUTE_API_KEY",
    )
    return any(os.getenv(name, "").strip() for name in envs)


def _patch_health(app_v3) -> None:
    external = _external_provider_configured()
    if not external:
        return
    for route in app_v3.app.routes:
        if getattr(route, "path", "") != "/health":
            continue
        if "GET" not in (getattr(route, "methods", set()) or set()):
            continue
        original = route.endpoint
        if getattr(original, "__ucoa_router_health_patch__", False):
            return

        def health_compat(*args, **kwargs):
            data = dict(original(*args, **kwargs))
            data["brain_configured"] = True
            data["routing"] = True
            data["reasoning_provider"] = "provider-router"
            return data

        health_compat.__ucoa_router_health_patch__ = True
        route.endpoint = health_compat
        if hasattr(route, "dependant"):
            route.dependant.call = health_compat
        return


def _patch_android_routes(app_v3) -> None:
    paths = {getattr(route, "path", "") for route in app_v3.app.routes}
    if "/v1/agent/step" not in paths:
        @app_v3.app.post("/v1/agent/step")
        def android_step(req: app_v3.StepRequest, authorization: str | None = Header(default=None)):
            app_v3.auth(authorization)
            runner = getattr(app_v3, "run_step", None)
            if not callable(runner):
                raise HTTPException(503, "step runtime not initialized")
            return app_v3.submit("step", lambda: runner(req))

    if "/v1/agent/jobs/{jid}" not in paths:
        @app_v3.app.get("/v1/agent/jobs/{jid}")
        def android_job(jid: str, authorization: str | None = Header(default=None)):
            app_v3.auth(authorization)
            with app_v3.JOB_LOCK:
                job = dict(app_v3.JOBS.get(jid, {}))
            if not job:
                raise HTTPException(404, "job not found")
            return job


def _patch_safety(app_v3) -> None:
    sensitive = getattr(app_v3, "SENSITIVE", None)
    if isinstance(sensitive, list):
        for phrase in ("send code", "ارسال الرمز", "إرسال الرمز"):
            if phrase not in sensitive:
                sensitive.append(phrase)


def _qwen_space_call(prompt: str, image: str | None = None):
    import app_v4_runtime
    raw = app_v4_runtime._space_predict(prompt, image)
    return raw, "huggingface-qwen3-vl-235b"


def _patch_provider_router(app_v3) -> None:
    import provider_router

    if not getattr(provider_router.reasoning, "__ucoa_qwen_fallback__", False):
        original_reasoning = provider_router.reasoning

        def reasoning_with_qwen(system, user):
            try:
                return original_reasoning(system, user)
            except Exception as primary_error:
                try:
                    return _qwen_space_call(system + "\n" + user, None)
                except Exception:
                    raise primary_error

        reasoning_with_qwen.__ucoa_qwen_fallback__ = True
        provider_router.reasoning = reasoning_with_qwen

    if not getattr(provider_router.visual, "__ucoa_qwen_fallback__", False):
        original_visual = provider_router.visual

        def visual_with_qwen(task, ui_tree, image):
            try:
                return original_visual(task, ui_tree, image)
            except Exception as primary_error:
                try:
                    import json
                    system = (
                        "You are UCOA visual perception. Inspect only the current Android screenshot and UI tree. "
                        "Return ONLY valid JSON: {\"screen_summary\":string,\"elements\":[{\"text\":string,\"role\":string,\"x\":number,\"y\":number}],\"visible_goal_state\":string,\"confidence\":number}. "
                        "Never invent unseen elements. Coordinates normalized 0..1000."
                    )
                    user = json.dumps({"task": task, "ui_tree": ui_tree[:18000]}, ensure_ascii=False)
                    raw, provider = _qwen_space_call(system + "\n" + user, image)
                    return app_v3.extract_json(raw), provider
                except Exception:
                    raise primary_error

        visual_with_qwen.__ucoa_qwen_fallback__ = True
        provider_router.visual = visual_with_qwen

    if not getattr(provider_router.safe_text_probe, "__ucoa_qwen_fallback__", False):
        original_probe = provider_router.safe_text_probe

        def safe_text_probe_with_qwen():
            try:
                result = original_probe()
                if result.get("ok") or result.get("response"):
                    return result
            except Exception:
                pass
            try:
                raw, provider = _qwen_space_call(
                    'Return ONLY valid JSON: {"ok":true}. Return exactly {"ok":true}.',
                    None,
                )
                return {
                    "ok": True,
                    "configured": True,
                    "providers": [{"provider": provider, "model": "Qwen/Qwen3-VL-235B-A22B-Instruct", "ok": True, "vision": True}],
                    "runtime": {"ok": True, "provider": provider},
                    "response": app_v3.extract_json(raw),
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "configured": _external_provider_configured(),
                    "providers": [],
                    "error": type(exc).__name__,
                    "runtime": {"ok": False, "error": type(exc).__name__},
                }

        safe_text_probe_with_qwen.__ucoa_qwen_fallback__ = True
        provider_router.safe_text_probe = safe_text_probe_with_qwen


def _patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    try:
        import app_v3
        _patch_android_routes(app_v3)
        _patch_safety(app_v3)
        _patch_health(app_v3)
        _patch_provider_router(app_v3)
        _PATCHED = True
    except Exception:
        return


_patch()
