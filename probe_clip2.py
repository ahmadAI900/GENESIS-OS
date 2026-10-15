import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine, _CLIPBOARD_READ_RE
e = WorkflowDecisionEngine()
text = "what's in the clipboard"
normalized = e._normalize_text(text)
print('normalized:', repr(normalized))
print('match:', _CLIPBOARD_READ_RE.match(normalized))
