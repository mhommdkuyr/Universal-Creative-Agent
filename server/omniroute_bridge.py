"""OmniRoute bridge for UCOA V4.

Keeps UCOA's stable FastAPI contract while moving production planning, visual
perception and action selection behind OmniRoute's OpenAI-compatible gateway.
"""
from __future__ import annotations

import os
import app_v3

BASE = os.getenv("UCOA_OMNIROUTE_BASE_URL", "").rstrip("/")
MODEL = os.getenv("UCOA_OMNIROUTE_MODEL", "auto")
KEY = os.getenv("UCOA_OMNIROUTE_API_KEY", "")
TIMEOUT = int(os.getenv("UCOA_OMNIROUTE_TIMEOUT", "120"))

VISION = """You are UCOA visual perception. Inspect ONLY the current Android screenshot
and UI tree. Return ONLY JSON:
{"screen_summary":string,"elements":[{"text":string,"role":string,"x":number,"y":number}],"visible_goal_state":string,"confidence":number}
Never invent unseen controls."""


def _chat(system: str, user: str, image: str | None = None) -> str:
    if not BASE:
        raise RuntimeError("UCOA_OMNIROUTE_BASE_URL is not configured")
    return app_v3.chat(BASE, KEY, MODEL, system, user, image, TIMEOUT)


def reasoning(system: str, user: str):
    return _chat(system, user), "omniroute"


def visual(task: str, ui_tree: str, image: str | None):
    if not image:
        return {"screen_summary":"no screenshot","elements":[],"visible_goal_state":"unknown","confidence":0.0}, "omniroute"
    raw = _chat(VISION, f"TASK: {task}\nUI_TREE:\n{ui_tree[:14000]}", image)
    try:
        return app_v3.extract_json(raw), "omniroute"
    except Exception:
        return {"screen_summary": raw[:1200], "elements": [], "visible_goal_state":"unknown", "confidence":0.2}, "omniroute"


def call_vision(task: str, ui_tree: str, image: str | None):
    return visual(task, ui_tree, image)


def install() -> None:
    if BASE:
        app_v3.reasoning = reasoning
        app_v3.visual = visual
        app_v3.call_vision = call_vision
