"""UCOA V4 model router with OmniRoute and external provider fallbacks."""
from __future__ import annotations
import json
import os
import re
import time
from typing import Any
import app_v3

OMNI_BASE = os.getenv("UCOA_OMNIROUTE_BASE_URL", "").rstrip("/")
OMNI_MODEL = os.getenv("UCOA_OMNIROUTE_MODEL", "auto")
OMNI_KEY = os.getenv("UCOA_OMNIROUTE_API_KEY", "")
TIMEOUT = int(os.getenv("UCOA_OMNIROUTE_TIMEOUT", "12"))

PROVIDERS = [
    {"name":"gemini","env":"UCOA_GEMINI_API_KEY","base":"https://generativelanguage.googleapis.com/v1beta/openai/","model":os.getenv("UCOA_GEMINI_MODEL","gemini-3.8-flash"),"vision":True},
    {"name":"deepseek","env":"UCOA_DEEPSEEK_API_KEY","base":"https://api.deepseek.com","model":os.getenv("UCOA_DEEPSEEK_MODEL","deepseek-v4-flash-vision-exp"),"vision":True},
    {"name":"cerebras","env":"UCOA_CEREBRAS_API_KEY","base":"https://api.cerebras.ai/v1","model":os.getenv("UCOA_CEREBRAS_MODEL","gpt-oss-120b"),"vision":False},
    {"name":"groq","env":"UCOA_GROQ_API_KEY","base":"https://api.groq.com/openai/v1","model":os.getenv("UCOA_GROQ_MODEL","openai/gpt-oss-120b"),"vision":False},
]

def _chat(base: str, key: str, model: str, system: str, user: str, image: str | None = None, timeout: int | None = None) -> str:
    return app_v3.chat(base, key, model, system, user, image, timeout or TIMEOUT)

def _fallback(prompt: str) -> str:
    texts=[]
    for m in re.finditer(r'"text"\s*:\s*"([^"]+)"', prompt or ""):
        v=m.group(1).strip()
        if v: texts.append(v)
    low={x.lower() for x in texts}
    if any("continue" in x for x in low):
        return json.dumps({"action":"click_any_text","params":{"texts":["CONTINUE"]},"message":"اضغط CONTINUE ثم تحقق","done":False,"wait_after_ms":700,"confidence":0.98,"coordinate_space":None,"verification_goal":"اختفاء CONTINUE أو ظهور الحالة التالية"},ensure_ascii=False)
    for x in texts:
        if x.lower() in {"allow","السماح","موافق","ok","حسنا","التالي","متابعة"}:
            return json.dumps({"action":"click_any_text","params":{"texts":[x]},"message":f"اضغط {x} ثم تحقق","done":False,"wait_after_ms":700,"confidence":0.95,"coordinate_space":None,"verification_goal":"تغير الواجهة"},ensure_ascii=False)
    return json.dumps({"action":"observe","params":{},"message":"لا يوجد هدف مؤكد؛ أعد الملاحظة","done":False,"wait_after_ms":500,"confidence":0.2,"coordinate_space":None,"verification_goal":"الحصول على هدف مؤكد"},ensure_ascii=False)

def _provider(name: str):
    if name == "omniroute":
        return OMNI_BASE, OMNI_KEY, OMNI_MODEL, True
    p=next((x for x in PROVIDERS if x["name"]==name),None)
    if not p: raise RuntimeError("unknown provider")
    key=os.getenv(p["env"],"").strip()
    if not key: raise RuntimeError("provider not configured")
    return p["base"],key,p["model"],bool(p["vision"])

def _ordered(image: str | None):
    names=[]
    if OMNI_BASE: names.append("omniroute")
    configured=[p["name"] for p in PROVIDERS if os.getenv(p["env"],"").strip()]
    if image:
        names += [n for n in configured if next(p for p in PROVIDERS if p["name"]==n)["vision"]]
        names += [n for n in configured if not next(p for p in PROVIDERS if p["name"]==n)["vision"]]
    else:
        # Cerebras/Groq are optimized for fast reasoning; keep multimodal providers available as fallbacks.
        names += [n for n in ("cerebras","groq","gemini","deepseek") if n in configured]
    return list(dict.fromkeys(names))

def _call(name, system, user, image, timeout=TIMEOUT):
    base,key,model,vision=_provider(name)
    return _chat(base,key,model,system,user,image if vision else None,timeout)

def model_predict(prompt: str, image: str | None = None):
    system="You are UCOA, a real Android GUI agent. Return ONLY valid JSON in the requested action schema. Never claim success without evidence. Never invent unseen controls."
    for name in _ordered(image):
        try:
            raw=_call(name,system,prompt,image,TIMEOUT)
            if raw and raw.strip(): return raw,name
        except Exception:
            continue
    return _fallback(prompt),"deterministic-fallback"

def probe() -> dict[str,Any]:
    """Run a minimal live request against every configured provider without exposing secrets."""
    system="Return only JSON."
    prompt='Return exactly {"action":"observe","done":false,"confidence":1.0}'
    results=[]
    for name in _ordered(None):
        started=time.perf_counter()
        try:
            raw=_call(name,system,prompt,None,min(TIMEOUT,8))
            results.append({"provider":name,"ok":bool(raw and raw.strip()),"latency_s":round(time.perf_counter()-started,3)})
        except Exception as exc:
            results.append({"provider":name,"ok":False,"latency_s":round(time.perf_counter()-started,3),"error":type(exc).__name__})
    ok=[r for r in results if r["ok"]]
    return {"ok":bool(ok),"best":min(ok,key=lambda r:r["latency_s"],default=None),"providers":results}

def install() -> None:
    import app_v4_runtime
    app_v4_runtime._model_predict = model_predict
