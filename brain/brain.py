from personality.personality import PersonalityEngine
from router.router import Router
from ai.ai_engine import AIEngine
from memory.memory import MemoryManager
from internet.search import InternetSearch
from internet.parser import Parser
from internet.formatter import Formatter
from knowledge.knowledge import Knowledge
from ai.prompt_builder import PromptBuilder
from conversation.conversation import ConversationEngine
from reasoning.reasoning import ReasoningEngine
from emotion.emotion import EmotionEngine

import logging
import os as _os


logger = logging.getLogger("genesis_os.brain")


def _genesis_debug() -> bool:
    """Return True when the GENESIS_DEBUG environment
    variable is set to ``"1"``.

    Debug prints in the Brain and Memory subsystems are
    gated on this so a normal interactive session stays
    quiet. Setting ``GENESIS_DEBUG=1`` before ``python
    genesis.py`` restores the verbose dumps.
    """
    return _os.environ.get("GENESIS_DEBUG") == "1"


class Brain:
    def __init__(self):
        self.router = Router()
        self.ai_engine = AIEngine()
        self.memory = MemoryManager()
        self.internet = InternetSearch()
        self.parser = Parser()
        self.formatter = Formatter()
        self.knowledge = Knowledge()
        self.prompt_builder = PromptBuilder()
        self.conversation = ConversationEngine()
        self.reasoning = ReasoningEngine()
        self.emotion = EmotionEngine()
        self.personality = PersonalityEngine()

    def think(self, user_input: str) -> str:
        return self.process_request(user_input)

    def process_request(self, text: str) -> str:
        text = text.strip()
        emotion = self.emotion.detect(text)
        # Check profile information first
        response = self.memory.learn_profile(text)
        if response:
            return response

        # Check preferences second
        response = self.memory.learn_preference(text)
        if response:
            return response


        if self.is_greeting(text):
            return "Hello! I am Genesis AI. I am created by AHMAD. The future owner of ASAAFS TECHNEOLOGY How can I help you?"

        if self.is_exit(text):
            return "Goodbye! See you soon."

        destination = self.router.route(text)
        logger.debug("Destination: %s", destination)
        if self.is_reasoning_request(text):
            reasoning_prompt = self.reasoning.solve(text)
            answer = self.ai_engine.generate_response(reasoning_prompt)

            self.conversation.add_user_message(text)
            self.conversation.add_assistant_message(answer)

            return answer

        if destination == "memory":

    # Learn profile information
            response = self.memory.learn_profile(text)
            if response:
                 return response

    # Learn user preferences
            response = self.memory.learn_preference(text)
            if response:
                return response

    # Recall stored profile information
            response = self.memory.recall_profile(text)
            if response:
                return response

            return "I couldn't find any memory-related information."

        elif destination == "Internet":
            result = self.internet.search(text)
            parsed = self.parser.extract(result)
            answer = self.formatter.format(parsed)
            return answer

        elif destination == "knowledge":
            answer = self.knowledge.search(text)
            if answer:
                return answer
            return "I could not find that in my knowledge base."

        elif destination == "ai":

            # Save the actual user message
            self.conversation.add_user_message(text)

            # Get conversation history
            history = self.conversation.get_recent_history()

            # Get relevant long-term memory
            memory = self.memory.get_relevent_memory(text)
            preferences = {}

            if self.memory.is_preference_relevant(text):
                preferences = self.memory.get_relevant_preferences(text)

            if _genesis_debug():
                print("[DEBUG PREFERENCES]:", preferences)
                preference_context = self.memory.build_preference_context(preferences)

                print("[DEBUG PREFERENCE CONTEXT]:")
                print(preference_context)

                print("[DEBUG HISTORY]:", history)
                print("[DEBUG MEMORY]:", memory)

                profile = self.memory.load_profile()
                preferences = self.memory.load_preferences()

                personalization_context = self.personality.build_context(memories=memory,profile=profile,preferences=preferences)

                print("[DEBUG PERSONALIZATION]:")
                print(personalization_context)

                # Build AI prompt
                prompt = self.prompt_builder.build_prompt(
                text,
                history,
                memory,
                emotion,
                personalization_context,
                preferences,
                )


                print("[DEBUG PROMPT]:", repr(prompt))
                print("[DEBUG PROMPT LENGTH]:", len(prompt))
            else:
                profile = self.memory.load_profile()
                preferences = self.memory.load_preferences()

                personalization_context = self.personality.build_context(memories=memory,profile=profile,preferences=preferences)

                prompt = self.prompt_builder.build_prompt(
                text,
                history,
                memory,
                emotion,
                personalization_context,
                preferences,
                )

            # Generate response
            answer = self.ai_engine.generate_response(prompt)

            # Save important information
            self.memory.save_if_important(text)

            # Save Genesis response
            self.conversation.add_assistant_message(answer)

            return answer

        # ITEM 18A (L16): the if/elif chain ended without a final
        # return. Any destination the router names that is not one of
        # memory/Internet/knowledge/ai -- and that is not caught by
        # the greeting/exit/reasoning/early returns -- fell off the
        # end of this function, so process_request (and think(), which
        # forwards to it) returned None while annotated `-> str`.
        # default_response() existed for exactly this case and was
        # called by nothing. Unknown destinations now land here, so
        # every control path returns a str.
        return self.default_response()

    def is_greeting(self, text: str) -> bool:
        greetings = [
            "hi",
            "hello",
            "hey",
            "assalamualaikum",
            "aslamualikum"
        ]
        return text.lower() in greetings

    def is_exit(self, text: str) -> bool:
        return text.lower() == "exit"

    def default_response(self) -> str:
        return "I'm not sure about that."

    def is_reasoning_request(self, text: str) -> bool:
        text = text.lower()

        reasoning_keywords = [
            "solve",
            "calculate",
            "how many",
            "how much",
            "why",
            "explain",
            "compare",
            "if",
            "problem"
        ]

        return any(
            keyword in text
            for keyword in reasoning_keywords
        )