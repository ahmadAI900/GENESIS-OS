"""DEPRECATED: superseded by genesis_os/capability_resolver.py + agents/workflow_decision.py control plane. Kept for backward-compat tests only. Do NOT use for new code."""
import warnings


class TaskPlanner:
    def __init__(self):
        warnings.warn("planner.task_planner.TaskPlanner is deprecated", DeprecationWarning, stacklevel=2)

    def create_plan(self, task):

        task_lower = task.lower()

        steps = []

        if "research" in task_lower:
            steps.append({
                "step": 1,
                "agent": "Research Agent",
                "action": "Research the requested topic"
            })

        if any(word in task_lower for word in [
            "code",
            "coding",
            "debug",
            "review",
            "refactor",
            "python"
        ]):
            steps.append({
                "step": len(steps) + 1,
                "agent": "Coding Agent",
                "action": "Analyze and work on the provided code"
            })

        if "test" in task_lower:
            steps.append({
                "step": len(steps) + 1,
                "agent": "Coding Agent",
                "action": "Generate tests for the code"
            })

        if "security" in task_lower:
            steps.append({
                "step": len(steps) + 1,
                "agent": "Coding Agent",
                "action": "Perform security analysis"
            })

        if not steps:
            steps.append({
                "step": 1,
                "agent": "Unknown",
                "action": "No specialized workflow identified"
            })

        return {
            "task": task,
            "steps": steps
        }