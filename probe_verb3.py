import sys
sys.path.insert(0, '.')
import re
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
e.decide('open Command Prompt')
case_form = e._last_case_form
print('case form:', repr(case_form))
m = re.match(
    r"^(?:please\s+)?(?:open|launch|start|"
    r"fire\s+up|spin\s+up|boot\s+up|bring\s+up|"
    r"start\s+up|pop\s+open|pop\s+up)\s+"
    r"(?:the\s+|my\s+)?(.+?)\s*[.?!]?$",
    case_form,
    re.IGNORECASE,
)
print('match:', m, 'group:', m.group(1) if m else None)
