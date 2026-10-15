import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
text = """search this PDF for 'climate'"""
print('normalized:', repr(e._normalize_text(text)))
