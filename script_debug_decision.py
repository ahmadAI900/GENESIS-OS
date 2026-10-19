from agents.workflow_decision import WorkflowDecisionEngine
import re

engine = WorkflowDecisionEngine()
result = engine.decide('open Chrome')
print('Level:', result.get('level'))
print('Intent:', result.get('intent'))
print('Mode:', result.get('mode'))
print()

result2 = engine.decide('Research laptops and open Chrome')
print('Full Level:', result2.get('level'))
print('Full Intent:', result2.get('intent'))

parts = re.split(r'\s+(?:and|then|,)\s+', 'Research laptops and open Chrome')
for part in parts:
    r = engine.decide(part.strip())
    print('Part:', part.strip(), '-> Level:', r.get('level'), 'Intent:', r.get('intent'))