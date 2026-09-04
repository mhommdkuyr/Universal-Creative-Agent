from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import os

@dataclass
class DisabledVisionProvider:
    name: str = 'disabled'
    def analyze(self, prompt: str, *, images=None, video=None) -> dict[str, Any]:
        return {'status':'unavailable','reason':'No VLM provider configured'}

@dataclass
class OpenAICompatibleVisionProvider:
    base_url: str = os.getenv('UCOA_VLM_BASE_URL','')
    api_key: str = os.getenv('UCOA_VLM_API_KEY','')
    model: str = os.getenv('UCOA_VLM_MODEL','')
    name: str = 'openai-compatible-vlm'
    def analyze(self, prompt: str, *, images=None, video=None) -> dict[str, Any]:
        if not self.base_url or not self.model:
            return {'status':'unavailable','reason':'UCOA_VLM_BASE_URL/UCOA_VLM_MODEL not configured'}
        return {'status':'configured','provider':self.name,'model':self.model,'prompt':prompt,'images':images or [],'video':video}
