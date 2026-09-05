from __future__ import annotations

import json
import tempfile

from PIL import Image, ImageDraw
from gradio_client import Client, handle_file

SPACE = "Qwen/Qwen3-VL-235B-A22B-Instruct-Demo"
client = Client(SPACE, verbose=False)
api = client.view_api(all_endpoints=True)
print(api)
assert "/predict" in str(api), api

with tempfile.NamedTemporaryFile(suffix=".png") as f:
    image = Image.new("RGB", (360, 640), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 260, 280, 340), outline="black", width=4)
    draw.text((125, 290), "CONTINUE", fill="black")
    image.save(f.name)
    image_ref = handle_file(f.name)
    history = [((image_ref,), None), ("Return ONLY JSON with action, params, message, done, confidence. Identify the visible CONTINUE button and choose the safest action to press it.", None)]
    result = client.predict(history, history, api_name="/predict")

print("HF_235B_RESULT", json.dumps(result, ensure_ascii=False, default=str))
assert result is not None
