import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
from agents.agent_registry import AgentRegistry
from agents.agent_discovery import AgentDiscovery
from benchmark.runner import BenchmarkRunner

text = "What's the difference between correlation and causation?"

# Create a fresh engine
discovery = AgentDiscovery()
registry = AgentRegistry()
for agent in discovery.discover():
    registry.register(agent)
e = WorkflowDecisionEngine(registry=registry, context=None, conversation=None, memory=None, ai_engine=None)
d1 = e.decide(text)
print('fresh engine:', d1.get('level'), d1.get('mode'))

# Now use BenchmarkRunner (which creates its own engine)
r = BenchmarkRunner()
d2 = r._engine.decide(text)
print('runner engine:', d2.get('level'), d2.get('mode'))

# Are they the same engine?
print('same engine:', r._engine is e)
print('runner engine class:', r._engine.__class__.__name__)
print('fresh engine class:', e.__class__.__name__)
