class AgentOrchestrator:

    def __init__(self, agents):
        self.agents = agents

    def list_agents(self):
        return [agent.get_info() for agent in self.agents]

    def select_agent(self, task):

        task_lower = task.lower()

        if any(word in task_lower for word in [
            "research",
            "find information",
            "investigate",
            "study the topic"
        ]):
            for agent in self.agents:
                if agent.get_info()["name"] == "Research Agent":
                    return agent

        if any(word in task_lower for word in [
            "code",
            "coding",
            "program",
            "debug",
            "python",
            "review code",
            "refactor"
        ]):
            for agent in self.agents:
                if agent.get_info()["name"] == "Coding Agent":
                    return agent

        return None

    def execute(self, task):

        print("[Orchestrator] Understanding task...")

        agent = self.select_agent(task)

        if agent is None:
            return {
                "success": False,
                "agent": None,
                "response": "I could not find a suitable Genesis agent for this task."
            }

        print(
            f"[Orchestrator] Selected: "
            f"{agent.get_info()['name']}"
        )

        result = agent.run(task)

        if result is None:
            return {
                "success": False,
                "agent": agent.get_info()["name"],
                "response": None,
                "message": "Agent returned no result.",
            }

        if isinstance(result, str) and not result.strip():
            return {
                "success": False,
                "agent": agent.get_info()["name"],
                "response": result,
                "message": "Agent returned an empty result.",
            }

        if isinstance(result, (dict, list, tuple, set)) and len(result) == 0:
            return {
                "success": False,
                "agent": agent.get_info()["name"],
                "response": result,
                "message": "Agent returned an empty result.",
            }

        return {
            "success": True,
            "agent": agent.get_info()["name"],
            "response": result
        }