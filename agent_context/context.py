class AgentContext:

    def __init__(self):
        self.results = []

    def add_result(self, agent_name, result):

        self.results.append({
            "agent": agent_name,
            "result": result
        })

        print(
            f"[Agent Context] Result stored from: {agent_name}"
        )

    def get_results(self):
        return self.results

    def get_latest_result(self):

        if not self.results:
            return None

        return self.results[-1]

    def get_agent_result(self, agent_name):

        for item in reversed(self.results):

            if item.get("agent") == agent_name:
                return item.get("result")

        return None

    def has_results(self):
        return len(self.results) > 0

    def clear(self):

        self.results.clear()

        print(
            "[Agent Context] Context cleared."
        )