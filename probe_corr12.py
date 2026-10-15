import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
from agents.agent_registry import AgentRegistry
from agents.agent_discovery import AgentDiscovery
from benchmark.runner import BenchmarkRunner

text = "What's the difference between correlation and causation?"

# Use BenchmarkRunner FIRST
r = BenchmarkRunner()
d1 = r._engine.decide(text)
print('runner engine first:', d1.get('level'), d1.get('mode'))

# Then a fresh engine
discovery = AgentDiscovery()
registry = AgentRegistry()
for agent in discovery.discover():
    registry.register(agent)
e = WorkflowDecisionEngine(registry=registry, context=None, conversation=None, memory=None, ai_engine=None)
d2 = e.decide(text)
print('fresh engine second:', d2.get('level'), d2.get('mode'))
