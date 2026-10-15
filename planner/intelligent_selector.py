"""DEPRECATED: superseded by genesis_os/capability_resolver.py + agents/workflow_decision.py control plane. Kept for backward-compat tests only. Do NOT use for new code."""
import warnings


class IntelligentTaskSelector:
    def __init__(self):
        warnings.warn("planner.intelligent_selector.IntelligentTaskSelector is deprecated", DeprecationWarning, stacklevel=2)

    def create_plan(self, task):

        task_lower = task.lower()

        steps = []

        # ==========================================
        # RESEARCH
        # ==========================================

        research_keywords = [
            "research",
            "investigate",
            "find information",
            "learn about",
            "analyze information"
        ]

        if any(
            keyword in task_lower
            for keyword in research_keywords
        ):
            steps.append({
                "agent": "Research Agent",
                "action": f"Research and gather reliable information about: {task}",
                "reason": "Task requires information gathering."
            })

        # ==========================================
        # CODING
        # ==========================================

        coding_keywords = [
            "code",
            "coding",
            "python",
            "program",
            "debug",
            "software",
            "developer",
            "development",
            "refactor",
            "implement"
        ]

        if any(
            keyword in task_lower
            for keyword in coding_keywords
        ):
            steps.append({
                "agent": "Coding Agent",
                "action": f"Analyze and work on the software task: {task}",
                "reason": "Task requires software development."
            })

        # ==========================================
        # STUDY
        # ==========================================

        study_keywords = [
            "study",
            "learn",
            "explain",
            "teach",
            "lesson",
            "exam",
            "quiz"
        ]

        if any(
            keyword in task_lower
            for keyword in study_keywords
        ):
            steps.append({
                "agent": "Study Agent",
                "action": f"Explain and teach the topic: {task}",
                "reason": "Task requires educational assistance."
            })

        # ==========================================
        # INTERNET
        # ==========================================

        internet_keywords = [
            "search online",
            "browse",
            "internet",
            "website",
            "web",
            "latest",
            "current"
        ]

        if any(
            keyword in task_lower
            for keyword in internet_keywords
        ):
            steps.append({
                "agent": "Internet Agent",
                "action": f"Search the internet for current information about: {task}",
                "reason": "Task requires internet access."
            })

        # ==========================================
        # TESTING
        # ==========================================

        testing_keywords = [
            "test",
            "testing",
            "unit test",
            "integration test"
        ]

        if any(
            keyword in task_lower
            for keyword in testing_keywords
        ):
            steps.append({
                "agent": "Coding Agent",
                "action": f"Create or analyze tests for: {task}",
                "reason": "Task requires software testing."
            })

        # ==========================================
        # SECURITY
        # ==========================================

        security_keywords = [
            "security",
            "secure",
            "vulnerability",
            "vulnerabilities",
            "cybersecurity"
        ]

        if any(
            keyword in task_lower
            for keyword in security_keywords
        ):
            steps.append({
                "agent": "Coding Agent",
                "action": f"Perform security analysis for: {task}",
                "reason": "Task requires security analysis."
            })

        # ==========================================
        # FALLBACK
        # ==========================================

        if not steps:
            steps.append({
                "agent": "General Agent",
                "action": f"Analyze the user's task: {task}",
                "reason": "No specialized capability detected."
            })

        # ==========================================
        # ADD STEP NUMBERS
        # ==========================================

        for index, step in enumerate(steps, start=1):
            step["step"] = index

        return {
            "task": task,
            "steps": steps,
            "agent_count": len(steps)
        }