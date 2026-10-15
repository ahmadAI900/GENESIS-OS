import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
text = "What's the difference between correlation and causation?"
d = e.decide(text)
print('level:', d.get('level'), 'mode:', d.get('mode'), 'reason:', d.get('reason'))
