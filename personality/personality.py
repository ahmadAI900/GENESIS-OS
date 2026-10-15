class PersonalityEngine:

    def __init__(self):
        print("[Personality] Engine initialized")

    def build_context(self, memories=None, profile=None, preferences=None):
        context = []

        if memories:
            context.append("Relevant memories:")

            for memory in memories:
                if isinstance(memory, dict):
                    message = memory.get("message", "")

                    if message:
                        context.append(
                            f"- {message}"
                        )
                else:
                    context.append(
                        f"- {str(memory)}"
                    )

        if profile:
            context.append("\nUser profile:")

            for key, value in profile.items():
                context.append(
                    f"- {key}: {value}"
                )

        if preferences:
            context.append("\nUser preferences:")

            for key, value in preferences.items():
                context.append(
                    f"- {key}: {value}"
                )

        if not context:
            return ""

        return "\n".join(context)

    def personalize_instruction(self):
        return (
            "Personalize your response using the user's relevant "
            "memories, profile, and preferences. "
            "Do not invent personal information. "
            "Only use information that is actually available."
        )