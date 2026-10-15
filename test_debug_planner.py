from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.unified_executor import MixedWorkflowPlanner, AgentCapabilityMapper
from agents.agent_registry import AgentRegistry
from agents.base_agent import BaseAgent
import re

class MockResearchAgent(BaseAgent):
    def __init__(self):
        super().__init__("Research Agent", "Researches topics", ["research"])

    def run(self, task):
        return {"findings": "Research results for " + task}

    def can_handle(self, task):
        task_lower = task.lower()
        return any(kw in task_lower for kw in ["research", "investigate", "find information"])

registry = AgentRegistry()
registry.register(MockResearchAgent())

decision_engine = WorkflowDecisionEngine()
context_resolver = None
mapper = AgentCapabilityMapper(registry)

# Debug the decision engine on each part
objective = "Research laptops and open Chrome"
parts = re.split(r'\s+(?:and|then|,)\s+', objective)
for part in parts:
    r = decision_engine.decide(part.strip())
    print(f'Part: "{part.strip()}" -> Level: {r.get("level")}, Intent: {r.get("intent")}, Mode: {r.get("mode")}')

# Now test the full planner
planner = MixedWorkflowPlanner(mapper, decision_engine, context_resolver)

# Manually trace through the plan method
required_agents = mapper.identify_required_agents(objective)
print('Required agents:', required_agents)

os_decision = decision_engine.decide(objective)
has_os_intent = os_decision.get("level") == 3
print(f'Full decision: level={os_decision.get("level")}, intent={os_decision.get("intent")}, has_os_intent={has_os_intent}')

if not has_os_intent:
    for part in parts:
        part_decision = decision_engine.decide(part.strip())
        print(f'Checking part: "{part.strip()}" -> level={part_decision.get("level")}')
        if part_decision.get("level") == 3:
            has_os_intent = True
            os_decision = part_decision
            print(f'  -> Found OS intent in part: {part_decision.get("intent")}')
            break

print(f'Final has_os_intent: {has_os_intent}')
if has_os_intent:
    print(f'OS decision: {os_decision.get("intent")}, target: {os_decision.get("target")}')

plan = planner.plan(objective)
print('Agent tasks:', [(t.agent_name, t.step_id) for t in plan.agent_tasks])
print('OS steps:', len(plan.os_steps))
for step in plan.os_steps:
    print(f'  Step: {step.step_id}, Op: {step.action_plan.operation}, Target: {step.action_plan.target}')