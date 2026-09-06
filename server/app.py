"""Production entrypoint for UCOA V4 with live provider routing."""
import base64
import io
import sys

import app_v4_runtime  # noqa: F401,E402
import app_v3
import openai_provider
import provider_router
from observability import init_sentry
from PIL import Image, ImageDraw

init_sentry()

OPENAI_PRIMARY = os.getenv("UCOA_OPENAI_PRIMARY", "true").lower() == "true"


def _provider_reasoning(system, user):
    if OPENAI_PRIMARY and openai_provider.configured():
        try:
            return openai_provider.reasoning(system, user), "openai"
        except Exception:
            pass
    return provider_router.reasoning(system, user)


def _provider_visual(task, ui_tree, image):
    if OPENAI_PRIMARY and openai_provider.configured():
        try:
            system = (
                "You are UCOA visual perception. Inspect only the current Android screenshot and UI tree. "
                "Return ONLY valid JSON: {\"screen_summary\":string,\"elements\":[{\"text\":string,\"role\":string,\"x\":number,\"y\":number}],\"visible_goal_state\":string,\"confidence\":number}. "
                "Never invent unseen elements. Coordinates must be normalized to 0..1000."
            )
            user = __import__("json").dumps({"task": task, "ui_tree": ui_tree[:18000]}, ensure_ascii=False)
            raw = openai_provider.visual(system, user, image)
            return app_v3.extract_json(raw), "openai"
        except Exception:
            pass
    return provider_router.visual(task, ui_tree, image)


# Import V4 before patching so its legacy references remain stable. Patch only
# the normal reasoning/visual hooks; keep call_vision untouched so existing
# tests and downstream integrations can override it safely.
app_v3.reasoning = _provider_reasoning
app_v3.visual = _provider_visual


@app_v3.app.get("/v1/providers/probe")
def providers_probe():
    result = provider_router.safe_text_probe()
    if OPENAI_PRIMARY and openai_provider.configured():
        try:
            openai_provider.reasoning("Return ONLY JSON.", "Return exactly {\"ok\":true}.")
            result["openai"] = {"ok": True, "model": openai_provider.MODEL}
            result["ok"] = True
        except Exception as exc:
            result["openai"] = {"ok": False, "model": openai_provider.MODEL, "error": type(exc).__name__}
    return result


@app_v3.app.get("/v1/providers/probe-vision")
def providers_probe_vision():
    """Live multimodal probe using a synthetic Android-like screen."""
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 640, 64), fill="black")
    draw.text((24, 20), "UCOA Vision Test", fill="white")
    draw.rounded_rectangle((220, 150, 420, 215), radius=12, fill="#dddddd", outline="black")
    draw.text((295, 172), "CONTINUE", fill="black")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    task = "Find the visible primary button in this Android-like screen. Return JSON only."
    tree = '[{"text":"CONTINUE","role":"button"}]'
    try:
        result, provider = _provider_visual(task, tree, encoded)
        labels = [str(e.get("text", "")) for e in result.get("elements", []) if isinstance(e, dict)] if isinstance(result, dict) else []
        found = any("continue" in x.lower() for x in labels) or "continue" in str(result).lower()
        return {"ok": bool(found), "provider": provider, "detected_target": "CONTINUE" if found else None, "confidence": result.get("confidence") if isinstance(result, dict) else None}
    except Exception as exc:
        return {"ok": False, "provider": None, "error": type(exc).__name__}


sys.modules[__name__] = app_v3
