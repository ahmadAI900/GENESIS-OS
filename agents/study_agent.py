from agents.base_agent import BaseAgent
from ai.ai_engine import AIEngine


class StudyAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Study Agent",
            description="Teaches topics, creates lessons, exercises, and quizzes.",
            capabilities=[
                "teaching",
                "explanation",
                "examples",
                "practice",
                "quiz",
                "learning_plan"
            ]
        )

        self.ai = ai_engine or AIEngine()

    def can_handle(self, task):

        keywords = [
            "teach me",
            "study",
            "learn",
            "explain",
            "lesson",
            "quiz me",
            "practice",
            "help me understand",
            "teaching",
            "explanation",
            "lesson_generation",
            "examples",
            "practice_exercises",
            "quiz_generation",
            "answer_generation",
            "study",
            "learn",
            "learning",
            "explain",
            "concept",
            "summarize",
             "summary",
            "teach",
            "understand",
            "tutor",
            "course",
            "curriculum",
            "syllabus",

            # Academic & Notes
            "flashcard",
            "flashcards",
            "quiz",
            "exam",
            "test prep",
            "notes",
            "key takeaways",
            "simplification",
            "eli5",  # Explain Like I'm 5
            "breakdown",

    # Educational Content & Research
            "textbook",
            "paper",
            "article",
            "academic",
            "theory",
            "definition",
            "example",
            "analogy"

        ]

        task = task.lower()

        return any(
            keyword in task
            for keyword in keywords
        )

    def run(self, task, context=None):

        print(
            f"[Study Agent] Teaching: {task}"
        )

        prompt = f"""
You are Genesis Study Agent.

Your job is to teach the user clearly and effectively.

USER REQUEST:

{task}

PREVIOUS AGENT CONTEXT:

{context}

Create a structured learning session.

Return the following:

## Topic

Identify the main topic.

## Learning Objective

Explain what the student should understand after this lesson.

## Explanation

Teach the topic clearly.

Start simple and build toward more advanced ideas.

## Examples

Give practical examples.

## Practice Exercise

Give the student exercises to solve.

Do not immediately reveal the answers.

## Quiz

Create a short quiz of 5 questions in EXACTLY this format, one per line:

Q1: <question>
A1: <answer>

## Answer Key

Provide the correct answers after the quiz.

## Common Mistakes

Explain mistakes beginners commonly make.

## Next Step

Recommend what the student should learn next.

IMPORTANT:

- Do not claim that you personally know the student's exact skill level unless provided.
- Do not invent information.
- Keep explanations accurate.
- Prefer clear examples over unnecessary complexity.
- Encourage understanding rather than memorization.
"""

        response = self.ai.generate_response(prompt)

        # ==========================================
        # LEVEL 2.5 — REAL STUDY DECK ARTIFACT
        #
        # Parse the quiz Q/A pairs and save a reusable
        # flashcard deck file.
        # ==========================================

        tool_metadata = {"operation": "study"}

        try:
            import re as _re

            from agents.agent_tools import AgentWorkspace

            if not hasattr(self, "workspace"):
                self.workspace = AgentWorkspace()

            pairs = _re.findall(
                r"^Q(\d+)[:.)]\s*(.+?)\s*\nA\1[:.)]\s*(.+)$",
                response,
                _re.MULTILINE,
            )

            if pairs:
                deck_lines = [
                    f"{question}\t{answer}"
                    for _, question, answer in pairs
                ]

                saved = self.workspace.save_text_artifact(
                    kind="Study",
                    base_name=f"flashcards-{task}",
                    content=(
                        "# Genesis Flashcard Deck\n"
                        f"# Topic: {task}\n"
                        "# Format: question<TAB>answer\n\n"
                        + "\n".join(deck_lines)
                        + "\n"
                    ),
                    extension=".txt",
                )

                if saved.get("success"):
                    response = (
                        response
                        + f"\n\n---\n🗂️ **Flashcard deck saved:** "
                        f"`{saved['path']}` ({len(pairs)} cards)"
                    )

                    tool_metadata["artifact_saved"] = True
                    tool_metadata["artifact_path"] = saved["path"]
                    tool_metadata["card_count"] = len(pairs)

        except Exception as tool_error:
            tool_metadata["tool_error"] = str(tool_error)

        return self.create_result(
            task=task,
            response=response,
            success=True,
            metadata={
                **tool_metadata
            }
        )

    def execute(self, task, context=None):

        self.start()

        try:

            previous_context = ""

            if context and context.has_results():

                latest = context.get_latest_result()

                if latest:

                    previous_context = f"""
Previous Agent:
{latest["agent"]}

Previous Agent Result:
{latest["result"]}
"""

            result = self.run(
                task,
                previous_context
            )

            if context:

                context.add_result(
                    self.name,
                    result
                )

            return result

        finally:

            self.stop()