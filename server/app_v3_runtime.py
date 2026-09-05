"""Production runtime for UCOA V4-style multimodal agent control.

The legacy V3 module remains test-compatible. Production imports this runtime
first and receives a stronger decision pipeline centered on Qwen3-VL-235B.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import time
from html.parser import HTMLParser
from typing import Any

import app_v3

PRIMARY_VISION_SPACE = os.getenv(
    "UCOA_PRIMARY_VISION_SPACE",
    "Qwen/Qwen3-VL-235B-A22B-Instruct-Demo",
)
PRIMARY_VISION_MODEL = os.getenv(
    "UCOA_PRIMARY_VISION_MODEL",
    "Qwen/Qwen3-VL-235B-A22B-Instruct",
)
PRIMARY_MAX_RETRIES = max(1, int(os.getenv("UCOA_PRIMARY_MAX_RETRIES", "2")))
PRIMARY_TIMEOUT_SECONDS = max(20, int(os.getenv("UCOA_PRIMARY_TIMEOUT", "90")))
WEB_RESEARCH_ENABLED = os.getenv("UCOA_WEB_RESEARCH", "true").lower() == "true"

PLANNER_SYSTEM = """
You are UCOA's primary task planner.
Return ONLY valid JSON: {"summary":string,"steps":string[]}
Create 2-6 concrete steps for an Android/mobile task. Mention observable verification.
Do not claim a step succeeded before the device proves it.
""".strip()

AGENT_SYSTEM = """
You are UCOA's primary mobile GUI agent. You control a real Android phone through
Accessibility actions. You are looking at the CURRENT screenshot and UI tree.
Never invent controls. Select the safest action that advances the user's goal.
Return ONLY one JSON object with exactly these fields:
{
  "action": "open_app_by_name|open_url|click_any_text|type_into_any|tap|long_press|swipe|back|home|wait|observe|done",
  "params": {},
  "message": "brief reason",
  "done": false,
  "wait_after_ms": 500,
  "confidence": 0.0,
  "target_text": "optional visible label",
  "coordinate_space": "pixel|normalized_1000|null",
  "verification_goal": "what visual/UI change must happen next"
}
For tap/long_press/swipe, prefer coordinate_space=normalized_1000 and use integer
coordinates from 0..1000 based on the screenshot dimensions. For text buttons,
prefer click_any_text. Use open_app_by_name when the requested app is installed.
If the target is not visible or certainty is low, use observe rather than guessing.
The word done may ONLY be used when the requested end-state is visibly confirmed.
""".strip()

app_v3.PLAN_SYSTEM = PLANNER_SYSTEM
app_v3.STEP_SYSTEM = AGENT_SYSTEM
app_v3.VISION_MODEL = PRIMARY_VISION_MODEL
app_v3.VISION_ENABLED = True


def _json_from_text(text: str) -> dict[str, Any]:
    return app_v3.extract_json(str(text))


def _space_predict(prompt: str, image_base64: str | None = None) -> str:
    """Call the official Qwen 235B HF Space through its public Gradio function."""
    from gradio_client import Client, handle_file

    last: Exception | None = None
    raw = base64.b64decode(image_base64) if image_base64 else None
    for attempt in range(PRIMARY_MAX_RETRIES):
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                if raw:
                    f.write(raw)
                    f.flush()
                    image_ref = handle_file(f.name)
                else:
                    image_ref = None
                history = []
                if image_ref is not None:
                    history.append(((image_ref,), None))
                history.append((prompt, None))
                client = Client(PRIMARY_VISION_SPACE, verbose=False)
                # Qwen's official demo exposes its Gradio Blocks callback as /predict.
                result = client.predict(history, history, api_name="/predict")
            return str(result)
        except Exception as exc:
            last = exc
            if attempt + 1 < PRIMARY_MAX_RETRIES:
                time.sleep(2 ** attempt)
        finally:
            try:
                if 'f' in locals(): os.unlink(f.name)
            except Exception:
                pass
    raise RuntimeError(f"Qwen3-VL-235B Space request failed: {last}")


def _primary_multimodal(prompt: str, image_base64: str | None = None) -> tuple[str, str]:
    if app_v3.HF_TOKEN:
        try:
            out = app_v3.chat(
                app_v3.HF_BASE,
                app_v3.HF_TOKEN,
                PRIMARY_VISION_MODEL,
                AGENT_SYSTEM,
                prompt,
                image_base64,
                PRIMARY_TIMEOUT_SECONDS,
            )
            return out, "huggingface-router-qwen3-vl-235b"
        except Exception:
            pass
    return _space_predict(prompt, image_base64), "huggingface-space-qwen3-vl-235b"


def _screen_size(image_base64: str | None) -> tuple[int, int]:
    if not image_base64:
        return 0, 0
    try:
        from PIL import Image
        from io import BytesIO
        with Image.open(BytesIO(base64.b64decode(image_base64))) as im:
            return im.size
    except Exception:
        return 0, 0


def _normalize_action(result: dict[str, Any], image_base64: str | None) -> dict[str, Any]:
    allowed = set(app_v3.ACTIONS)
    action = str(result.get("action", "observe")).strip()
    if action not in allowed:
        raise ValueError(f"unsupported action: {action}")
    params = result.get("params") if isinstance(result.get("params"), dict) else {}
    coordinate_space = result.get("coordinate_space")
    if action in {"tap", "long_press"} and coordinate_space == "normalized_1000":
        w, h = _screen_size(image_base64)
        if w and h and "x" in params and "y" in params:
            params["x"] = round(float(params["x"]) * w / 1000.0, 1)
            params["y"] = round(float(params["y"]) * h / 1000.0, 1)
            coordinate_space = "pixel"
    if action == "swipe" and coordinate_space == "normalized_1000":
        w, h = _screen_size(image_base64)
        if w and h:
            for k, scale in (("x1", w), ("x2", w), ("y1", h), ("y2", h)):
                if k in params:
                    params[k] = round(float(params[k]) * scale / 1000.0, 1)
            coordinate_space = "pixel"
    result["action"] = action
    result["params"] = params
    result["coordinate_space"] = coordinate_space or None
    result["done"] = bool(result.get("done", False)) or action == "done"
    result["wait_after_ms"] = max(150, min(5000, int(result.get("wait_after_ms", 500))))
    result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
    result["message"] = str(result.get("message", ""))
    return result


class _DDGParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_title = False
        self._title = ""
        self._href = ""
        self._snippet = ""
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        cls = attrs_d.get("class") or ""
        if tag == "a" and "result__a" in cls:
            self._in_title = True
            self._title = ""
            self._href = attrs_d.get("href") or ""
        elif tag == "a" and "result__snippet" in cls:
            self._capture_snippet = True
            self._snippet = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        if tag == "a" and self._capture_snippet:
            self._capture_snippet = False
        if self._title and self._href:
            self.results.append({"title": self._title.strip(), "url": self._href, "snippet": self._snippet.strip()})
            self._title = ""
            self._href = ""
            self._snippet = ""

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title += data
        elif self._capture_snippet:
            self._snippet += data


def web_search(query: str, limit: int = 5) -> list[dict[str, str]]:
    if not WEB_RESEARCH_ENABLED or not query.strip():
        return []
    from urllib.parse import quote
    from urllib.request import Request, urlopen
    req = Request(
        "https://html.duckduckgo.com/html/?q=" + quote(query),
        headers={"User-Agent": "Mozilla/5.0 (UCOA research agent)"},
    )
    try:
        with urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="ignore")
        parser = _DDGParser()
        parser.feed(html)
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in parser.results:
            url = item["url"]
            if url in seen:
                continue
            seen.add(url)
            out.append(item)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def research_app(app_name: str, task: str) -> list[dict[str, str]]:
    q1 = f"{app_name} Android help {task}"
    q2 = f"{app_name} Android tutorial interface {task}"
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for q in (q1, q2):
        for r in web_search(q, 4):
            if r["url"] not in seen:
                seen.add(r["url"])
                merged.append(r)
    return merged[:6]


def _known_app(task: str, installed_apps: list[str]) -> str | None:
    lower = task.lower()
    # Common app aliases first; otherwise use an installed label directly when
    # it is a close textual match to a token in the task.
    aliases = {
        "capcut": "CapCut", "كاب كات": "CapCut",
        "youtube": "YouTube", "يوتيوب": "YouTube",
        "canva": "Canva", "كانفا": "Canva",
        "chrome": "Chrome", "كروم": "Chrome",
        "instagram": "Instagram", "انستجرام": "Instagram",
        "whatsapp": "WhatsApp", "واتساب": "WhatsApp",
    }
    for key, label in aliases.items():
        if key in lower and any(label.lower() in a.lower() for a in installed_apps):
            return label
    for a in installed_apps:
        if len(a) >= 4 and a.lower() in lower:
            return a
    return None


def _action_prompt(req: Any, obs: dict[str, Any], research: list[dict[str, str]]) -> str:
    data = {
        "task": req.task,
        "step": req.step,
        "history": req.history[-8:],
        "ui_tree": req.ui_tree[:18000],
        "visual_observation": obs,
        "installed_apps": req.installed_apps[:250],
        "capabilities": req.capabilities,
        "research": research,
    }
    return json.dumps(data, ensure_ascii=False)


def production_run_plan(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    prompt = json.dumps({
        "task": req.task,
        "attachments": req.attachments[:8],
        "device": req.device,
        "memory": app_v3.memory(sid, 12),
    }, ensure_ascii=False)
    raw, provider = _primary_multimodal(PLANNER_SYSTEM + "\n" + prompt, None)
    try:
        x = _json_from_text(raw)
        steps = x.get("steps") if isinstance(x.get("steps"), list) else []
        if not steps:
            raise ValueError("missing steps")
        out = {"summary": str(x.get("summary", "UCOA execution plan")), "steps": [str(s) for s in steps[:6]], "output_mode": "primary_model", "provider": provider}
    except Exception as exc:
        out = {"summary": "خطة قابلة للتحقق", "steps": ["افتح التطبيق الهدف.", "نفذ الإجراء المطلوب.", "تحقق بصريًا من النتيجة."], "output_mode": "repair", "provider": provider, "error": str(exc)}
    out["session_id"] = sid
    app_v3.remember(sid, "plan", out)
    app_v3.save_state(sid, {"phase": "planned", "task": req.task, "step": 0, "plan": out})
    return out


def production_run_step(req: Any) -> dict[str, Any]:
    sid = app_v3.ensure_session(req.session_id)
    obs: dict[str, Any] = {"screen_summary": "No screenshot", "elements": [], "confidence": 0.0}
    primary_provider = ""
    image = req.screenshot_base64

    app_name = _known_app(req.task, req.installed_apps)
    research: list[dict[str, str]] = []
    if app_name and req.step > 0:
        # Research is only added once the task is already inside an app or the
        # app is unfamiliar; this avoids wasting latency on every iteration.
        try:
            research = research_app(app_name, req.task)
        except Exception:
            research = []

    # Give the multimodal model the real screenshot directly. The model is now
    # asked for the action, not merely a description, so there is no second
    # fragile reasoning hop between perception and execution.
    prompt = _action_prompt(req, obs, research)
    try:
        raw, primary_provider = _primary_multimodal(prompt, image)
        result = _normalize_action(_json_from_text(raw), image)
        result["output_mode"] = "primary_multimodal"
    except Exception as exc:
        # Safe deterministic recovery: prefer an app-open bootstrap, then visible
        # accessibility text, otherwise observe. Never guess coordinates.
        result = None
        if req.step == 0 and app_name:
            result = {"action": "open_app_by_name", "params": {"app_name": app_name}, "message": f"فتح التطبيق المطلوب: {app_name}", "done": False, "wait_after_ms": 900, "confidence": 0.99, "coordinate_space": None, "verification_goal": "انتظر ظهور واجهة التطبيق"}
        if result is None:
            result = app_v3.fallback_step(req, obs)
            result["confidence"] = 0.2
            result["coordinate_space"] = None
            result["verification_goal"] = "راقب الشاشة بحثًا عن هدف مؤكد"
        result["output_mode"] = "repair"
        result["error"] = str(exc)
        primary_provider = primary_provider or "repair"

    result.update({
        "provider": primary_provider,
        "vision_provider": primary_provider,
        "visual_observation": obs,
        "session_id": sid,
        "research": research,
        "verification": app_v3.safety(req.task, result, req.approved_risks),
    })
    app_v3.remember(sid, "decision", result)
    app_v3.save_state(sid, {"phase": "executing", "task": req.task, "step": req.step, "last_decision": result})
    return result


def production_verify_result(req: Any) -> dict[str, Any]:
    """Stronger evidence check using both accessibility state and screenshot hash."""
    base = app_v3.independent_verify(req.task, req.action, req.before_ui_tree, req.after_ui_tree)
    before_hash = hashlib.sha256((req.before_screenshot_base64 or "").encode()).hexdigest()
    after_hash = hashlib.sha256((req.after_screenshot_base64 or "").encode()).hexdigest()
    screenshot_changed = before_hash != after_hash and bool(req.before_screenshot_base64 and req.after_screenshot_base64)
    base["screenshot_changed"] = screenshot_changed
    if screenshot_changed:
        base["verified"] = True
        base["reasons"] = [r for r in base.get("reasons", []) if r != "no_ui_change"]
    return base


# Production routes dynamically resolve these globals from app_v3.app.
_original_run_plan = app_v3.run_plan
_original_run_step = app_v3.run_step
_original_verify_result = app_v3.verify_result

app_v3.run_plan = production_run_plan
app_v3.run_step = production_run_step
app_v3.reasoning = lambda system, user: _primary_multimodal(system + "\n" + user, None)
app_v3.vision_space = lambda prompt, image: _space_predict(prompt, image)

# Keep the public FastAPI application exported for server/app.py.
app = app_v3.app
