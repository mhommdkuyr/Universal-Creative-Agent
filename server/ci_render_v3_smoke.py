from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

BASE = os.getenv("BRAIN_URL", "https://ucoa-agent-brain.onrender.com").rstrip("/")


def request(method: str, path: str, payload=None, token: str | None = None, timeout: int = 30):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def bootstrap() -> str:
    master = os.getenv("UCOA_AGENT_TOKEN", "").strip()
    if master:
        return master
    body = request("POST", "/v1/client/session", {
        "install_id": "ci-release-acceptance",
        "app_version": "ci",
        "platform": "github-actions",
        "device": {"runner": "ubuntu-latest"},
    }, timeout=20)
    token = str(body.get("session_token", ""))
    if not token:
        raise RuntimeError(f"client session bootstrap failed: {body}")
    return token


def poll(job_id: str, token: str):
    for _ in range(180):
        x = request("GET", "/v1/agent/jobs/" + job_id, token=token, timeout=20)
        if x.get("status") == "completed":
            return x["result"]
        if x.get("status") == "failed":
            raise RuntimeError(x.get("error", "job failed"))
        time.sleep(1)
    raise TimeoutError("job timeout")


def screenshot_b64():
    img = Image.new("RGB", (900, 500), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
    except Exception:
        font = ImageFont.load_default()
    d.text((80, 70), "UCOA Test Screen", fill="black", font=font)
    d.rounded_rectangle((260, 260, 640, 390), radius=20, fill="#dddddd", outline="#222222", width=4)
    d.text((355, 300), "CONTINUE", fill="black", font=font)
    out = BytesIO(); img.save(out, format="JPEG", quality=90)
    return base64.b64encode(out.getvalue()).decode()


mode = sys.argv[1]
token = bootstrap()
if mode == "plan":
    submitted = request("POST", "/v1/agent/plan", {"task": "Open the appropriate app, perform the requested action, and verify the result.", "device": {"android": 35}}, token)
    result = poll(submitted["job_id"], token)
    assert len(result.get("steps", [])) >= 2, result
    assert result.get("provider") not in {None, "", "repair"}, result
    print("PLAN_V4_OK", json.dumps(result, ensure_ascii=False))
elif mode == "step":
    submitted = request("POST", "/v1/agent/step", {"task": "Press the visible CONTINUE button.", "step": 0, "history": [], "ui_tree": "[{\"text\":\"CONTINUE\",\"class\":\"android.widget.Button\"}]", "screenshot_base64": screenshot_b64(), "installed_apps": ["Chrome"], "capabilities": ["click_any_text", "tap", "observe", "done"]}, token)
    result = poll(submitted["job_id"], token)
    provider = str(result.get("vision_provider", ""))
    assert provider not in {"", "repair", "compatibility"}, result
    assert result.get("visual_observation"), result
    assert result.get("action") in {"click_any_text", "tap", "observe", "done"}, result
    print("RENDER_V4_MULTIMODAL_OK", json.dumps({"vision_provider": provider, "provider": result.get("provider"), "action": result.get("action"), "visual_observation": result.get("visual_observation")}, ensure_ascii=False))
elif mode == "state":
    sid = request("POST", "/v1/agent/sessions", {"title": "ci-v4"}, token)["session_id"]
    request("POST", "/v1/agent/state", {"session_id": sid, "state": {"task": "smoke", "step": 2, "status": "verified"}}, token)
    state = request("GET", "/v1/agent/state/" + sid, token=token, timeout=20)
    assert state["state"]["step"] == 2
    verified = request("POST", "/v1/agent/verify-result", {"task": "press continue", "action": {"action": "click_any_text", "params": {"texts": ["CONTINUE"]}}, "before_ui_tree": "[{\"text\":\"CONTINUE\"}]", "after_ui_tree": "[{\"text\":\"NEXT\"}]", "session_id": sid}, token)
    assert verified["verified"] is True, verified
    print("RENDER_V4_STATE_VERIFIER_OK", sid)
else:
    raise SystemExit("unknown mode")
