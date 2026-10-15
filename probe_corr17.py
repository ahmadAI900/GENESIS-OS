import sys
sys.path.insert(0, '.')
import importlib
import agents.workflow_decision
importlib.reload(agents.workflow_decision)
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
result = e.decide("What's the difference between correlation and causation?")
print('result:', result.get('level'))
