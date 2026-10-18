from planner.task_planner import TaskPlanner
from planner.intelligent_selector import IntelligentTaskSelector
from agents.multi_agent_executor import MultiAgentExecutor


class AgentOrchestrator:

    def __init__(self, registry, context):

        self.registry = registry
        self.context = context

        self.planner = TaskPlanner()
        self.selector = IntelligentTaskSelector()

        self.executor = MultiAgentExecutor(
            registry,
            context
        )

    # ==========================================
    # CREATE EXECUTION PLAN
    # ==========================================

    def create_plan(self, task):

        print()
        print("======================================")
        print("     GENESIS AGENT ORCHESTRATOR")
        print("======================================")

        print()
        print("[Orchestrator] Creating task plan...")

        plan = self.planner.create_plan(task)

        print(
            f"[Orchestrator] Planner created "
            f"{len(plan['steps'])} step(s)."
        )

        return plan

    # ==========================================
    # CREATE INTELLIGENT PLAN
    # ==========================================

    def create_intelligent_plan(self, task):

        print()
        print(
            "[Orchestrator] Creating intelligent "
            "agent plan..."
        )

        plan = self.selector.create_plan(task)

        # Item 12C (R5): count the STEPS, not the dict.
        #
        # This logged len(plan). IntelligentTaskSelector.create_plan
        # returns {'task': ..., 'steps': [...], 'agent_count': N} --
        # three keys -- so len(plan) was 3 for EVERY plan regardless of
        # how many steps it held. A 1-step plan and a 7-step plan both
        # reported "created 3 step(s)".
        #
        # create_plan() above already did this correctly with
        # len(plan['steps']), which is what made the omission obvious.
        print(
            f"[Orchestrator] Intelligent selector "
            f"created {len(plan['steps'])} step(s)."
        )

        return plan

    # ==========================================
    # CONVERT PLAN TO EXECUTABLE TASKS
    # ==========================================

    def prepare_tasks(self, plan):

        tasks = []

        for step in plan["steps"]:

            action = step.get(
                "action",
                ""
            )

            agent_name = step.get(
                "agent"
            )

            if not action:
                continue

            if agent_name:

                tasks.append({
                    "task": action,
                    "agent": agent_name
                })

            else:

                tasks.append({
                    "task": action,
                    "agent": None
                })

        return tasks

    # ==========================================
    # EXECUTE PLAN
    # ==========================================

    def execute(self, task):

        plan = self.create_plan(task)

        executable_tasks = self.prepare_tasks(
            plan
        )

        if not executable_tasks:

            print(
                "[Orchestrator] No executable "
                "tasks found."
            )

            return {
                "task": task,
                "plan": plan,
                "results": [],
                "status": "failed"
            }

        print()
        print(
            "[Orchestrator] Sending plan "
            "to MultiAgentExecutor..."
        )

        results = self.executor.execute(
            executable_tasks
        )

        return {
            "task": task,
            "plan": plan,
            "results": results,
            "status": "completed"
        }

    def prepare_intelligent_tasks(self, plan):

        tasks = []

        for step in plan["steps"]:

            tasks.append({
                "agent": step.get("agent"),
                "action": step.get("action", "")
            })

        return tasks

    def execute_intelligent(self, task):

        plan = self.create_intelligent_plan(task)

        executable_tasks = self.prepare_intelligent_tasks(
            plan
        )

        if not executable_tasks:

            return {
                "task": task,
                "plan": plan,
                "results": [],
                "status": "failed"
            }

        print()
        print(
            "[Orchestrator] Executing intelligent "
             "multi-agent plan..."
        )

        results = self.executor.execute(
            executable_tasks
        )

        return {
            "task": task,
            "plan": plan,
            "results": results,
            "status": "completed"
        }