import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
text = """search this PDF for 'climate'"""
d = e.decide(text)
print('level:', d.get('level'), 'intent:', d.get('intent'))
