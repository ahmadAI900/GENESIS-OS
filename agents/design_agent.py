from agents.base_agent import BaseAgent
from ai.ai_engine import AIEngine


class DesignAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Design Agent",
            description=(
                "Creates design concepts, UI/UX ideas, "
                "visual specifications, and design plans."
            ),
            capabilities=[
                "design",
                "ui_design",
                "ux_design",
                "design_planning",
                "visual_concepts",
                "design_analysis"
            ]
        )

        self.ai = ai_engine or AIEngine()

    # ==========================================
    # CAPABILITY DETECTION
    # ==========================================

    def can_handle(self, task):

        keywords = [
            "design",
            "ui",
            "ux",
            "interface",
            "layout",
            "visual",
            "wireframe",
            "prototype",
            "user experience",
            "user interface",
            "canvas",
            "diagram",
            "image"
        ]

        task = task.lower()

        return any(
            keyword in task
            for keyword in keywords
        )

    # ==========================================
    # MAIN DESIGN ENGINE
    # ==========================================

    def run(self, task, context=None):

        print(
            f"[Design Agent] Designing: {task}"
        )

        prompt = f"""
You are Genesis Design Agent.

The user requested:

{task}

Your job is to help with design-related work.

Possible operations include:

- UI design
- UX design
- interface planning
- layout design
- wireframe concepts
- visual design concepts
- design analysis
- user-flow planning

Produce a practical and structured design response.

When appropriate include:

1. Design Goal
2. Target User
3. User Experience
4. Interface Structure
5. Main Components
6. Visual Direction
7. User Flow
8. Implementation Notes

Rules:

- Do not claim that an actual image or prototype was created
  unless an appropriate design/image tool actually created it.
- Clearly distinguish design specifications from generated assets.
- Prioritize usability, accessibility, clarity, and consistency.
- Do not invent requirements that the user did not provide.
"""

        response = self.ai.generate_response(
            prompt
        )

        # ==========================================
        # LEVEL 2.5 — REAL DESIGN ARTIFACT
        #
        # Generate a real SVG palette board so the user gets
        # an actual openable design asset, not just advice.
        # ==========================================

        tool_metadata = {"operation": "design_concept"}

        try:
            from agents.agent_tools import (
                AgentWorkspace,
                palette_svg,
            )

            if not hasattr(self, "workspace"):
                self.workspace = AgentWorkspace()

            theme = next(
                (
                    name
                    for name in ("ocean", "sunset", "forest", "neon", "mono")
                    if name in task.lower()
                ),
                "ocean",
            )

            svg_result = palette_svg(theme, title=task[:60])

            if svg_result.get("success"):
                saved = self.workspace.save_text_artifact(
                    kind="Designs",
                    base_name=f"{theme}-palette-{task[:24]}",
                    content=svg_result["svg"],
                    extension=".svg",
                )

                if saved.get("success"):
                    response = (
                        response
                        + f"\n\n---\n🎨 **Real design asset created:** "
                        f"`{saved['path']}` "
                        f"(open in any browser — theme '{theme}': "
                        f"{', '.join(svg_result['colors'])})"
                    )

                    tool_metadata["artifact_saved"] = True
                    tool_metadata["artifact_path"] = saved["path"]
                    tool_metadata["theme"] = theme

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

    # ==========================================
    # DIRECT INTERFACE
    # ==========================================

    def design(self, task):

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