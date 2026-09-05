from __future__ import annotations

import json
import tempfile

from PIL import Image, ImageDraw
from gradio_client import Client, handle_file

SPACE = "Qwen/Qwen3-VL-235B-A22B-Instruct-Demo"
client = Client(SPACE, verbose=False)
# view_api() prints the discovered schema and may return None in some gradio_client versions.
print("HF_235B_API")
client.view_api(all_endpoints=True)

with tempfile.NamedTemporaryFile(suffix=".png") as f:
    image = Image.new("RGB", (360, 640), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 260, 280, 340), outline="black", width=4)
    draw.text((125, 290), "CONTINUE", fill="black")
    image.save(f.name)
    image_ref = handle_file(f.name)

    history = client.predict([], image_ref, api_name="/add_file")
    history = client.predict(
        history,
        "Return ONLY JSON with fields action, params, message, done, confidence. Identify the visible CONTINUE button and choose the safest action to press it.",
        api_name="/add_text",
    )
    result = client.predict(history, api_name="/predict")

print("HF_235B_RESULT", json.dumps(result, ensure_ascii=False, default=str))
assert result is not None
assert "continue" in str(result).lower()
