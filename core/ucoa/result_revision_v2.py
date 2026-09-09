from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ResultArtifact:
    artifact_id:str; uri:str; artifact_type:str; produced_by_steps:list[str]=field(default_factory=list); metadata:dict[str,Any]=field(default_factory=dict)

@dataclass
class RevisionRequest:
    result_id:str; instruction:str; target_artifact_id:str|None=None; target_step_id:str|None=None

class RevisionPlanner:
    def locate(self, request:RevisionRequest, artifacts:list[ResultArtifact])->ResultArtifact|None:
        if request.target_artifact_id:
            return next((a for a in artifacts if a.artifact_id==request.target_artifact_id),None)
        text=request.instruction.lower()
        for a in artifacts:
            if any(k in text for k in a.metadata.get('keywords',[])): return a
        return artifacts[0] if artifacts else None
    def affected_steps(self, artifact:ResultArtifact)->list[str]: return list(artifact.produced_by_steps)
