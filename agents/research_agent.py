from agents.base_agent import BaseAgent
from .source_evaluator import SourceEvaluator
from internet.search import InternetSearch
from ai.ai_engine import AIEngine
from .research_quality import ResearchQuality


class ResearchAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Research Agent",
            description="Researches topics, evaluates sources, and creates research reports.",
            capabilities=[
                "research",
                "web_search",
                "source_evaluation",
                "source_ranking",
                "research_synthesis",
                "quality_check"
            ]
        )

        self.internet = InternetSearch()
        self.ai = ai_engine or AIEngine()
        self.evaluator = SourceEvaluator()
        self.quality = ResearchQuality()

    # ==========================================
    # CAPABILITY DETECTION
    # ==========================================

    def can_handle(self, task):

        keywords = [
            "research",
            "investigate",
            "find information",
            "learn about",
            "research",
            "investigate",
            "analyze",
            "analysis",
            "find info",
            "look up",
            "gather information",
            "study",
            "explore",

    # Information Retrieval & Web Search
            "search",
            "web search",
            "browse",
            "google",
            "find articles",
            "current state of",
            "latest trends",
            "market research",

    # Data Synthesis & Comparison
            "compare",
            "comparison",
            "pros and cons",
            "benchmarking",
            "overview",
            "background on",
            "state of the art",
            "landscape"
        ]

        task = task.lower()

        return any(
            keyword in task
            for keyword in keywords
        )

    # ==========================================
    # MAIN RESEARCH ENGINE
    # ==========================================

    def run(self, task, context = None):

        print(
            f"[Research Agent] Researching: {task}"
        )

        # --------------------------------------
        # STEP 1 — SEARCH
        # --------------------------------------

        sources = self.internet.search_multiple(
            task,
            max_results=5
        )

        print(
            f"[Research Agent] Collected {len(sources)} sources"
        )

        # --------------------------------------
        # STEP 2 — EVALUATE SOURCES
        # --------------------------------------

        evaluated_sources = []

        for source in sources:

            evaluation = self.evaluator.evaluate(
                source
            )

            evaluated_sources.append({
                **source,
                "quality_score": evaluation["score"],
                "quality_reasons": evaluation["reasons"]
            })

        # --------------------------------------
        # STEP 3 — SORT SOURCES
        # --------------------------------------

        evaluated_sources.sort(
            key=lambda source: source["quality_score"],
            reverse=True
        )

        print(
            "[Research Agent] Sources evaluated and ranked"
        )

        # --------------------------------------
        # STEP 4 — PREPARE AI DATA
        # --------------------------------------

        source_text = ""

        for index, source in enumerate(
            evaluated_sources,
            start=1
        ):

            source_text += f"""
SOURCE {index}

Title:
{source["title"]}

Content:
{source["content"]}

URL:
{source["url"]}

Quality Score:
{source["quality_score"]}/5

Quality Reason:
{", ".join(source["quality_reasons"])}

-------------------------
"""

        # --------------------------------------
        # STEP 5 — AI RESEARCH
        # --------------------------------------

        prompt = f"""
You are Genesis Research Agent.

The user asked:

{task}

Genesis collected and evaluated the following sources:

{source_text}

Create a reliable research report.

Use the highest-quality sources as the primary evidence.

The report must contain:

1. Overview
2. Key Findings
3. Important Facts
4. Main Conclusions
5. Sources Used

Rules:

- Do not invent information.
- Do not pretend that an unavailable source was successfully retrieved.
- Do not treat search errors as factual sources.
- If there are no reliable sources, clearly state that research could not be completed reliably.
- If sources disagree, clearly mention the disagreement.
- Prefer information supported by higher-quality sources.
- Keep the report clear and useful.
"""

        print(
            "[Research Agent] Sending evaluated research to AI Engine..."
        )

        summary = self.ai.generate_response(
            prompt
        )

        # --------------------------------------
        # STEP 6 — QUALITY CHECK
        # --------------------------------------

        quality = self.quality.check(
            summary,
            evaluated_sources
        )

        print(
            "[Research Agent] Quality check:",
            "PASSED" if quality["passed"] else "FAILED"
        )

        if quality["issues"]:

            print(
                "[Research Agent] Issues:"
            )

            for issue in quality["issues"]:

                print(
                    "-",
                    issue
                )

        # --------------------------------------
        # STEP 7 — RETURN RESULT
        # --------------------------------------

        return self.create_result(
            task=task,
            response=summary,
            success=quality["passed"],
            metadata={
                "sources": evaluated_sources,
                "source_count": len(evaluated_sources),
                "quality": quality
            }
        )

    # ==========================================
    # LEGACY / DIRECT RESEARCH INTERFACE
    # ==========================================

    def research(self, task):

        return self.run(task)

    # ==========================================
    # UNIVERSAL AGENT INTERFACE
    # ==========================================

    def execute(self, task, context=None):

        self.start()

        try:

            result = self.run(task)

            # ----------------------------------
            # SHARE RESULT WITH AGENT CONTEXT
            # ----------------------------------

            if context:

                context.add_result(
                    self.name,
                    result
                )

            return result

        finally:

            self.stop()