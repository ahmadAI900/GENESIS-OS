class MultiAgentExecutor:

    def __init__(self, registry, context):

        self.registry = registry
        self.context = context

        self._session_state = None
        self._entity_history = None

    def set_session_context(
        self, session_state=None, entity_history=None
    ):
        """
        Inject live session state and entity history so
        agents receive structured context.
        """

        self._session_state = session_state
        self._entity_history = entity_history

    # ==========================================
    # BUILD CHAIN CONTEXT
    # ==========================================

    def build_chain_context(self):

        previous_results = self.context.get_results()

        if not previous_results:
            return ""

        context_text = (
            "\n\n"
            "======================================\n"
            "PREVIOUS GENESIS AGENT RESULTS\n"
            "======================================\n"
        )

        for index, item in enumerate(
            previous_results,
            start=1
        ):

            context_text += (
                f"\nRESULT {index}\n"
                f"Agent: {item.get('agent')}\n"
                f"Result:\n"
                f"{item.get('result')}\n"
            )

        context_text += (
            "\n======================================\n"
            "END PREVIOUS AGENT RESULTS\n"
            "======================================\n"
        )

        return context_text

    # ==========================================
    # BUILD STRUCTURED CONTEXT
    # ==========================================

    def build_structured_context(self, task):
        """
        Build a structured context block from session state
        and entity history for the agent.
        """

        from genesis_os.structured_context import (
            StructuredAgentContext,
        )

        previous_results = self.context.get_results()

        conversation_history = []
        if hasattr(self, '_conversation'):
            try:
                conversation_history = (
                    self._conversation.get_history()
                )
            except Exception:
                pass

        structured = StructuredAgentContext.from_genesis_state(
            task,
            session_state=self._session_state,
            entity_history=self._entity_history,
            previous_results=previous_results,
            conversation_history=conversation_history,
        )

        return structured.to_context_string()

    # ==========================================
    # EXECUTE SEQUENTIAL WORKFLOW
    # ==========================================

    def execute(self, tasks):

        results = []

        print()
        print("======================================")
        print("   GENESIS SEQUENTIAL AGENT WORKFLOW")
        print("======================================")

        for index, task_data in enumerate(
            tasks,
            start=1
        ):

            print()
            print("--------------------------------------")
            print(f"WORKFLOW STEP {index}")
            print("--------------------------------------")

            # ----------------------------------
            # NORMALIZE TASK
            # ----------------------------------

            if isinstance(task_data, dict):

                task = task_data.get(
                    "task",
                    ""
                )

                requested_agent = task_data.get(
                    "agent"
                )

            else:

                task = str(task_data)
                requested_agent = None

            print(
                f"Task: {task}"
            )

            # ----------------------------------
            # SELECT AGENT
            # ----------------------------------

            agent = None

            if requested_agent:

                print(
                    f"[Workflow] Requested agent: "
                    f"{requested_agent}"
                )

                agent = self.registry.get_agent(
                    requested_agent
                )

            else:

                agent = (
                    self.registry.find_capable_agent(
                        task
                    )
                )

            if agent is None:

                print(
                    "[Workflow] No capable agent found."
                )

                results.append({
                    "step": index,
                    "task": task,
                    "agent": None,
                    "result": None,
                    "status": "failed"
                })

                continue

            print(
                f"[Workflow] Selected: "
                f"{agent.name}"
            )

            # ----------------------------------
            # GET ACCUMULATED CONTEXT
            # ----------------------------------

            chain_context = (
                self.build_chain_context()
            )

            if chain_context:

                print(
                    "[Workflow] Passing accumulated "
                    "results to next agent."
                )

            else:

                print(
                    "[Workflow] No previous results."
                )

            # ----------------------------------
            # GET STRUCTURED CONTEXT
            # ----------------------------------

            structured_ctx = (
                self.build_structured_context(task)
            )

            # ----------------------------------
            # BUILD CHAINED TASK
            # ----------------------------------

            chained_task = (
                task
                + chain_context
                + structured_ctx
            )

            # ----------------------------------
            # EXECUTE
            # ----------------------------------

            try:

                result = agent.execute(
                    chained_task,
                    self.context
                )

                results.append({
                    "step": index,
                    "task": task,
                    "agent": agent.name,
                    "result": result,
                    "status": "completed"
                })

                print(
                    f"[Workflow] {agent.name} "
                    f"completed."
                )

                print(
                    f"[Workflow] Context now contains "
                    f"{len(self.context.get_results())} "
                    f"result(s)."
                )

            except Exception as error:

                print(
                    f"[Workflow] Agent error: {error}"
                )

                results.append({
                    "step": index,
                    "task": task,
                    "agent": agent.name,
                    "result": None,
                    "status": "failed",
                    "error": str(error)
                })

        return results