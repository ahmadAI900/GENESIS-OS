import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
from agents.agent_registry import AgentRegistry
from agents.agent_discovery import AgentDiscovery
discovery = AgentDiscovery()
registry = AgentRegistry()
for agent in discovery.discover():
    registry.register(agent)

# Test both configurations
e_with_registry = WorkflowDecisionEngine(registry=registry, context=None, conversation=None, memory=None, ai_engine=None)
text = "What's the difference between correlation and causation?"
d1 = e_with_registry.decide(text)
print('with registry:', d1.get('level'), d1.get('mode'), 'reason:', d1.get('reason')[:100])
# Direct check
import importlib
importlib.reload(WorkflowDecisionEngine.__module__)
from agents.workflow_decision import WorkflowDecisionEngine as E2
e2 = E2(registry=registry, context=None, conversation=None, memory=None, ai_engine=None)
d2 = e2.decide(text)
print('reloaded with registry:', d2.get('level'), d2.get('mode'))
