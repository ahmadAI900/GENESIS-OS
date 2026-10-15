class GenesisAgentBridge:

    def __init__(
        self,
        brain,
        orchestrator,
        executor,
        context
    ):
        self.brain = brain
        self.orchestrator = orchestrator
        self.executor = executor
        self.context = context

    # -----------------------------------------
    # CLASSIFY REQUEST
    # -----------------------------------------

    def classify_request(self, user_input):

        text = user_input.lower()

        agent_keywords = {
            "research": "Research Agent",
            "analyze": "Data Agent",
            "data": "Data Agent",
            "code": "Coding Agent",
            "coding": "Coding Agent",
            "debug": "Coding Agent",
            "study": "Study Agent",
            "learn": "Study Agent",
            "business": "Business Agent",
            "design": "Design Agent",
            "document": "Document Agent",
            "pdf": "Document Agent",
            "security": "Security Agent",
            "secure": "Security Agent",
            "plan": "Planning Agent",
            "planning": "Planning Agent",
            "internet": "Internet Agent",
            "search": "Internet Agent",
        }

        for keyword, agent_name in agent_keywords.items():

            if keyword in text:

                return {
                    "type": "agent",
                    "agent": agent_name,
                    "task": user_input
                }

        return {
            "type": "conversation",
            "agent": None,
            "task": user_input
        }

    # -----------------------------------------
    # HANDLE REQUEST
    # -----------------------------------------

    def handle(self, user_input):

        classification = self.classify_request(
            user_input
        )

        print(
            "[Genesis Bridge] Request type:",
            classification["type"]
        )

        # -------------------------------------
        # LEVEL 1
        # -------------------------------------

        if classification["type"] == "conversation":

            return {
                "type": "conversation",
                "handled_by": "Level 1",
                "task": user_input
            }

        # -------------------------------------
        # LEVEL 2
        # -------------------------------------

        print(
            "[Genesis Bridge] Routing to:",
            classification["agent"]
        )

        return self.execute_agent_task(
            user_input,
            classification["agent"]
        )

    # -----------------------------------------
    # EXECUTE AGENT TASK
    # -----------------------------------------

    def execute_agent_task(
        self,
        task,
        agent_name
    ):

        print(
            "[Genesis Bridge] Executing Level 2 task"
        )

        prepared_task = {
            "task": task,
            "agent": agent_name
        }

        try:

            result = self.executor.execute(
                [prepared_task]
            )

        except TypeError:

            # Compatibility fallback for
            # current executor implementations.

            result = self.executor.execute(
                prepared_task
            )

        return {
            "type": "agent",
            "handled_by": "Level 2",
            "agent": agent_name,
            "task": task,
            "result": result
        }