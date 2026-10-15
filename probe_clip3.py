import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
for q in ["what's in the clipboard", "what is in the clipboard", "paste from clipboard"]:
    d = e.decide(q)
    print(repr(q), '-> L' + str(d.get('level')) + '/' + str(d.get('mode')) + ' intent=' + str(d.get('intent')))
