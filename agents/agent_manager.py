class AgentManager:

    def __init__(self):
        self.agents = []

    def register_agent(self, agent):
        self.agents.append(agent)

    def list_agents(self):
        return [agent.name for agent in self.agents]

    def find_agent(self, task):

        for agent in self.agents:

            if agent.can_handle(task):
                return agent

        return None

    def get_agent_status(self):

        return [
            agent.get_info()
            for agent in self.agents
        ]