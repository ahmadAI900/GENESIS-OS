class AgentContext:

    def __init__(self, task):
        self.task = task
        self.results = []
        self.metadata = {}

    def add_result(self, agent_name, result):
        self.results.append({
            "agent": agent_name,
            "result": result
        })

    def get_results(self):
        return self.results