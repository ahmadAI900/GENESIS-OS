import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
d = e.decide("What's the difference between correlation and causation?")
print('level:', d.get('level'), 'mode:', d.get('mode'), 'intent:', d.get('intent'))
