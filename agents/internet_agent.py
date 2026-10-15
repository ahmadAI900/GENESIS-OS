from agents.base_agent import BaseAgent
from internet.search import InternetSearch


class InternetAgent(BaseAgent):

    def __init__(self):

        super().__init__(
            name="Internet Agent",
            description="Searches the internet and returns structured web information.",
            capabilities=[
                "web_search",
                "multi_source_search",
                "information_retrieval",
                "web_results"
            ]
        )

        self.internet = InternetSearch()

    def can_handle(self, task):

        keywords = [
            "search the internet",
            "search internet",
            "search the web",
            "search web",
            "web search",
            "search online",
            "find online",
            "find on the web",
            "look online",
            "browse the web",
            "browse internet",
            "web_search",
            "information_search",
            "url_search",
            "current_information",
            "source_collection",
            "look up",
            "find information"
        ]

        task = task.lower().strip()

        return any(
            keyword in task
            for keyword in keywords
        )

    def run(self, task, context=None):

        print(
            f"[Internet Agent] Searching web for: {task}"
        )

        sources = self.internet.search_multiple(
            task,
            max_results=5
        )

        print(
            f"[Internet Agent] Collected {len(sources)} sources"
        )

        return self.create_result(
            task=task,
            response=sources,
            success=True,
            metadata={
                "source_count": len(sources),
                "sources": sources
            }
        )

    def execute(self, task, context=None):

        self.start()

        try:

            result = self.run(task)

            if context:

                context.add_result(
                    self.name,
                    result
                )

            return result

        finally:

            self.stop()