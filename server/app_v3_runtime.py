"""Runtime compatibility shim for the public Qwen3-VL Gradio Space."""
from __future__ import annotations

import base64
import tempfile

import app_v3


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
