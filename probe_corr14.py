import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
text = "what is the difference between correlation and causation?"
normalized = e._normalize_text(text)
print('normalized:', repr(normalized))
print('is_conv:', e._is_conversational_or_educational(normalized))
