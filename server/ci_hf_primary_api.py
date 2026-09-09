from __future__ import annotations

import json
import tempfile
from PIL import Image, ImageDraw
from gradio_client import Client, handle_file

SPACE = "Qwen/Qwen3-VL-235B-A22B-Instruct-Demo"
PROMPT = "Return ONLY JSON with fields action, params, message, done, confidence. Identify the visible CONTINUE button and choose the safest action to press it."


def pairs(value):
    if not isinstance(value, list):
        return value
    return [tuple(x) if isinstance(x, list) and len(x) == 2 else x for x in value]

client = Client(SPACE, verbose=False)
print("HF_235B_API")
client.view_api(all_endpoints=True)

with tempfile.NamedTemporaryFile(suffix=".png") as f:
    image = Image.new("RGB", (360, 640), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 260, 280, 340), outline="black", width=4)
    draw.text((125, 290), "CONTINUE", fill="black")
    image.save(f.name)
    f.flush()
    history = client.predict([], handle_file(f.name), api_name="/add_file")
    print("HF_235B_ADD_FILE", repr(history))
    history = pairs(history)
    history = client.predict(history, PROMPT, api_name="/add_text")
    print("HF_235B_ADD_TEXT", repr(history))
    history = pairs(history)
    result = client.predict(history, api_name="/predict")

print("HF_235B_RESULT", json.dumps(result, ensure_ascii=False, default=str))
assert result is not None
assert "continue" in str(result).lower()
