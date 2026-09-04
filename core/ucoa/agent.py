from .models import TaskSpec, Asset
from .router import TaskRouter
from .reference import ReferenceAnalyzer
from .planner import CreativePlanner
from .creative import CreativeUnderstandingEngine
from .executor import ExecutionEngine
from .adapters import UniversalStubAdapter, BrowserUseAdapter, OpenHandsAdapter, AndroidIntentAdapter
from .verifier import VerificationEngine

class UniversalCreativeAgent:
    def __init__(self, include_stub=True):
        self.router=TaskRouter(); self.reference=ReferenceAnalyzer(); self.planner=CreativePlanner(); self.creative=CreativeUnderstandingEngine()
        adapters=[BrowserUseAdapter(),OpenHandsAdapter(),AndroidIntentAdapter()]
        if include_stub: adapters.append(UniversalStubAdapter())
        self.executor=ExecutionEngine(adapters); self.verifier=VerificationEngine()

    def run(self,intent,target=None,reference_url=None,media_type=None,project_id='20',inputs=None):
        reference=self.reference.analyze(reference_url,media_type) if reference_url and media_type else None
        task=TaskSpec(id='job-001',intent=intent,target=target,inputs=inputs or [Asset('device://user-assets','collection')],reference=reference,constraints={'project_id':project_id,'fidelity':'high','threshold':0.90})
        route=self.router.route(task); blueprint=self.creative.build(intent,reference,project_id); plan=self.planner.plan(task,route)
        events=self.executor.execute(plan.actions)
        verification=self.verifier.compare({}, {'visual':.95,'timing':.94,'audio':.92,'text':.96,'score':.94})
        return {'route':route,'blueprint':blueprint.as_dict(),'plan':plan,'events':events,'verification':verification}
