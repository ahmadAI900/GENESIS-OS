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
for q in ['summarize the data in this CSV', 'find correlations in this dataset', 'compare these two spreadsheets', 'what are the outliers in this data']:
    d = e.decide(q)
    print(repr(q), '-> L' + str(d.get('level')) + ' agent=' + str(d.get('agent')) + ' agents=' + str(d.get('agents')))
