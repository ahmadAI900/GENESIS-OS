import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
for q in ["search this PDF for climate", "find the section in this document", "open this file", "search for python tutorials", "find the PDF I worked on"]:
    d = e.decide(q)
    print(repr(q), '-> L' + str(d.get('level')) + '/' + str(d.get('mode')) + ' intent=' + str(d.get('intent')))
