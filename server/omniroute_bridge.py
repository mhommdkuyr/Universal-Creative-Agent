"""OmniRoute bridge with bounded fallback to the proven UCOA vision/reasoning path."""
from __future__ import annotations

import os
import app_v3

BASE = os.getenv("UCOA_OMNIROUTE_BASE_URL", "").rstrip("/")
MODEL = os.getenv("UCOA_OMNIROUTE_MODEL", "auto")
KEY = os.getenv("UCOA_OMNIROUTE_API_KEY", "")
TIMEOUT = int(os.getenv("UCOA_OMNIROUTE_TIMEOUT", "25"))

_ORIGINAL_REASONING = app_v3.reasoning
_ORIGINAL_VISUAL = app_v3.visual
_ORIGINAL_CALL_VISION = app_v3.call_vision

VISION = """You are UCOA visual perception. Inspect ONLY the current Android screenshot
and UI tree. Return ONLY JSON:
{"screen_summary":string,"elements":[{"text":string,"role":string,"x":number,"y":number}],"visible_goal_state":string,"confidence":number}
Never invent unseen controls."""


def _chat(system: str, user: str, image: str | None = None) -> str:
    if not BASE:
        raise RuntimeError("UCOA_OMNIROUTE_BASE_URL is not configured")
    return app_v3.chat(BASE, KEY, MODEL, system, user, image, TIMEOUT)


def reasoning(system: str, user: str):
    try:
        return _chat(system, user), "omniroute"
    except Exception:
        return _ORIGINAL_REASONING(system, user)[0], "fallback"


def visual(task: str, ui_tree: str, image: str | None):
    if not image:
        return _ORIGINAL_VISUAL(task, ui_tree, image)[0], "fallback"
    try:
        raw = _chat(VISION, f"TASK: {task}\nUI_TREE:\n{ui_tree[:14000]}", image)
        return app_v3.extract_json(raw), "omniroute"
    except Exception:
        obs, provider = _ORIGINAL_CALL_VISION(task, ui_tree, image)
        return obs, f"{provider}-fallback"


def call_vision(task: str, ui_tree: str, image: str | None):
    return visual(task, ui_tree, image)


def install() -> None:
    if BASE:
        app_v3.reasoning = reasoning
        app_v3.visual = visual
        app_v3.call_vision = call_vision
