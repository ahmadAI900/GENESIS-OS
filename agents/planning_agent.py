from agents.base_agent import BaseAgent
from ai.ai_engine import AIEngine
from datetime import datetime


class PlanningAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Planning Agent",
            description=(
                "Breaks complex goals into actionable steps, "
                "creates plans, schedules work, and coordinates tasks."
            ),
            capabilities=[
                "planning",
                "task_planning",
                "goal_planning",
                "project_planning",
                "workflow_planning",
                "task_breakdown",
                "prioritization"
            ]
        )

        self.ai = ai_engine or AIEngine()

    # ==========================================
    # CAPABILITY DETECTION
    # ==========================================

    def can_handle(self, task):

        keywords = [
            "plan",
            "planning",
            "create a plan",
            "project plan",
            "roadmap",
            "schedule",
            "organize",
            "tasks",
            "break down",
            "steps",
            "workflow",
            "goal",
            "prioritize",
            "strategy",
            "timeline estimation",
            "step-by-step plan"
        ]

        task = task.lower()

        return any(
            keyword in task
            for keyword in keywords
        )

    # ==========================================
    # MAIN PLANNING ENGINE
    # ==========================================

    def run(self, task, context=None):

        print(
            f"[Planning Agent] Planning: {task}"
        )

        context_information = ""

        if context:

            previous_results = (
                context.get_results()
            )

            if previous_results:

                context_information = """
Previous agent results are available in
Genesis shared context.

Use relevant previous results when they
help create a better plan.
"""

        prompt = f"""
You are Genesis Planning Agent.

The user requested:

{task}

{context_information}

Your job is to transform goals and complex
tasks into clear, practical execution plans.

Possible operations include:

- project planning
- task breakdown
- goal planning
- roadmap creation
- workflow design
- prioritization
- scheduling
- dependency identification
- milestone planning

When appropriate structure the response as:

1. Objective
2. Desired Outcome
3. Major Phases
4. Tasks
5. Task Dependencies
6. Priorities
7. Milestones
8. Risks
9. Recommended Execution Order
10. Next Action

Rules:

- Do not invent requirements.
- Clearly identify assumptions.
- Break large goals into manageable tasks.
- Identify dependencies between tasks.
- Prioritize tasks logically.
- Keep the plan practical and executable.
"""

        response = self.ai.generate_response(
            prompt
        )

        # ==========================================
        # LEVEL 2.5 — REAL PLAN ARTIFACT
        #
        # Every plan is saved as a markdown file so the user
        # keeps an executable document, not just chat text.
        # ==========================================

        tool_metadata = {"operation": "planning"}

        try:
            from agents.agent_tools import AgentWorkspace

            if not hasattr(self, "workspace"):
                self.workspace = AgentWorkspace()

            saved = self.workspace.save_text_artifact(
                kind="Plans",
                base_name=f"plan-{task}",
                content=(
                    f"# Genesis Plan — {task}\n\n"
                    f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n\n"
                    + response
                    + "\n"
                ),
                extension=".md",
            )

            if saved.get("success"):
                response = (
                    response
                    + f"\n\n---\n📋 **Plan saved:** `{saved['path']}`"
                )

                tool_metadata["artifact_saved"] = True
                tool_metadata["artifact_path"] = saved["path"]

        except Exception as tool_error:
            tool_metadata["tool_error"] = str(tool_error)

        return self.create_result(
            task=task,
            response=response,
            success=True,
            metadata={
                **tool_metadata
            }
        )

    # ==========================================
    # DIRECT INTERFACE
    # ==========================================

    def plan(self, task):

        return self.run(task)

    # ==========================================
    # UNIVERSAL AGENT INTERFACE
    # ==========================================

    def execute(self, task, context=None):

        self.start()

        try:

            result = self.run(
                task,
                context
            )

            if context:

                context.add_result(
                    self.name,
                    result
                )

            return result

        finally:

            self.stop()