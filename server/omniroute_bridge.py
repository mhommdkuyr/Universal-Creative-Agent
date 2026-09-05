"""OmniRoute bridge with bounded deterministic fallback.

OmniRoute is the preferred production brain. If it is unavailable, UCOA does
not call the slow local Render model and does not hang: it falls back to a
fast UI-tree/safe-action controller. The dedicated HF smoke workflow still
proves the Qwen visual path independently.
"""
from __future__ import annotations

import json
import os
import re
import app_v3

BASE = os.getenv("UCOA_OMNIROUTE_BASE_URL", "").rstrip("/")
MODEL = os.getenv("UCOA_OMNIROUTE_MODEL", "auto")
KEY = os.getenv("UCOA_OMNIROUTE_API_KEY", "")
TIMEOUT = int(os.getenv("UCOA_OMNIROUTE_TIMEOUT", "25"))

VISION = """You are UCOA visual perception. Inspect ONLY the current Android screenshot
and UI tree. Return ONLY JSON:
{"screen_summary":string,"elements":[{"text":string,"role":string,"x":number,"y":number}],"visible_goal_state":string,"confidence":number}
Never invent unseen controls."""


def _chat(system: str, user: str, image: str | None = None) -> str:
    if not BASE:
        raise RuntimeError("UCOA_OMNIROUTE_BASE_URL is not configured")
    return app_v3.chat(BASE, KEY, MODEL, system, user, image, TIMEOUT)


def _tree_text(user: str) -> list[str]:
    vals = re.findall(r'"text"\s*:\s*"([^"]+)"|\btext=([\w\s.-]+)', user or "", flags=re.I)
    out=[]
    for a,b in vals:
        x=(a or b).strip()
        if x and x.lower() not in {"null","none"}: out.append(x)
    return out


def _deterministic_reasoning(system: str, user: str):
    texts=_tree_text(user)
    lower={x.lower() for x in texts}
    if "continue" in lower or any("continue" in x for x in lower):
        action={"action":"click_any_text","params":{"texts":["CONTINUE"]},"message":"اضغط الزر الظاهر CONTINUE","done":False,"wait_after_ms":700,"confidence":0.98,"coordinate_space":None,"verification_goal":"اختفاء CONTINUE أو ظهور الحالة التالية"}
    elif any(x in lower for x in ("allow","السماح","موافق","ok","حسنا")):
        label=next(x for x in texts if x.lower() in {"allow","السماح","موافق","ok","حسنا"})
        action={"action":"click_any_text","params":{"texts":[label]},"message":f"اضغط {label}","done":False,"wait_after_ms":700,"confidence":0.95,"coordinate_space":None,"verification_goal":"تغير واجهة الإذن"}
    else:
        action={"action":"observe","params":{},"message":"لا يوجد هدف نصي مؤكد؛ أعد الملاحظة","done":False,"wait_after_ms":500,"confidence":0.2,"coordinate_space":None,"verification_goal":"الحصول على هدف مؤكد"}
    return json.dumps(action, ensure_ascii=False), "deterministic-fallback"


def reasoning(system: str, user: str):
    try:
        return _chat(system, user), "omniroute"
    except Exception:
        return _deterministic_reasoning(system, user)


def visual(task: str, ui_tree: str, image: str | None):
    if image and BASE:
        try:
            raw = _chat(VISION, f"TASK: {task}\nUI_TREE:\n{ui_tree[:14000]}", image)
            return app_v3.extract_json(raw), "omniroute"
        except Exception:
            pass
    texts=[]
    for m in re.finditer(r'"text"\s*:\s*"([^"]+)"', ui_tree or ""):
        if m.group(1).strip(): texts.append(m.group(1).strip())
    return {"screen_summary":"Accessibility tree fallback; visual model unavailable","elements":[{"text":x,"role":"text"} for x in texts[:40]],"visible_goal_state":"unknown","confidence":0.35}, "deterministic-fallback"


def call_vision(task: str, ui_tree: str, image: str | None):
    return visual(task, ui_tree, image)


def install() -> None:
    app_v3.reasoning = reasoning
    app_v3.visual = visual
    app_v3.call_vision = call_vision
