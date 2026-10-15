import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
r = BenchmarkRunner()
text = "What's the difference between correlation and causation?"
# The runner's engine
d = r._engine.decide(text)
print('runner engine:', d.get('level'), d.get('mode'), 'reason:', d.get('reason'))
# A fresh engine
from agents.workflow_decision import WorkflowDecisionEngine
from agents.agent_registry import AgentRegistry
from agents.agent_discovery import AgentDiscovery
discovery = AgentDiscovery()
registry = AgentRegistry()
for agent in discovery.discover():
    registry.register(agent)
e2 = WorkflowDecisionEngine(
    registry=registry,
    context=None,
    conversation=None,
    memory=None,
    ai_engine=None,
)
d2 = e2.decide(text)
print('fresh engine:', d2.get('level'), d2.get('mode'), 'reason:', d2.get('reason'))
