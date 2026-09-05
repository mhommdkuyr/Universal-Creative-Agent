"""OmniRoute model adapter for UCOA V4.

The adapter patches only V4's model boundary. It does not monkeypatch
app_v3.reasoning/visual, so legacy unit-test hooks and safety tests remain
isolated and cannot recurse.
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


def _chat(system: str, user: str, image: str | None = None) -> str:
    if not BASE:
        raise RuntimeError("UCOA_OMNIROUTE_BASE_URL is not configured")
    return app_v3.chat(BASE, KEY, MODEL, system, user, image, TIMEOUT)


def _fallback(prompt: str) -> str:
    texts=[]
    for m in re.finditer(r'"text"\s*:\s*"([^"]+)"', prompt or ""):
        if m.group(1).strip(): texts.append(m.group(1).strip())
    low={x.lower() for x in texts}
    if any("continue" in x for x in low):
        return json.dumps({"action":"click_any_text","params":{"texts":["CONTINUE"]},"message":"اضغط CONTINUE","done":False,"wait_after_ms":700,"confidence":0.98,"coordinate_space":None,"verification_goal":"اختفاء CONTINUE أو ظهور الحالة التالية"},ensure_ascii=False)
    if any(x in low for x in {"allow","السماح","موافق","ok","حسنا"}):
        label=next(x for x in texts if x.lower() in {"allow","السماح","موافق","ok","حسنا"})
        return json.dumps({"action":"click_any_text","params":{"texts":[label]},"message":f"اضغط {label}","done":False,"wait_after_ms":700,"confidence":0.95,"coordinate_space":None,"verification_goal":"تغير واجهة الإذن"},ensure_ascii=False)
    return json.dumps({"action":"observe","params":{},"message":"لا يوجد هدف مؤكد؛ أعد الملاحظة","done":False,"wait_after_ms":500,"confidence":0.2,"coordinate_space":None,"verification_goal":"الحصول على هدف مؤكد"},ensure_ascii=False)


def model_predict(prompt: str, image: str | None = None):
    try:
        return _chat("You are UCOA, a multimodal Android agent. Return ONLY valid JSON. Never claim success without evidence.", prompt, image), "omniroute"
    except Exception:
        return _fallback(prompt), "deterministic-fallback"


def install() -> None:
    import app_v4_runtime
    app_v4_runtime._model_predict = model_predict
