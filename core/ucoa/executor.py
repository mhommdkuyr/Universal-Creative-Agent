from dataclasses import dataclass, field
from typing import Protocol, Any
from .models import Action

class Adapter(Protocol):
    name: str
    def supports(self, action: Action) -> bool: ...
    def execute(self, action: Action) -> Any: ...

@dataclass
class ExecutionEvent:
    action: Action
    adapter: str
    result: Any

@dataclass
class ExecutionEngine:
    adapters: list[Adapter] = field(default_factory=list)
    events: list[ExecutionEvent] = field(default_factory=list)
    def execute(self, actions: list[Action]) -> list[ExecutionEvent]:
        self.events=[]
        for action in actions:
            adapter=next((a for a in self.adapters if a.supports(action)),None)
            if adapter is None: raise RuntimeError(f'No adapter for action: {action.type}')
            self.events.append(ExecutionEvent(action,adapter.name,adapter.execute(action)))
        return self.events
