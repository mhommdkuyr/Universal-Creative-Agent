from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List

class PermissionMode(str, Enum):
    FULL='full'; ASK_EVERY_TIME='ask_every_time'; SAFE='safe'

SAFE_ACTIONS={'observe','open_app_by_name','open_url','back','home','wait'}
SENSITIVE_ACTIONS={'share_attachment','type_into_any','tap','long_press','swipe'}

@dataclass
class AppPermissionProfile:
    package_name:str
    app_label:str
    mode:PermissionMode=PermissionMode.SAFE
    allowed_actions:List[str]=field(default_factory=list)
    denied_actions:List[str]=field(default_factory=list)

    def allows(self,action:str,explicit_confirmation:bool=False)->bool:
        if action in self.denied_actions:return False
        if self.mode==PermissionMode.FULL:return True
        if self.mode==PermissionMode.SAFE:return action in SAFE_ACTIONS or action in self.allowed_actions
        return explicit_confirmation
    def jsonable(self)->Dict: return asdict(self)

class PermissionLibrary:
    def __init__(self): self._profiles:Dict[str,AppPermissionProfile]={}
    def get(self,package_name,app_label=None):
        if package_name not in self._profiles:self._profiles[package_name]=AppPermissionProfile(package_name,app_label or package_name)
        elif app_label:self._profiles[package_name].app_label=app_label
        return self._profiles[package_name]
    def set_mode(self,package_name,mode,app_label=None):
        p=self.get(package_name,app_label); p.mode=PermissionMode(mode); return p
    def check(self,package_name,action,app_label=None,explicit_confirmation=False): return self.get(package_name,app_label).allows(action,explicit_confirmation)
    def export(self): return {k:v.jsonable() for k,v in self._profiles.items()}
