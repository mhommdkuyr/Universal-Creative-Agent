from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List

@dataclass
class RevisionPlan:
    instruction:str
    target_steps:List[int]
    reuse_artifacts:bool=True
    estimated_new_steps:int=0
    reason:str=''

class ResultRevisionPlanner:
    """Maps a user edit request to existing task steps so the whole task is not recreated."""
    KEYWORDS={
        'text':[2,4], 'نص':[2,4], 'لون':[3,4], 'color':[3,4], 'صوت':[5], 'audio':[5],
        'موسيقى':[5], 'سرعة':[3], 'speed':[3], 'قص':[1], 'trim':[1], 'انتقال':[4],
        'transition':[4], 'تصدير':[9], 'export':[9], 'صورة':[2,3], 'فيديو':[1,2,3,4],
    }
    def plan(self,instruction:str,existing_steps:int)->RevisionPlan:
        t=(instruction or '').lower(); targets=set()
        for key,steps in self.KEYWORDS.items():
            if key in t: targets.update(s for s in steps if s<existing_steps)
        if not targets: targets={max(0,existing_steps-1)}
        return RevisionPlan(instruction,sorted(targets),True,len(targets),'إعادة استخدام المشروع والموارد وتعديل الخطوات المتأثرة فقط')
