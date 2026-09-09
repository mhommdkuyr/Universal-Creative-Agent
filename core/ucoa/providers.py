from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path


@dataclass
class DisabledVisionProvider:
    name: str = "disabled"

    def analyze(self, prompt: str, *, images=None, video=None) -> dict[str, Any]:
        return {"status": "unavailable", "reason": "No VLM provider configured"}


def _data_url(path: str) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


@dataclass
class OpenAICompatibleVisionProvider:
    base_url: str = os.getenv("UCOA_VLM_BASE_URL", "")
    api_key: str = os.getenv("UCOA_VLM_API_KEY", "")
    model: str = os.getenv("UCOA_VLM_MODEL", "")
    timeout_s: int = int(os.getenv("UCOA_VLM_TIMEOUT_S", "120"))
    name: str = "openai-compatible-vlm"

    def _endpoint(self) -> str:
        root = self.base_url.rstrip("/")
        return root if root.endswith("/chat/completions") else root + "/chat/completions"

    def analyze(self, prompt: str, *, images=None, video=None) -> dict[str, Any]:
        if not self.base_url or not self.model:
            return {"status": "unavailable", "reason": "UCOA_VLM_BASE_URL/UCOA_VLM_MODEL not configured"}
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images or []:
            try:
                if Path(str(image)).exists():
                    content.append({"type": "image_url", "image_url": {"url": _data_url(str(image))}})
                elif str(image).startswith(("data:", "http://", "https://")):
                    content.append({"type": "image_url", "image_url": {"url": str(image)}})
            except OSError:
                continue
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self._endpoint(), data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
            result = json.loads(raw)
            choices = result.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            return {
                "status": "ok",
                "provider": self.name,
                "model": self.model,
                "content": message.get("content", ""),
                "raw": result,
                "video_reference": video,
            }
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            return {"status": "error", "provider": self.name, "model": self.model, "error": str(exc)}
