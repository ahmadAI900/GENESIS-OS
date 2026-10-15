import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
for q in ['open Maps', 'launch Maps', 'start Maps', 'open my downloads', 'open File Explorer', 'open Slack', 'open Teams', 'open my documents', 'open google maps']:
    d = e.decide(q)
    print(str(q).ljust(35), '-> L' + str(d.get('level')) + '/' + str(d.get('mode')) + ' intent=' + str(d.get('intent')) + ' target=' + str(d.get('target')))
