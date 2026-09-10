"""Production cloud-provider router for UCOA.

Gemini uses the native Gemini REST API. Other providers retain an OpenAI-compatible
fallback. The router provides credential detection, failover, circuit breaking and
short-lived visual caching so a transient model outage does not stop a task.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from observability import set_measurement, span

CONNECT_TIMEOUT = float(os.getenv("UCOA_PROVIDER_CONNECT_TIMEOUT", "8"))
TEXT_TIMEOUT = float(os.getenv("UCOA_PROVIDER_TEXT_TIMEOUT", "45"))
VISION_TIMEOUT = float(os.getenv("UCOA_PROVIDER_VISION_TIMEOUT", "60"))
MAX_TOKENS = int(os.getenv("UCOA_PROVIDER_MAX_TOKENS", "512"))
CACHE_TTL = max(0.0, float(os.getenv("UCOA_VISION_CACHE_TTL", "3")))
CB_FAILURES = max(1, int(os.getenv("UCOA_PROVIDER_CB_FAILURES", "3")))
CB_COOLDOWN = max(1.0, float(os.getenv("UCOA_PROVIDER_CB_COOLDOWN", "30")))
VISION_SPACE = os.getenv("UCOA_VISION_SPACE_URL", "https://akhaliq-qwen3-vl-2b-instruct.hf.space").rstrip("/")

PROVIDERS = [
    {"name":"gemini","key_envs":["UCOA_GEMINI_API_KEY","GEMINI_API_KEY"],"base_env":"UCOA_GEMINI_BASE_URL","model_env":"UCOA_GEMINI_MODEL","default_base":"https://generativelanguage.googleapis.com/v1beta","default_model":"gemini-3.8-flash","vision":True,"native_gemini":True},
    {"name":"gemini-2","key_envs":["UCOA_GEMINI_API_KEY_2","GEMINI_API_KEY_2"],"base_env":"UCOA_GEMINI_BASE_URL_2","model_env":"UCOA_GEMINI_MODEL_2","default_base":"https://generativelanguage.googleapis.com/v1beta","default_model":"gemini-3.7-flash","vision":True,"native_gemini":True},
    {"name":"huggingface-text","key_envs":["HF_TOKEN"],"base_env":"HF_BASE_URL","model_env":"HF_MODEL","default_base":"https://router.huggingface.co/v1","default_model":"Qwen/Qwen3-4B-Instruct-2507:fastest","vision":False},
    {"name":"huggingface-vision","key_envs":["HF_TOKEN"],"base_env":"HF_BASE_URL","model_env":"HF_VISION_MODEL","default_base":"https://router.huggingface.co/v1","default_model":"Qwen/Qwen3-VL-2B-Instruct:fastest","vision":True},
    {"name":"huggingface-space","key_envs":[],"base_env":"HF_SPACE_BASE_URL","model_env":"HF_SPACE_MODEL","default_base":"public","default_model":"Qwen3-VL-2B-Instruct","vision":True,"public":True},
    {"name":"deepseek","key_envs":["UCOA_DEEPSEEK_API_KEY"],"base_env":"UCOA_DEEPSEEK_BASE_URL","model_env":"UCOA_DEEPSEEK_MODEL","default_base":"https://api.deepseek.com","default_model":"deepseek-chat","vision":False},
    {"name":"omniroute","key_envs":["UCOA_OMNIROUTE_API_KEY"],"base_env":"UCOA_OMNIROUTE_BASE_URL","model_env":"UCOA_OMNIROUTE_MODEL","default_base":"","default_model":"auto","vision":True},
    {"name":"cerebras","key_envs":["UCOA_CEREBRAS_API_KEY"],"base_env":"UCOA_CEREBRAS_BASE_URL","model_env":"UCOA_CEREBRAS_MODEL","default_base":"https://api.cerebras.ai/v1","default_model":"gpt-oss-120b","vision":False},
    {"name":"groq","key_envs":["UCOA_GROQ_API_KEY"],"base_env":"UCOA_GROQ_BASE_URL","model_env":"UCOA_GROQ_MODEL","default_base":"https://api.groq.com/openai/v1","default_model":"openai/gpt-oss-120b","vision":False},
]

@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float = 0.0

_BREAKERS = {p["name"]: CircuitState() for p in PROVIDERS}
_VISION_CACHE: dict[str, tuple[float, dict, str]] = {}


def _first_env(names):
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value, name
    return "", names[0] if names else "public"


def _cfg(p):
    if p.get("public"):
        return "public", "", "public", bool(p["vision"]), "public"
    key, key_name = _first_env(p["key_envs"])
    if not key:
        raise RuntimeError("provider not configured")
    base = (os.getenv(p["base_env"], "").strip() or p["default_base"]).rstrip("/")
    model = os.getenv(p["model_env"], p["default_model"]).strip()
    if not base or not model:
        raise RuntimeError("provider endpoint/model not configured")
    return base, key, model, bool(p["vision"]), key_name


def _provider(name):
    return next(p for p in PROVIDERS if p["name"] == name)


def _is_open(name):
    state = _BREAKERS[name]
    if not state.opened_at:
        return False
    if time.monotonic() - state.opened_at >= CB_COOLDOWN:
        state.failures = 0
        state.opened_at = 0.0
        return False
    return True


def _success(name):
    _BREAKERS[name] = CircuitState()


def _failure(name):
    state = _BREAKERS[name]
    state.failures += 1
    if state.failures >= CB_FAILURES:
        state.opened_at = time.monotonic()


def _extract_openai_text(body: dict) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("no choices")
    content = (choices[0].get("message") or {}).get("content", "")
    if isinstance(content, list):
        content = "".join(str(item.get("text", "") if isinstance(item, dict) else item) for item in content)
    text = str(content).strip()
    if not text:
        raise RuntimeError("empty response")
    return text


def _extract_gemini_text(body: dict) -> str:
    candidates = body.get("candidates") or []
    if not candidates:
        error = body.get("error") or {}
        raise RuntimeError(error.get("message", "Gemini returned no candidates"))
    pieces = []
    for part in (candidates[0].get("content") or {}).get("parts", []):
        if isinstance(part, dict) and part.get("text"):
            pieces.append(str(part["text"]))
    text = "".join(pieces).strip()
    if not text:
        raise RuntimeError("Gemini returned empty content")
    return text


def _gemini_generate(base: str, key: str, model: str, system: str, user: str, image: str | None, timeout: float) -> str:
    parts = [{"text": user}]
    if image:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image}})
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max(64, min(MAX_TOKENS, 2048)),
        },
    }
    if model.startswith("gemini-3."):
        payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "low"}
    url = f"{base}/models/{model}:generateContent"
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key, "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return _extract_gemini_text(json.loads(response.read().decode("utf-8")))


def _chat(base, key, model, system, user, image, timeout):
    content = user
    if image:
        content = [{"type":"text","text":user},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image}"}}]
    payload = {"model":model,"temperature":0,"max_tokens":MAX_TOKENS,"messages":[{"role":"system","content":system},{"role":"user","content":content}]}
    if model.startswith("gemini-3"): payload["reasoning_effort"] = "low"
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type":"application/json","Accept":"application/json"}
    if key: headers["Authorization"] = f"Bearer {key}"
    with urlopen(Request(url,data=json.dumps(payload,ensure_ascii=False).encode(),headers=headers,method="POST"),timeout=timeout) as resp:
        return _extract_openai_text(json.loads(resp.read().decode()))


def _space_call(system, user, image, timeout):
    from gradio_client import Client, handle_file
    from PIL import Image
    raw = base64.b64decode(image) if image else None
    with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
        if raw: f.write(raw)
        else: Image.new("RGB", (32,32), (255,255,255)).save(f, "JPEG")
        f.flush()
        client = Client(VISION_SPACE, verbose=False)
        return str(client.predict({"text":system+"\n"+user,"files":[handle_file(f.name)]},[],api_name="/qwen_chat_fn"))


def _ordered(image):
    configured=[]
    for p in PROVIDERS:
        try: _cfg(p); configured.append(p["name"])
        except Exception: pass
    preferred = ["gemini","gemini-2","huggingface-vision","huggingface-space","omniroute","huggingface-text","deepseek"] if image else ["gemini","gemini-2","huggingface-text","cerebras","groq","deepseek","omniroute"]
    return [name for name in preferred if name in configured and not _is_open(name)]


def call(system, user, image=None):
    errors=[]
    timeout=VISION_TIMEOUT if image else TEXT_TIMEOUT
    for name in _ordered(bool(image)):
        started=time.perf_counter()
        try:
            p=_provider(name); base,key,model,supports_vision,key_name=_cfg(p)
            if image and not supports_vision: raise RuntimeError("provider does not support vision")
            with span("ai.provider", f"{name} inference", provider=name, model=model, multimodal=bool(image), credential=key_name):
                if p.get("native_gemini"):
                    raw=_gemini_generate(base,key,model,system,user,image,timeout)
                elif p.get("public"):
                    raw=_space_call(system,user,image,timeout)
                else:
                    raw=_chat(base,key,model,system,user,image,timeout)
            _success(name); set_measurement(f"provider.{name}.latency_ms",(time.perf_counter()-started)*1000); return raw,name
        except HTTPError as exc:
            _failure(name); errors.append(f"{name}:HTTP_{exc.code}")
        except (URLError,TimeoutError) as exc:
            _failure(name); errors.append(f"{name}:{type(exc).__name__}")
        except Exception as exc:
            _failure(name); errors.append(f"{name}:{str(exc)[:160]}")
    raise RuntimeError("all providers failed; "+",".join(errors) if errors else "no provider configured")


def _extract_json(raw):
    text=re.sub(r"^```(?:json)?\s*|\s*```$","",raw.strip())
    try:
        value=json.loads(text)
        if isinstance(value,dict): return value
    except json.JSONDecodeError: pass
    match=re.search(r"\{.*\}",text,re.S)
    if match:
        value=json.loads(match.group(0))
        if isinstance(value,dict): return value
    raise ValueError("provider returned non-JSON output")


def reasoning(system,user):
    return call(system,user,None)


def visual(task,ui_tree,image):
    key=hashlib.sha256(image.encode("ascii","ignore")).hexdigest()
    now=time.monotonic(); cached=_VISION_CACHE.get(key)
    if cached and now-cached[0] <= CACHE_TTL: return cached[1],cached[2]
    system='You are UCOA visual perception. Inspect only the current Android screenshot and UI tree. Return ONLY valid JSON: {"screen_summary":string,"elements":[{"text":string,"role":string,"x":number,"y":number}],"visible_goal_state":string,"confidence":number}. Never invent unseen elements. Coordinates normalized 0..1000.'
    raw,provider=call(system,json.dumps({"task":task,"ui_tree":ui_tree[:18000]},ensure_ascii=False),image)
    value=_extract_json(raw); _VISION_CACHE[key]=(now,value,provider); return value,provider


def safe_text_probe():
    configured=[]
    for p in PROVIDERS:
        try:
            _,_,model,vision,key_name=_cfg(p)
            configured.append({"provider":p["name"],"model":model,"vision":vision,"credential_env":key_name})
        except Exception: pass
    try:
        raw,provider=call("Return ONLY JSON.","Return exactly {\"ok\":true}.")
        return {"ok":True,"configured":True,"providers":[{"provider":provider,"model":_provider(provider).get("default_model"),"ok":True}],"response":_extract_json(raw),"configured_candidates":[{k:v for k,v in x.items() if k!="credential_env"} for x in configured]}
    except Exception as exc:
        return {"ok":False,"configured":bool(configured),"providers":configured,"error":type(exc).__name__}
