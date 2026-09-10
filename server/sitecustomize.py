"""Runtime health compatibility patch loaded automatically by Python's site init.

The Android client treats /health.brain_configured as readiness. UCOA V4 can
serve through the cloud provider router even when the legacy LOCAL_BASE is empty,
so expose that actual readiness without changing the client or requiring an APK update.
"""
from __future__ import annotations

import os


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


def _patch_health() -> None:
    try:
        import app_v3

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
    except Exception:
        return


_patch_health()
