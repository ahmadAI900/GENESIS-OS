class ReasoningEngine:

    def __init__(self):
        print("[Reasoning] Engine initialized")

    def solve(self, problem: str) -> str:
        problem = problem.strip()

        if not problem:
            return "Please provide a problem."

        return self.build_reasoning_prompt(problem)

    def build_reasoning_prompt(self, problem: str) -> str:
        return (
            "You are Genesis AI's reasoning engine.\n\n"

            "Solve the problem carefully using logical steps.\n"
            "Identify the important information first.\n"
            "Break the problem into smaller steps.\n"
            "Perform each step in the correct order.\n"
            "Check the result for consistency.\n"
            "Then provide the final answer clearly.\n\n"

            "IMPORTANT:\n"
            "Do not skip necessary steps.\n"
            "Do not assume information that is not provided.\n"
            "If the problem is ambiguous, explain what is missing.\n\n"

            f"PROBLEM:\n{problem}\n\n"

            "REASONING:\n"
            "Step 1:"
        )