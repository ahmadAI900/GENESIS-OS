from agents.base_agent import BaseAgent
from ai.ai_engine import AIEngine


class DataAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Data Agent",
            description=(
                "Analyzes data, identifies patterns, "
                "creates insights, and supports data-driven decisions."
            ),
            capabilities=[
                "data_analysis",
                "data_interpretation",
                "pattern_detection",
                "data_insights",
                "data_cleaning",
                "statistical_analysis"
            ]
        )

        self.ai = ai_engine or AIEngine()

    # ==========================================
    # CAPABILITY DETECTION
    # ==========================================

    def can_handle(self, task):

        keywords = [
            "data",
            "dataset",
            "analyze data",
            "data analysis",
            "statistics",
            "statistical",
            "trend",
            "patterns",
            "csv",
            "spreadsheet",
            "metrics",
            "numbers",
            "analytics",
            "insights"
        ]

        task = task.lower()

        return any(
            keyword in task
            for keyword in keywords
        )

    # ==========================================
    # MAIN DATA ENGINE
    # ==========================================

    def run(self, task, context=None):

        print(
            f"[Data Agent] Analyzing: {task}"
        )

        # ==========================================
        # LEVEL 2.5 — REAL DATA ANALYSIS
        #
        # When a CSV file or an inline number series is part of
        # the request, compute GENUINE statistics first and let
        # the AI interpret real numbers instead of inventing.
        # ==========================================

        from agents.agent_tools import (
            find_data_path,
            data_column_statistics,
            inline_number_series,
            series_statistics,
        )

        real_data_report = ""
        tool_metadata = {"operation": "data_analysis"}

        try:
            csv_path = find_data_path(task)

            stats = None

            if csv_path:
                print(
                    f"[Data Agent] CSV detected: {csv_path}"
                )

                stats = data_column_statistics(csv_path)

                if stats.get("success"):
                    tool_metadata["csv_analyzed"] = csv_path

                    lines = [
                        f"REAL DATA — file: {csv_path} "
                        f"({stats['row_count']} rows)",
                    ]

                    for column, entry in stats["columns"].items():
                        trend = (
                            f", trend {entry['trend_percent']:+.1f}%"
                            if "trend_percent" in entry
                            else ""
                        )
                        lines.append(
                            f"- {column}: n={entry['count']}, "
                            f"min={entry['min']}, max={entry['max']}, "
                            f"mean={entry['mean']}, "
                            f"median={entry['median']}"
                            + (
                                f", stdev={entry['stdev']}"
                                if "stdev" in entry
                                else ""
                            )
                            + trend
                        )

                    real_data_report = "\n".join(lines)

                    tool_metadata["real_statistics"] = {
                        name: value
                        for name, value in stats["columns"].items()
                    }

            else:

                series = inline_number_series(task)

                if len(series) >= 3:
                    stats = series_statistics(series)

                    if stats.get("success"):
                        tool_metadata["series_analyzed"] = series

                        real_data_report = (
                            "REAL DATA — inline series: "
                            f"{series}\n"
                            f"- count={stats['count']}, "
                            f"min={stats['min']}, max={stats['max']}, "
                            f"mean={stats['mean']}, "
                            f"median={stats['median']}"
                            + (
                                f", stdev={stats['stdev']}"
                                if "stdev" in stats
                                else ""
                            )
                        )

            if real_data_report:
                real_data_report = (
                    "The following statistics were ALREADY "
                    "computed from the user's real data. Use "
                    "these exact numbers; never invent others:\n\n"
                    + real_data_report
                    + "\n\n"
                )

        except Exception as tool_error:

            tool_metadata["tool_error"] = str(tool_error)

        context_information = ""

        if context:

            previous_results = (
                context.get_results()
            )

            if previous_results:

                context_information = """
Previous agent results are available in
Genesis shared context.

Use them only when relevant to the
current data task.
"""

        prompt = f"""
You are Genesis Data Agent.

The user requested:

{task}

{real_data_report}{context_information}

Your job is to help with data-related work.

Possible operations include:

- data analysis
- data interpretation
- finding trends
- identifying patterns
- statistical reasoning
- data cleaning recommendations
- comparing metrics
- extracting insights
- supporting data-driven decisions

When appropriate structure the response as:

1. Data Objective
2. Data Available
3. Important Observations
4. Trends and Patterns
5. Statistical Insights
6. Anomalies
7. Possible Explanations
8. Conclusions
9. Recommended Actions

Rules:

- Do not invent data.
- Do not invent numerical results.
- Clearly distinguish observed values from assumptions.
- If the actual dataset is unavailable, say so.
- Do not claim that calculations were performed
  unless the required data was actually provided.
- Keep analysis precise and evidence-based.
"""

        response = self.ai.generate_response(
            prompt
        )

        if real_data_report and "REAL DATA" in real_data_report:
            response = (
                "📊 **Computed from your actual data:**\n"
                + real_data_report.split("never invent others:\n\n")[-1].strip()
                + "\n\n"
                + response
            )

        return self.create_result(
            task=task,
            response=response,
            success=True,
            metadata={
                **tool_metadata,
            }
        )

    # ==========================================
    # DIRECT INTERFACE
    # ==========================================

    def analyze(self, task):

        return self.run(task)

    # ==========================================
    # UNIVERSAL AGENT INTERFACE
    # ==========================================

    def execute(self, task, context=None):

        self.start()

        try:

            result = self.run(
                task,
                context
            )

            if context:

                context.add_result(
                    self.name,
                    result
                )

            return result

        finally:

            self.stop()