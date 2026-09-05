from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

BASE = "https://ucoa-agent-brain-local2.onrender.com"

def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def poll(job_id):
    for _ in range(180):
        with urllib.request.urlopen(BASE + "/v1/agent/jobs/" + job_id, timeout=20) as r:
            x = json.loads(r.read().decode())
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
if mode == "plan":
    submitted = post("/v1/agent/plan", {"task": "Open the appropriate app, perform the requested action, and verify the result.", "device": {"android": 35}})
    result = poll(submitted["job_id"])
    assert len(result.get("steps", [])) >= 2
    print("PLAN_V3_OK", json.dumps(result, ensure_ascii=False))
elif mode == "step":
    submitted = post("/v1/agent/step", {"task": "Press the visible CONTINUE button.", "step": 0, "history": [], "ui_tree": "[{\"text\":\"CONTINUE\",\"class\":\"android.widget.Button\"}]", "screenshot_base64": screenshot_b64(), "installed_apps": ["Chrome"], "capabilities": ["click_any_text", "tap", "observe", "done"]})
    result = poll(submitted["job_id"])
    assert result.get("vision_provider") in {"huggingface-space", "huggingface-router"}, result
    assert result.get("visual_observation"), result
    assert result.get("action") in {"click_any_text", "tap", "observe", "done"}, result
    print("RENDER_V3_VISION_REASONING_OK", json.dumps({"vision_provider": result.get("vision_provider"), "provider": result.get("provider"), "action": result.get("action"), "visual_observation": result.get("visual_observation")}, ensure_ascii=False))
elif mode == "state":
    sid = post("/v1/agent/sessions", {"title": "ci-v3"})["session_id"]
    post("/v1/agent/state", {"session_id": sid, "state": {"task": "smoke", "step": 2, "status": "verified"}})
    with urllib.request.urlopen(BASE + "/v1/agent/state/" + sid, timeout=20) as r:
        state = json.loads(r.read().decode())
    assert state["state"]["step"] == 2
    verified = post("/v1/agent/verify-result", {"task": "press continue", "action": {"action": "click_any_text", "params": {"texts": ["CONTINUE"]}}, "before_ui_tree": "[{\"text\":\"CONTINUE\"}]", "after_ui_tree": "[{\"text\":\"NEXT\"}]", "session_id": sid})
    assert verified["verified"] is True, verified
    print("RENDER_V3_STATE_VERIFIER_OK", sid)
else:
    raise SystemExit("unknown mode")
