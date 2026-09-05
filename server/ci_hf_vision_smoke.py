from __future__ import annotations

import io
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from gradio_client import Client, handle_file

SPACE = "akhaliq/Qwen3-VL-2B-Instruct"
IMAGE = Path("/tmp/ucoa-vlm-smoke.png")

img = Image.new("RGB", (900, 500), "white")
d = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
except Exception:
    font = ImageFont.load_default()
d.text((70, 70), "Universal Creative Agent", fill="black", font=font)
d.rounded_rectangle((250, 260, 650, 380), radius=24, fill="#dddddd", outline="#333333", width=4)
d.text((355, 290), "CONTINUE", fill="black", font=font)
img.save(IMAGE)

client = Client(SPACE, verbose=False)
prompt = "Inspect the screenshot. Identify the main button label exactly. Do not invent anything. Reply with a short factual description."
last = ""
for attempt in range(3):
    try:
        result = client.predict(
            {"text": prompt, "files": [handle_file(str(IMAGE))]},
            [],
            api_name="/qwen_chat_fn",
        )
        last = str(result)
        print("HF_VISION_RESULT:", last)
        normalized = last.lower().replace("_", " ")
        assert "continue" in normalized, f"VLM did not identify CONTINUE: {last}"
        print("HF_VISION_SMOKE_OK")
        break
    except Exception as exc:
        print(f"vision attempt {attempt + 1} failed: {exc}")
        if attempt == 2:
            raise
        time.sleep(8)
