import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_plan import ActionPlan
from genesis_os.action_executor import ActionExecutor
from benchmark.runner import _MockOSManager
e = WorkflowDecisionEngine()
for q in ["summarize this PDF", "read this document", "find the section about methodology"]:
    d = e.decide(q)
    plan = ActionPlan.from_decision(d)
    ex = ActionExecutor(_MockOSManager())
    r = ex.execute(plan)
    print(repr(q), '-> success:', r.success, 'verified:', r.verified, 'status:', r.status, 'params.anaphoric:', d.get('parameters', {}).get('anaphoric_target'))
