"""Runtime compatibility shim for the public Qwen3-VL Gradio Space."""
from __future__ import annotations

import base64
import json
import re
import tempfile
import time

import app_v3

app_v3.PLAN_SYSTEM = (
    "You are UCOA planner. Return JSON {summary:string,steps:string[]}. "
    "Create 2-5 ordered steps and include verification. Never claim success."
)
app_v3.STEP_SYSTEM = (
    "You are UCOA action reasoner. Use the visual observation and UI tree. "
    "Return ONLY JSON with action, params, message, done, wait_after_ms. "
    "Choose only from the provided capabilities. Never invent hidden UI."
)

VISION_SPACE_ID = "akhaliq/Qwen3-VL-2B-Instruct"


def vision_space(prompt: str, image: str) -> str:
    from gradio_client import Client, handle_file

    raw = base64.b64decode(image)
    last_error = None
    for target in (VISION_SPACE_ID, app_v3.VISION_SPACE):
        for attempt in range(2):
            try:
                with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
                    f.write(raw)
                    f.flush()
                    client = Client(target, verbose=False)
                    result = client.predict(
                        {"text": prompt, "files": [handle_file(f.name)]},
                        [],
                        api_name="/chat",
                    )
                text = str(result)
                # Keep real VLM output. Normalize only when the Space returns
                # ordinary text rather than the JSON requested in the prompt.
                try:
                    app_v3.extract_json(text)
                    return text
                except Exception:
                    normalized = text.replace("_", " ")
                    labels = []
                    for label in ("continue", "التالي", "متابعة", "موافق", "ok", "تأكيد", "submit", "إرسال"):
                        if re.search(rf"\b{re.escape(label)}\b", normalized, re.IGNORECASE):
                            labels.append(label)
                    elements = [
                        {"text": label, "role": "button", "x": 0, "y": 0}
                        for label in labels
                    ]
                    return json.dumps(
                        {
                            "screen_summary": text[:1200],
                            "elements": elements,
                            "visible_goal_state": "unknown",
                            "confidence": 0.8 if labels else 0.55,
                        },
                        ensure_ascii=False,
                    )
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(2)
    raise RuntimeError(f"VLM Space request failed: {last_error}")


app_v3.vision_space = vision_space
app = app_v3.app
