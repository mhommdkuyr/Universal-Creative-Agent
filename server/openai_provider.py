"""OpenAI Responses API adapter used as UCOA's primary reasoning/vision provider."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol").strip()
MAX_OUTPUT = max(256, int(os.getenv("UCOA_OPENAI_MAX_OUTPUT_TOKENS", "2048")))
TIMEOUT = max(10, int(os.getenv("UCOA_OPENAI_TIMEOUT", "90")))


def configured() -> bool:
    return bool(API_KEY and MODEL)


def _request(payload: dict[str, Any]) -> str:
    if not configured():
        raise RuntimeError("OpenAI provider not configured")
    req = urllib.request.Request(
        f"{BASE_URL}/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1200]
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"OpenAI request failed: {exc}") from exc

    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    chunks: list[str] = []
    for item in body.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                chunks.append(str(content.get("text", "")))
    text = "\n".join(chunks).strip()
    if not text:
        raise RuntimeError("OpenAI returned an empty response")
    return text


def reasoning(system: str, user: str) -> str:
    return _request(
        {
            "model": MODEL,
            "instructions": system,
            "input": user,
            "reasoning": {"effort": os.getenv("UCOA_OPENAI_REASONING_EFFORT", "high")},
            "max_output_tokens": MAX_OUTPUT,
        }
    )


def visual(system: str, user: str, image_base64: str) -> str:
    return _request(
        {
            "model": MODEL,
            "instructions": system,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user},
                        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_base64}"},
                    ],
                }
            ],
            "reasoning": {"effort": os.getenv("UCOA_OPENAI_VISION_REASONING_EFFORT", "medium")},
            "max_output_tokens": MAX_OUTPUT,
        }
    )
