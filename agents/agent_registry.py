"""Genesis OS — deterministic Level 2 agent registry."""
from __future__ import annotations
from typing import Iterable


class AgentRegistry:
    VERSION = "2.5.0"

    def __init__(self):
        self.agents = {}

    def register(self, agent):
        if agent is None or not getattr(agent, "name", None):
            raise ValueError("A valid agent with a name is required.")
        # Phase 1 contract: the agent must satisfy the Agent
        # boundary (non-empty id, capability list preserved).
        from genesis_os.contracts import Agent as AgentContract
        AgentContract.from_runtime(agent)
        self.agents[agent.name] = agent
        return agent

    def get_agent(self, name):
        if not isinstance(name, str):
            return None
        return self.agents.get(name.strip())

    def get_all_agents(self):
        return [self.agents[name] for name in sorted(self.agents)]

    def get_names(self):
        return tuple(sorted(self.agents))

    def count(self):
        return len(self.agents)

    def find_capable_agents(self, task):
        if not isinstance(task, str):
            return []
        matches = []
        for agent in self.get_all_agents():
            try:
                if bool(agent.can_handle(task)):
                    matches.append(agent)
            except Exception:
                continue
        return matches

    def find_capable_agent(self, task):
        matches = self.find_capable_agents(task)
        return matches[0] if matches else None

    def find_agents_by_keywords(self, keyword):
        if not isinstance(keyword, str):
            return []
        key = keyword.strip().lower()
        return [
            agent for agent in self.get_all_agents()
            if key in {str(x).lower() for x in getattr(agent, "keywords", [])}
        ]

    def find_by_capability(self, capability):
        if not isinstance(capability, str):
            return None
        key = capability.strip()
        for agent in self.get_all_agents():
            if key in getattr(agent, "capabilities", []):
                return agent
        return None

    def status(self):
        return {
            "version": self.VERSION,
            "agent_count": self.count(),
            "agents": [
                {
                    "name": agent.name,
                    "description": getattr(agent, "description", ""),
                    "capabilities": list(getattr(agent, "capabilities", [])),
                    "status": getattr(agent, "status", "unknown"),
                }
                for agent in self.get_all_agents()
            ],
        }

    def get_status(self):
        return self.status()
