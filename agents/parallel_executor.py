from concurrent.futures import ThreadPoolExecutor, as_completed


class ParallelAgentExecutor:

    def __init__(self, registry, context, max_workers=5):

        self.registry = registry
        self.context = context
        self.max_workers = max_workers

    # ==========================================
    # EXECUTE SINGLE TASK
    # ==========================================

    def _execute_task(self, task):

        task_text = task.get("task", "")
        requested_agent = task.get("agent")

        print()
        print("--------------------------------------")
        print(f"[Parallel Executor] Task: {task_text}")

        agent = None

        # Explicit agent requested
        if requested_agent:

            agent = self.registry.get_agent(
                requested_agent
            )

            if agent:
                print(
                    f"[Parallel Executor] Selected: "
                    f"{agent.name}"
                )

        # Otherwise discover capable agent
        if agent is None:

            agent = self.registry.find_capable_agent(
                task_text
            )

        if agent is None:

            print(
                "[Parallel Executor] "
                "No capable agent found."
            )

            return {
                "success": False,
                "task": task_text,
                "agent": None,
                "error": "No capable agent found"
            }

        try:

            result = agent.run(task_text)

            # Store exactly one context result
            existing = self.context.get_agent_result(
                agent.name
            )

            if existing is None:
                self.context.add_result(
                    agent.name,
                    result
                )

            print(
                f"[Parallel Executor] "
                f"{agent.name} completed."
            )

            return {
                "success": True,
                "task": task_text,
                "agent": agent.name,
                "result": result
            }

        except Exception as error:

            print(
                f"[Parallel Executor] "
                f"{agent.name} failed: {error}"
            )

            return {
                "success": False,
                "task": task_text,
                "agent": agent.name,
                "error": str(error)
            }

    # ==========================================
    # EXECUTE PARALLEL TASKS
    # ==========================================

    def execute(self, tasks):

        if not tasks:

            return []

        print()
        print("======================================")
        print("   GENESIS PARALLEL AGENT EXECUTOR")
        print("======================================")

        print()
        print(
            f"[Parallel Executor] "
            f"Starting {len(tasks)} independent tasks..."
        )

        results = []

        with ThreadPoolExecutor(
            max_workers=min(
                self.max_workers,
                len(tasks)
            )
        ) as executor:

            futures = [
                executor.submit(
                    self._execute_task,
                    task
                )
                for task in tasks
            ]

            for future in as_completed(futures):

                result = future.result()

                results.append(result)

        print()
        print(
            f"[Parallel Executor] "
            f"Completed {len(results)} task(s)."
        )

        return results