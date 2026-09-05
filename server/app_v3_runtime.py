"""Runtime compatibility shim for the public Qwen3-VL Gradio Space."""
from __future__ import annotations

import base64
import tempfile

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


def vision_space(prompt: str, image: str) -> str:
    from gradio_client import Client, handle_file

    raw = base64.b64decode(image)
    with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
        f.write(raw)
        f.flush()
        client = Client(app_v3.VISION_SPACE, verbose=False)
        return str(client.predict(
            {"text": prompt, "files": [handle_file(f.name)]},
            [],
            api_name="/chat",
        ))


app_v3.vision_space = vision_space
app = app_v3.app
