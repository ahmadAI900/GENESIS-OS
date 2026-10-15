class ResultAggregator:

    def __init__(self, context):
        self.context = context

    # ==========================================
    # COLLECT RESULTS
    # ==========================================

    def collect_results(self):

        results = self.context.get_results()

        print(
            f"[Result Aggregator] "
            f"Collected {len(results)} result(s)."
        )

        return results

    # ==========================================
    # BUILD AGGREGATION INPUT
    # ==========================================

    def build_input(self, results):

        aggregation_input = []

        for item in results:

            aggregation_input.append({
                "agent": item.get("agent"),
                "result": item.get("result")
            })

        return aggregation_input

    # ==========================================
    # AGGREGATE
    # ==========================================

    def aggregate(self, results):

        results = self.build_input(results)

        if not results:

            return {
                "success": False,
                "agent_count": 0,
                "results": [],
                "summary": "No agent results available."
            }

        print(
            "[Result Aggregator] "
            "Combining multi-agent results..."
        )

        summaries = []

        for item in results:

            agent_name = item["agent"]
            result = item["result"]

            summaries.append({
                "agent": agent_name,
                "result": result
            })

        return {
            "success": True,
            "agent_count": len(results),
            "results": summaries,
            "summary": (
                "Multi-agent results successfully "
                "collected and aggregated."
            )
        }