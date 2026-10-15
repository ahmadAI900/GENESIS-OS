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

for q in [
    'open my downloads and find the latest PDF',
    'open my documents and open report.docx',
    'open my downloads, find the latest PDF, and copy it to my documents',
    'open my downloads and open the latest PDF',
    'open Word and open my essay.docx',
    'open my downloads',
    'Define machine learning.',
    'open chrome',
    'research and development',
    'What is the difference between correlation and causation?',
]:
    d = e.decide(q)
    sys.stdout.write(str(q).ljust(60) + ' -> L' + str(d.get('level')) + '/' + str(d.get('mode')) + ' intent=' + str(d.get('intent')) + ' compound=' + str(d.get('parameters', {}).get('is_compound')) + '\n')
    sys.stdout.flush()
