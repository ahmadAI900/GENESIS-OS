class AgentChain:

    def __init__(self, context):
        self.context = context
        self.steps = []

    def add_step(self, agent_name, task):
        self.steps.append({
            "agent": agent_name,
            "task": task
        })

    def get_steps(self):
        return self.steps

    def get_previous_results(self):
        return self.context.get_results()

    def execute_step(self, agent_name, result):

        print(
            f"[Agent Chain] "
            f"{agent_name} completed a step."
        )

        self.context.add_result(
            agent_name,
            result
        )

        return result

    def get_latest_result(self):

        results = self.context.get_results()

        if not results:
            return None

        return results[-1]

    def build_agent_input(self, task):

        previous_results = self.context.get_results()

        if not previous_results:

            return task

        context_text = "\n\n".join(
            [
                f"Agent: {item['agent']}\n"
                f"Result: {item['result']}"
                for item in previous_results
            ]
        )

        return f"""
Original Task:

{self.context.task}

Previous Agent Results:

{context_text}

Your Assigned Task:

{task}

Use the previous agent results as context.
Do not ignore relevant information from them.
"""

    def status(self):

        return {
            "task": self.context.task,
            "steps": self.steps,
            "results": self.context.get_results()
        }