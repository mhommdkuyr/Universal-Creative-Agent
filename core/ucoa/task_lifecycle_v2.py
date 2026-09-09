from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time

class TaskState(str, Enum):
    NEW='new'; ANALYZING='analyzing'; PLANNING='planning'; EXECUTING='executing'; RECOVERING='recovering'; WAITING_FOR_USER='waiting_for_user'; VERIFYING='verifying'; REVIEW='review'; REVISING='revising'; COMPLETED='completed'; FAILED='failed'; CANCELLED='cancelled'

class InterventionKind(str, Enum):
    SIGNUP='signup'; LOGIN='login'; VERIFICATION='verification'; SUBSCRIPTION='subscription'; PAYMENT='payment'; PERMISSION='permission'; DECISION='decision'

@dataclass
class Checkpoint:
    task_id:str; step_id:str; state:TaskState; next_action:str|None=None; snapshot:dict[str,Any]=field(default_factory=dict); created_at:float=field(default_factory=time.time)

@dataclass
class HumanIntervention:
    task_id:str; kind:InterventionKind; reason:str; required_action:str; checkpoint:Checkpoint; notification_sent:bool=False

@dataclass
class TaskRecord:
    task_id:str; state:TaskState=TaskState.NEW; current_step:str|None=None; completed_steps:list[str]=field(default_factory=list); checkpoints:list[Checkpoint]=field(default_factory=list); intervention:HumanIntervention|None=None; result_id:str|None=None; parent_result_id:str|None=None; revision_of_step:str|None=None

class TaskLifecycle:
    def __init__(self): self.tasks:dict[str,TaskRecord]={}
    def create(self,task_id:str)->TaskRecord:
        r=TaskRecord(task_id); self.tasks[task_id]=r; return r
    def checkpoint(self,task_id:str,step_id:str,next_action:str|None,snapshot:dict[str,Any]|None=None)->Checkpoint:
        r=self.tasks[task_id]; cp=Checkpoint(task_id,step_id,r.state,next_action,snapshot or {}); r.checkpoints.append(cp); return cp
    def require_human(self,task_id:str,kind:InterventionKind,reason:str,required_action:str,checkpoint:Checkpoint)->HumanIntervention:
        r=self.tasks[task_id]; h=HumanIntervention(task_id,kind,reason,required_action,checkpoint); r.intervention=h; r.state=TaskState.WAITING_FOR_USER; return h
    def resume(self,task_id:str)->TaskRecord:
        r=self.tasks[task_id]
        if not r.intervention: return r
        r.state=TaskState.EXECUTING; r.current_step=r.intervention.checkpoint.step_id; r.intervention=None; return r
    def begin_revision(self,task_id:str,result_id:str,step_id:str)->TaskRecord:
        r=self.tasks[task_id]; r.parent_result_id=result_id; r.revision_of_step=step_id; r.state=TaskState.REVISING; return r
    def complete(self,task_id:str,result_id:str)->TaskRecord:
        r=self.tasks[task_id]; r.result_id=result_id; r.state=TaskState.COMPLETED; return r
