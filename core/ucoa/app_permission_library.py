from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

class PermissionMode(str,Enum): FULL='full'; ASK_EACH='ask_each'; SAFE='safe'
@dataclass
class AppPermissionPolicy:
    package_name:str; mode:PermissionMode=PermissionMode.SAFE; allowed:set[str]=field(default_factory=set); denied:set[str]=field(default_factory=set)
class AppPermissionLibrary:
    def __init__(self): self._items:dict[str,AppPermissionPolicy]={}
    def get(self,package_name:str)->AppPermissionPolicy: return self._items.setdefault(package_name,AppPermissionPolicy(package_name))
    def set_mode(self,package_name:str,mode:PermissionMode): self.get(package_name).mode=mode
    def is_allowed(self,package_name:str,action:str)->bool:
        p=self.get(package_name)
        if action in p.denied:return False
        if p.mode is PermissionMode.FULL:return True
        if p.mode is PermissionMode.SAFE:return action in {'open','read','search','navigate','preview'} or action in p.allowed
        return action in p.allowed
