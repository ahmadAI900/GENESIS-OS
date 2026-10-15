import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
from agents.agent_registry import AgentRegistry
from agents.agent_discovery import AgentDiscovery
discovery = AgentDiscovery()
registry = AgentRegistry()
for agent in discovery.discover():
    registry.register(agent)
e = WorkflowDecisionEngine(registry=registry)
text = "what is the difference between correlation and causation"
print('comp signal:', e._detect_compound_l3_signal(text))
print('os:', e._detect_os_intent(text))
print('conversational:', e._is_conversational_or_educational(text))
d = e.decide(text)
print('decision level:', d.get('level'), 'mode:', d.get('mode'), 'reason:', d.get('reason'))
