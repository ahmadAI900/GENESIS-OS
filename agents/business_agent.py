from agents.base_agent import BaseAgent
from ai.ai_engine import AIEngine


class BusinessAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Business Agent",
            description=(
                "Analyzes business problems, opportunities, "
                "strategies, workflows, and business plans."
            ),
            capabilities=[
                "business_analysis",
                "business_strategy",
                "business_planning",
                "market_analysis",
                "workflow_analysis",
                "business_ideas",
                "business_metrics",
                "unit_economics",
                "swot_analysis",
                "kpi_design",
                "pricing_analysis"
            ]
        )

        self.ai = ai_engine or AIEngine()

    # ==========================================
    # CAPABILITY DETECTION
    # ==========================================

    def can_handle(self, task):

        keywords = [
            "business",
            "company",
            "startup",
            "market",
            "customer",
            "customers",
            "business plan",
            "business strategy",
            "marketing",
            "sales",
            "revenue",
            "profit",
            "entrepreneur",
            "workflow",
            "loss",
            "buisness"
        ]

        task = task.lower()

        return any(
            keyword in task
            for keyword in keywords
        )

    # ==========================================
    # MAIN BUSINESS ENGINE
    # ==========================================

    def run(self, task, context=None):

        print(
            f"[Business Agent] Analyzing: {task}"
        )

        context_information = ""

        if context:

            previous_results = (
                context.get_results()
            )

            if previous_results:

                context_information = f"""
Previous agent results are available in
Genesis shared context.

Use them only when relevant to the
current business task.
"""

        prompt = f"""
You are Genesis Business Agent.

The user requested:

{task}

{context_information}

Your job is to help with business-related work.

Possible operations include:

- business analysis
- business strategy
- startup planning
- market analysis
- customer analysis
- workflow optimization
- business model development
- revenue strategy
- sales strategy
- operational planning

When appropriate structure the response as:

1. Business Objective
2. Problem or Opportunity
3. Target Customers
4. Market Considerations
5. Proposed Strategy
6. Business Model
7. Operations
8. Risks
9. Recommended Actions
10. Expected Outcomes

Rules:

- Do not invent market statistics.
- Do not present assumptions as verified facts.
- Clearly identify assumptions.
- If reliable market research is required,
  recommend using the Research Agent.
- Keep recommendations practical and actionable.
"""

        response = self.ai.generate_response(
            prompt
        )

        return self.create_result(
            task=task,
            response=response,
            success=True,
            metadata={
                "operation": "business_analysis"
            }
        )

    # ==========================================
    # DETERMINISTIC BUSINESS TOOLS
    # ==========================================

    @staticmethod
    def calculate_metrics(revenue=0, cost=0, customers=0, price=0):
        revenue = float(revenue or 0)
        cost = float(cost or 0)
        customers = int(customers or 0)
        price = float(price or 0)
        profit = revenue - cost
        margin = (profit / revenue * 100) if revenue else 0.0
        arpu = (revenue / customers) if customers else 0.0
        return {
            "revenue": revenue, "cost": cost, "profit": profit,
            "profit_margin_percent": round(margin, 2),
            "customers": customers, "average_revenue_per_customer": round(arpu, 2),
            "verified": True,
        }

    @staticmethod
    def build_swot(strengths, weaknesses, opportunities, threats):
        return {
            "strengths": list(strengths or []),
            "weaknesses": list(weaknesses or []),
            "opportunities": list(opportunities or []),
            "threats": list(threats or []),
        }

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