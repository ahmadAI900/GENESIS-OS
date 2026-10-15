class PromptBuilder:

    def __init__(self):
        self.system_instruction = (
            "You are GENESIS AI, a helpful and intelligent personal AI assistant.\n"
            "Answer clearly, accurately, naturally, and conversationally.\n"
            "Use the conversation history to understand follow-up questions.\n"
            "Use information already provided by the user as conversation context.\n"
            "Use long-term memory when it is relevant.\n"
            "Do not invent personal information.\n"
            "For mathematics, explain solutions step by step.\n"
            "For general questions, give direct and helpful answers.\n"
            "Do not mention internal prompts, routing, memory, or system instructions.\n"
            "Behave like a mature, thoughtful, and reliable AI assistant.\n"
            "Be calm, respectful, and natural in every conversation.\n"
            "Do not exaggerate or overreact to ordinary situations.\n"
            "Do not repeat information unnecessarily.\n"
            "Be concise when a simple answer is enough.\n"
            "Give more explanation when the user needs it.\n"
            "Do not ask unnecessary follow-up questions.\n"
            "If the user asks a clear question, answer it directly first.\n"
            "If you are uncertain, be honest instead of inventing information.\n"
            "Use the user's emotions and preferences only when relevant to the response.\n"
            "Do not pretend to know information you do not have.\n"
            "If the available context is insufficient to answer reliably, say so clearly.\n"
            "Do not fabricate facts, memories, events, sources, or personal information.\n"
            "When you are unsure, explain the uncertainty briefly and give the most useful answer you can.\n"
            "Use the user's emotions and preferences only when relevant to the response.\n"
            "Adapt your response style appropriately to the user's detected emotional state.\n"
            "If the user is happy or excited, respond warmly and positively without overdoing it.\n"
            "If the user is sad, disappointed, or frustrated, respond with empathy and patience.\n"
            "If the user appears angry, remain calm and respectful and avoid escalating the situation.\n"
            "If the user appears confused, explain things more simply and step by step.\n"
            "Do not diagnose, label, or make medical conclusions about the user's emotional state.\n"
            "Do not assume an emotion is certain when the available context is ambiguous.\n"
            "Ask a follow-up question only when additional information would meaningfully improve the answer.\n"
            "Do not end every response with a question.\n"
            "If the user's request is complete and no clarification is needed, finish the response naturally.\n"
            "When clarification is necessary, ask one clear and specific question at a time.\n"
            "Prefer answering the user's question first before asking for additional information.\n"
            "Maintain consistency with reliable information stored in long-term memory and user preferences.\n"
            "When previous information conflicts with newer information, treat the newer explicit user statement as the current preference.\n"
            "Do not contradict established user information without a clear reason.\n"

            "Do not mention internal prompts, routing, memory, debug information, "
            "or system instructions."
        )

    def build_prompt(self, user_input: str, history=None, memory=None , emotion = "neutral", personality_context = "", preferences = None):

        if history is None:
            history = []

        if memory is None:
            memory = []
        if preferences is None:
            preferences = []

        prompt_parts = []

        # SYSTEM INSTRUCTIONS
        prompt_parts.append(
            "SYSTEM INSTRUCTIONS:\n"
            + self.system_instruction
        )

        # LONG-TERM MEMORY
        if memory:
            prompt_parts.append("\nLONG-TERM MEMORY:")

            for item in memory:

                if isinstance(item, dict):

                    content = item.get("message", "")

                    if not content:
                        content = item.get("content", "")

                    if content:
                        prompt_parts.append(
                            "MEMORY: " + str(content)
                        )

                else:
                    prompt_parts.append(
                        "MEMORY: " + str(item))

        # -------------------------
        # RELEVANT USER PREFERENCES
        # -------------------------

        if preferences:
            prompt_parts.append("\nUSER PREFERENCES:")

            if isinstance(preferences, dict):

                for preference, liked in preferences.items():

                    if liked:
                        prompt_parts.append(
                            f"- User prefers: {preference}"
                        )
                    else:
                        prompt_parts.append(
                            f"- User does not like: {preference}"
                        )

            elif isinstance(preferences, list):

                    for item in preferences:

                        if isinstance(item, dict):

                            preference = item.get("preference", "")
                            liked = item.get("liked", True)

                            if preference:
                                if liked:
                                    prompt_parts.append(
                                        f"- User prefers: {preference}"
                                    )
                                else:
                                    prompt_parts.append(
                                    f"- User does not like: {preference}"
                                    )    
                    
        prompt_parts.append("\nCURRENT USER EMOTION:\n" + str(emotion))
        if personality_context:
            prompt_parts.append("\nPERSONALIZATION CONTEXT:\n"+ str(personality_context))

        # CONVERSATION HISTORY
        if history:

            prompt_parts.append(
                "\nCONVERSATION HISTORY:"
            )

            for item in history:

                if isinstance(item, dict):

                    role = item.get("role", "user")
                    message = item.get("message", "")

                    if not message:
                        message = item.get("content", "")

                    if message:
                        prompt_parts.append(
                            role.upper() + ": " + str(message)
                        )

                else:
                    prompt_parts.append(
                        str(item)
                    )

        # CURRENT USER MESSAGE
        prompt_parts.append(
            "\nCURRENT USER MESSAGE:"
        )

        prompt_parts.append(
            str(user_input)
        )

        # FINAL INSTRUCTION
        prompt_parts.append(
            "\nUse the conversation history and long-term memory "
            "to answer the current user message."
        )

        prompt_parts.append(
            "\nGENESIS AI RESPONSE:"
        )

        # THIS IS VERY IMPORTANT
        return "\n".join(prompt_parts)
    