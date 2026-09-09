from __future__ import annotations
from dataclasses import dataclass
from time import time
@dataclass
class TaskNotification:
    task_id:str; title:str; body:str; kind:str; created_at:float=time()
class NotificationCenter:
    def __init__(self): self._sent:set[tuple[str,str]]=set(); self._items:list[TaskNotification]=[]
    def notify(self,task_id:str,kind:str,title:str,body:str)->bool:
        key=(task_id,kind)
        if key in self._sent:return False
        self._sent.add(key); self._items.append(TaskNotification(task_id,title,body,kind)); return True
    def all(self): return list(self._items)
