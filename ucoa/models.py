from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import json

@dataclass
class Asset:
    uri: str
    kind: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ReferenceInsight:
    source: str
    media_type: str
    duration_s: Optional[float] = None
    scenes: List[Dict[str, Any]] = field(default_factory=list)
    style: Dict[str, Any] = field(default_factory=dict)
    audio: Dict[str, Any] = field(default_factory=dict)
    text: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class TaskSpec:
    id: str
    intent: str
    target: Optional[str] = None
    inputs: List[Asset] = field(default_factory=list)
    reference: Optional[ReferenceInsight] = None
    constraints: Dict[str, Any] = field(default_factory=dict)
    autonomy: str = "autonomous"

@dataclass
class Action:
    type: str
    target: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    verify: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Plan:
    task_id: str
    strategy: str
    actions: List[Action]
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class VerificationResult:
    passed: bool
    score: float
    issues: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


def to_json(obj: Any) -> str:
    return json.dumps(asdict(obj), ensure_ascii=False, indent=2)
