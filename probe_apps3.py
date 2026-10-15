import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
for q in ['open Command Prompt', 'open please Command Prompt', 'launch please Command Prompt', 'start please Command Prompt', 'open please File Explorer', 'open chrome', 'open Chrome']:
    d = e.decide(q)
    sys.stdout.write(repr(q).ljust(35) + ' -> application: ' + str(d.get('application')) + ' target: ' + str(d.get('target')) + '\n')
    sys.stdout.flush()
