"""Production provider router for UCOA.

Goals:
- fast deterministic failover
- provider circuit breakers
- separate connect/read timeout budget
- screenshot/vision result cache
- optional Sentry timing
- no secret or payload logging

The public functions intentionally stay compatible with the existing UCOA V3/V4
runtime: ``reasoning()``, ``visual()`` and ``safe_text_probe()``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from observability import span, set_measurement

CONNECT_TIMEOUT = float(os.getenv("UCOA_PROVIDER_CONNECT_TIMEOUT", "2"))
TEXT_TIMEOUT = float(os.getenv("UCOA_PROVIDER_TEXT_TIMEOUT", "8"))
VISION_TIMEOUT = float(os.getenv("UCOA_PROVIDER_VISION_TIMEOUT", "12"))
MAX_TOKENS = int(os.getenv("UCOA_PROVIDER_MAX_TOKENS", "256"))
CACHE_TTL = max(0.0, float(os.getenv("UCOA_VISION_CACHE_TTL", "3")))
CB_FAILURES = max(1, int(os.getenv("UCOA_PROVIDER_CB_FAILURES", "3")))
CB_COOLDOWN = max(1.0, float(os.getenv("UCOA_PROVIDER_CB_COOLDOWN", "30")))

PROVIDERS = [
    {"name": "gemini", "key_env": "UCOA_GEMINI_API_KEY", "base_env": "UCOA_GEMINI_BASE_URL", "model_env": "UCOA_GEMINI_MODEL", "default_base": "https://generativelanguage.googleapis.com/v1beta/openai", "default_model": "gemini-3.8-flash", "vision": True},
    {"name": "deepseek", "key_env": "UCOA_DEEPSEEK_API_KEY", "base_env": "UCOA_DEEPSEEK_BASE_URL", "model_env": "UCOA_DEEPSEEK_MODEL", "default_base": "https://api.deepseek.com", "default_model": "deepseek-v4-flash-vision-exp", "vision": True},
    {"name": "omniroute", "key_env": "UCOA_OMNIROUTE_API_KEY", "base_env": "UCOA_OMNIROUTE_BASE_URL", "model_env": "UCOA_OMNIROUTE_MODEL", "default_base": "", "default_model": "auto", "vision": True},
    {"name": "cerebras", "key_env": "UCOA_CEREBRAS_API_KEY", "base_env": "UCOA_CEREBRAS_BASE_URL", "model_env": "UCOA_CEREBRAS_MODEL", "default_base": "https://api.cerebras.ai/v1", "default_model": "gpt-oss-120b", "vision": False},
    {"name": "groq", "key_env": "UCOA_GROQ_API_KEY", "base_env": "UCOA_GROQ_BASE_URL", "model_env": "UCOA_GROQ_MODEL", "default_base": "https://api.groq.com/openai/v1", "default_model": "openai/gpt-oss-120b", "vision": False},
]


@dataclass
class _Breaker:
    failures: int = 0
    opened_at: float = 0.0


_BREAKERS: dict[str, _Breaker] = {p["name"]: _Breaker() for p in PROVIDERS}
_VISION_CACHE: dict[str, tuple[float, dict[str, Any], str]] = {}


def _cfg(p: dict[str, Any]) -> tuple[str, str, str, bool]:
    key = os.getenv(p["key_env"], "").strip()
    if not key:
        raise RuntimeError("provider not configured")
    configured_base = os.getenv(p["base_env"], "").strip() if p["base_env"] else ""
    base = (configured_base or p["default_base"]).rstrip("/")
    model = os.getenv(p["model_env"], p["default_model"]).strip()
    if not base or not model:
        raise RuntimeError("provider endpoint/model not configured")
    return base, key, model, bool(p["vision"])


def _provider(name: str) -> dict[str, Any]:
    return next(p for p in PROVIDERS if p["name"] == name)


def _is_open(name: str) -> bool:
    b = _BREAKERS[name]
    if b.opened_at <= 0:
        return False
    if time.monotonic() - b.opened_at >= CB_COOLDOWN:
        b.opened_at = 0.0
        b.failures = 0
        return False
    return True


def _success(name: str) -> None:
    b = _BREAKERS[name]
    b.failures = 0
    b.opened_at = 0.0


def _failure(name: str) -> None:
    b = _BREAKERS[name]
    b.failures += 1
    if b.failures >= CB_FAILURES:
        b.opened_at = time.monotonic()


def _chat(base: str, key: str, model: str, system: str, user: str, image: str | None, timeout: float) -> str:
    content: Any = user
    if image:
        content = [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "high"}}]
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    }
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("no choices")
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
    text = str(content).strip()
    if not text:
        raise RuntimeError("empty response")
    return text


def _ordered(image: str | None) -> list[str]:
    configured: set[str] = set()
    for p in PROVIDERS:
        try:
            _cfg(p)
            configured.add(p["name"])
        except Exception:
            continue
    preferred = ["gemini", "deepseek", "omniroute", "cerebras", "groq"] if image else ["cerebras", "groq", "gemini", "omniroute", "deepseek"]
    return [n for n in preferred if n in configured and not _is_open(n)]


def call(system: str, user: str, image: str | None = None) -> tuple[str, str]:
    errors: list[str] = []
    timeout = VISION_TIMEOUT if image else TEXT_TIMEOUT
    for name in _ordered(image):
        started = time.perf_counter()
        try:
            p = _provider(name)
            base, key, model, supports_vision = _cfg(p)
            if image and not supports_vision:
                raise RuntimeError("provider does not support vision")
            with span("ai.provider", f"{name} inference", provider=name, model=model, multimodal=bool(image)):
                raw = _chat(base, key, model, system, user, image, timeout)
            _success(name)
            set_measurement(f"provider.{name}.latency_ms", (time.perf_counter() - started) * 1000)
            return raw, name
        except HTTPError as exc:
            _failure(name)
            errors.append(f"{name}:HTTP_{exc.code}")
        except (URLError, TimeoutError) as exc:
            _failure(name)
            errors.append(f"{name}:{type(exc).__name__}")
        except Exception as exc:
            _failure(name)
            errors.append(f"{name}:{str(exc)[:120]}")
    raise RuntimeError("all providers failed; " + ",".join(errors))


def _extract_json(raw: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        value = json.loads(match.group(0))
        if isinstance(value, dict):
            return value
    raise ValueError("provider returned non-JSON output")


def reasoning(system: str, user: str) -> tuple[str, str]:
    return call(system, user, None)


def visual(task: str, ui_tree: str, image: str) -> tuple[dict[str, Any], str]:
    key = hashlib.sha256(image.encode("ascii", "ignore")).hexdigest()
    now = time.monotonic()
    cached = _VISION_CACHE.get(key)
    if cached and now - cached[0] <= CACHE_TTL:
        return cached[1], cached[2]
    system = (
        "You are UCOA visual perception. Inspect only the current Android screenshot and UI tree. "
        "Return ONLY valid JSON, no markdown: {\"screen_summary\":string,\"elements\":[{\"text\":string,\"role\":string,\"x\":number,\"y\":number}],\"visible_goal_state\":string,\"confidence\":number}. "
        "Never invent unseen elements. Coordinates must be normalized to 0..1000."
    )
    user = json.dumps({"task": task, "ui_tree": ui_tree[:18000]}, ensure_ascii=False)
    raw, provider = call(system, user, image)
    try:
        value = _extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        p = _provider(provider)
        base, api_key, model, _ = _cfg(p)
        repair = _chat(base, api_key, model, "Convert RAW VISUAL ANALYSIS into ONLY valid JSON matching the required schema. Preserve only explicit facts.", "SCHEMA={screen_summary:string,elements:[{text:string,role:string,x:number,y:number}],visible_goal_state:string,confidence:number}\nRAW=" + raw[:5000], None, min(TEXT_TIMEOUT, 6))
        value = _extract_json(repair)
    _VISION_CACHE[key] = (now, value, provider)
    return value, provider


def probe(vision: bool = False) -> dict[str, Any]:
    results = []
    image: str | None = None
    if vision:
        from io import BytesIO
        from PIL import Image
        img = Image.new("RGB", (320, 180), "white")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle((100, 65, 220, 115), fill="#dddddd", outline="black")
        draw.text((127, 82), "CONTINUE", fill="black")
        buf = BytesIO(); img.save(buf, format="JPEG", quality=85)
        image = base64.b64encode(buf.getvalue()).decode("ascii")
    for p in PROVIDERS:
        name = p["name"]
        started = time.perf_counter()
        try:
            base, key, model, supports_vision = _cfg(p)
            if vision and not supports_vision:
                results.append({"provider":name,"model":model,"vision":supports_vision,"ok":False,"latency_s":0.0,"error":"vision_unsupported"})
                continue
            raw = _chat(base, key, model, "Return ONLY JSON.", "Inspect the image and return exactly {\"ok\":true,\"target\":\"CONTINUE\"}." if vision else "Return exactly {\"ok\":true}.", image if vision else None, min(VISION_TIMEOUT if vision else TEXT_TIMEOUT, 8))
            parsed = _extract_json(raw) if raw else {}
            ok = bool(parsed.get("ok", False)) if isinstance(parsed, dict) else bool(raw.strip())
            results.append({"provider": name, "model": model, "vision": supports_vision, "ok": ok, "latency_s": round(time.perf_counter() - started, 3)})
        except Exception as exc:
            results.append({"provider": name, "model": p["default_model"], "vision": p["vision"], "ok": False, "latency_s": round(time.perf_counter() - started, 3), "error": str(exc)[:160]})
    good = [r for r in results if r["ok"]]
    return {"ok": bool(good), "best": min(good, key=lambda r: r["latency_s"], default=None), "providers": results}


def safe_text_probe() -> dict[str, Any]:
    return probe(False)
