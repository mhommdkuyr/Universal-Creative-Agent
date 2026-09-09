from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional
import time, uuid

class TaskState(str, Enum):
    NEW='new'; ANALYZING='analyzing'; PLANNING='planning'; EXECUTING='executing'; RECOVERING='recovering'
    WAITING_FOR_USER='waiting_for_user'; WAITING_FOR_SIGNUP='waiting_for_signup'; WAITING_FOR_VERIFICATION='waiting_for_verification'
    WAITING_FOR_SUBSCRIPTION='waiting_for_subscription'; WAITING_FOR_CREDITS='waiting_for_credits'; WAITING_FOR_BLOCKING_UI='waiting_for_blocking_ui'
    VERIFYING='verifying'; REPAIRING='repairing'; READY_FOR_REVIEW='ready_for_review'; REVISING='revising'; COMPLETED='completed'; CANCELLED='cancelled'; FAILED='failed'

class HumanAction(str, Enum):
    NONE='none'; SIGN_UP='sign_up'; ENTER_VERIFICATION_CODE='enter_verification_code'; COMPLETE_SUBSCRIPTION='complete_subscription'; CHOOSE_DECISION='choose_decision'; GRANT_PERMISSION='grant_permission'

@dataclass
class Checkpoint:
    id:str; task_id:str; step_index:int; state:str; next_action:Optional[Dict[str,Any]]=None
    completed_steps:List[int]=field(default_factory=list); foreground_package:Optional[str]=None; ui_snapshot:Optional[str]=None
    artifact_ids:List[str]=field(default_factory=list); created_at:float=field(default_factory=time.time)

@dataclass
class HumanRequest:
    id:str; task_id:str; state:str; reason:str; action:str; title:str; message:str; resume_from_checkpoint:Optional[str]
    created_at:float=field(default_factory=time.time); resolved_at:Optional[float]=None; resolution:Optional[Dict[str,Any]]=None

@dataclass
class TaskSnapshot:
    task_id:str; state:str; current_step:int; checkpoint_id:Optional[str]=None; human_request_id:Optional[str]=None
    completed_steps:List[int]=field(default_factory=list); result_artifact_ids:List[str]=field(default_factory=list)
    revision_of:Optional[str]=None; revision_target_steps:List[int]=field(default_factory=list); revision_instruction:Optional[str]=None
    updated_at:float=field(default_factory=time.time)
    def jsonable(self): return asdict(self)

class TaskLifecycle:
    HUMAN_STATES={TaskState.WAITING_FOR_USER,TaskState.WAITING_FOR_SIGNUP,TaskState.WAITING_FOR_VERIFICATION,TaskState.WAITING_FOR_SUBSCRIPTION,TaskState.WAITING_FOR_CREDITS}
    def __init__(self,task_id=None):
        self.snapshot=TaskSnapshot(task_id or uuid.uuid4().hex,TaskState.NEW.value,0); self.checkpoints={}; self.human_requests={}
    def transition(self,state,step=None):
        self.snapshot.state=state.value
        if step is not None:self.snapshot.current_step=max(0,step)
        self.snapshot.updated_at=time.time(); return self.snapshot
    def checkpoint(self,state=None,**kw):
        cp=Checkpoint(uuid.uuid4().hex,self.snapshot.task_id,self.snapshot.current_step,(state or TaskState(self.snapshot.state)).value,completed_steps=list(self.snapshot.completed_steps),**kw)
        self.checkpoints[cp.id]=cp; self.snapshot.checkpoint_id=cp.id; self.snapshot.updated_at=time.time(); return cp
    def wait_for_human(self,*,reason,action,title,message,state,**kw):
        if state not in self.HUMAN_STATES: raise ValueError('invalid human wait state')
        cp=self.checkpoint(state,**kw); req=HumanRequest(uuid.uuid4().hex,self.snapshot.task_id,state.value,reason,action.value,title,message,cp.id)
        self.human_requests[req.id]=req; self.snapshot.human_request_id=req.id; self.transition(state); return req
    def resolve_human(self,request_id,resolution):
        req=self.human_requests[request_id]; req.resolution=dict(resolution); req.resolved_at=time.time(); self.snapshot.human_request_id=None
        cp=self.checkpoints.get(req.resume_from_checkpoint)
        if cp: self.snapshot.current_step=cp.step_index; self.snapshot.completed_steps=list(cp.completed_steps); self.snapshot.checkpoint_id=cp.id
        return self.transition(TaskState.EXECUTING)
    def complete(self,artifact_ids): self.snapshot.result_artifact_ids=list(artifact_ids); return self.transition(TaskState.READY_FOR_REVIEW)
    def revise(self,instruction,target_steps):
        self.snapshot.revision_instruction=instruction; self.snapshot.revision_target_steps=sorted(set(int(x) for x in target_steps if int(x)>=0)); self.snapshot.revision_of=self.snapshot.task_id
        return self.transition(TaskState.REVISING)
    def cancel(self): return self.transition(TaskState.CANCELLED)
    def fail(self,terminal=True): return self.transition(TaskState.FAILED if terminal else TaskState.RECOVERING)
