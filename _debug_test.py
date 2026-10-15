import sys
sys.path.insert(0, '.')
from genesis import GenesisOS
from genesis_os.action_result import ActionResult

g = GenesisOS()

# Monkey-patch the WDE to log calls
orig_decide = g.workflow_decision.decide
calls = []
def logging_decide(text):
    result = orig_decide(text)
    calls.append((text, result.get('level'), result.get('intent'), result.get('target')))
    return result
g.workflow_decision.decide = logging_decide
g.objective_understanding.decision_engine = g.workflow_decision

# DO NOT call classify first - go straight to compound router
outcome = g.compound_task_router.route('open settings and turn on bluetooth')
print('is_compound:', outcome.signal.is_compound)
print('plan:', outcome.plan is not None)
print()
print('WDE calls:')
for t, level, intent, target in calls:
    print('  text=%r -> level=%s, intent=%s, target=%s' % (t, level, intent, target))
