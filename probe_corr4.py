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
print('conversational:', e._is_conversational_or_educational(text))
# Check what agent matches
agents = e._detect_multi_agents(text)
single = e._detect_single_agent(text)
print('multi:', agents, 'single:', single)
# What about the decision flow
os_d = e._detect_os_intent(text)
print('os decision:', os_d.get('level'), os_d.get('mode'))
