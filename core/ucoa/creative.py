from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .models import ReferenceInsight

@dataclass
class CreativeBlueprint:
    title: str
    medium: str
    reference: str | None
    objective: str
    timeline: list[dict[str, Any]]
    style: dict[str, Any]
    audio: dict[str, Any]
    typography: dict[str, Any]
    fidelity: str = 'high'
    def as_dict(self):
        return self.__dict__.copy()

class CreativeUnderstandingEngine:
    def build(self, intent: str, reference: ReferenceInsight | None, project_id: str) -> CreativeBlueprint:
        return CreativeBlueprint(
            title=f'Reference-derived project {project_id}',
            medium=reference.media_type if reference else 'unknown',
            reference=reference.source if reference else None,
            objective=intent,
            timeline=reference.scenes if reference else [],
            style=reference.style if reference else {},
            audio=reference.audio if reference else {},
            typography={'source': 'reference-analysis-pending'},
            fidelity='high',
        )
