import json
import os
import re
from datetime import datetime


def _genesis_debug() -> bool:
    """Return True when GENESIS_DEBUG=1 is set.

    Mirror of brain._genesis_debug — kept local so memory
    can be imported without pulling the whole Brain.
    """
    return os.environ.get("GENESIS_DEBUG") == "1"


class MemoryManager:
    def __init__(self):
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.memories = []

    def _get_file_path(self, filename: str) -> str:
        return os.path.join(self.base_path, filename)

    def load_memory(self, filename: str) -> dict:
        path = self._get_file_path(filename)
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_memory(self, filename: str, data: dict) -> None:
        path = self._get_file_path(filename)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)

    # -------------------------
    # Profile
    # -------------------------

    def load_profile(self) -> dict:
        return self.load_memory("profile.json")

    def save_profile(self, profile_data: dict) -> None:
        self.save_memory("profile.json", profile_data)

    # -------------------------
    # Goals
    # -------------------------

    def load_goals(self) -> dict:
        return self.load_memory("goals.json")

    def save_goals(self, goals_data: dict) -> None:
        self.save_memory("goals.json", goals_data)

    # -------------------------
    # Preferences
    # -------------------------

    def load_preferences(self) -> dict:
        return self.load_memory("preferences.json")

    def save_preferences(self, preferences_data: dict) -> None:
        self.save_memory("preferences.json", preferences_data)

    # -------------------------
    # Knowledge
    # -------------------------

    def load_knowledge(self) -> dict:
        return self.load_memory("knowledge.json")

    def save_knowledge(self, knowledge_data: dict) -> None:
        self.save_memory("knowledge.json", knowledge_data)

    # -------------------------
    # Learn User Information
    # -------------------------

    def learn_profile(self, text: str):
        if _genesis_debug():
            print("[DEBUG] learn_preference() called")
        text = text.strip()
        if _genesis_debug():
            print("[DEBUG PREFERENCE TEXT]:", repr(text))

        # Name
        match = re.match(r"^my name is\s+(.+)$", text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()

            profile = self.load_profile()
            profile["user_name"] = name
            self.save_profile(profile)

            return f"Nice to meet you, {name}. I'll remember your name."

        # Age
        match = re.match(r"^my age is\s+(\d+)$", text, re.IGNORECASE)
        if match:
            age = int(match.group(1))

            profile = self.load_profile()
            profile["age"] = age
            self.save_profile(profile)

            return f"I'll remember that you are {age} years old."

        # Location
        match = re.match(r"^i live in\s+(.+)$", text, re.IGNORECASE)
        if match:
            location = match.group(1).strip()

            profile = self.load_profile()
            profile["location"] = location
            self.save_profile(profile)

            return f"I'll remember that you live in {location}."

        # Profession
        match = re.match(r"^i am a[n]?\s+(.+)$", text, re.IGNORECASE)
        if match:
            profession = match.group(1).strip()

            profile = self.load_profile()
            profile["profession"] = profession
            self.save_profile(profile)

            return f"I'll remember that you're a {profession}."

        # Goal
        match = re.match(r"^my goal is\s+(.+)$", text, re.IGNORECASE)
        if match:
            goal = match.group(1).strip()

            goals = self.load_goals()
            goals["main_goal"] = goal
            self.save_goals(goals)

            return "I'll remember your goal."

        return None


    def learn_preference(self, text: str):
        if _genesis_debug():
            print("[DEBUG] learn_preference() called")

        text = text.strip()
        if _genesis_debug():
            print("[DEBUG PREFERENCE TEXT]:", repr(text))

        lower_text = text.lower()

        # Remove common update words
        update_prefixes = [
            "actually, ",
            "actually ",
            "now ",
            "i now ",
        ]

        cleaned_text = lower_text

        for prefix in update_prefixes:
            if cleaned_text.startswith(prefix):
                cleaned_text = cleaned_text[len(prefix):]
                break

        positive_prefixes = [
            "i prefer ",
            "i like ",
            "i love ",
            "i enjoy ",
            "i favor ",
            "i am fond of ",
            "i'm fond of ",
            "i am a fan of ",
            "i'm a fan of ",
            "my favorite is "
        ]

        negative_prefixes = [
            "i don't like ",
            "i dislike ",
            "i hate ",
            "i can't stand ",
            "i cant stand ",
            "i am not a fan of ",
            "i'm not a fan of ",
            "i despise ",
            "i detest "
        ]

        preference = None
        liked = True

    # -------------------------
    # Positive preference
    # -------------------------

        for prefix in positive_prefixes:
            if cleaned_text.startswith(prefix):

                preference = cleaned_text[len(prefix):].strip()
                liked = True
                break

    # -------------------------
    # Negative preference
    # -------------------------

        if preference is None:
            for prefix in negative_prefixes:
                if cleaned_text.startswith(prefix):

                    preference = cleaned_text[len(prefix):].strip()
                    liked = False
                    break

    # Not a preference statement
        if preference is None:
            if _genesis_debug():
                print("[DEBUG] Not a preference statement.")
            return None

    # Remove punctuation
        preference = preference.rstrip(".!?").strip()

    # Remove update words from the END
        preference = re.sub(
            r"\s+(now|anymore)$",
            "",
            preference,
            flags=re.IGNORECASE
        ).strip()

        if not preference:
            return None

    # --------------------------------
    # Normalize capitalization
    # --------------------------------

        preferences = self.load_preferences()

        if not isinstance(preferences, dict):
            preferences = {}

        normalized = preference.lower()

        existing_key = None

    # Find existing preference ignoring capitalization
        for key in preferences.keys():
            if str(key).strip().lower() == normalized:
                existing_key = key
                break

    # --------------------------------
    # Update existing preference
    # --------------------------------

        if existing_key is not None:

            preferences[existing_key] = liked

        # Remove duplicate capitalization variants
            for key in list(preferences.keys()):
                if key != existing_key:
                    if str(key).strip().lower() == normalized:
                        del preferences[key]

            clean_preference = existing_key

        else:

        # Store a clean version
            clean_preference = preference.strip()

            preferences[clean_preference] = liked

    # Save ONCE
        self.save_preferences(preferences)

        if _genesis_debug():
            print(
                "[DEBUG] Preference updated:",
                clean_preference,
                "=",
                liked
            )

            print("[DEBUG] Preferences:", preferences)

        if liked:
            return f"I'll remember that you prefer {clean_preference}."

        return f"I'll remember that you don't like {clean_preference}."

    def is_preference_relevant(self, text: str) -> bool:
        """
        Check whether the current message is relevant
        to the user's stored preferences.
        """

        if not text:
            if _genesis_debug():
                print("[DEBUG] Preference relevance: FALSE (empty text)")
            return False

        text = str(text).strip().lower()

        if _genesis_debug():
            print("[DEBUG RELEVANCE TEXT]:", repr(text))

        preference_keywords = [
            "prefer",
            "favorite",
            "favourite",
            "like",
            "love",
            "hate",
            "dislike",
            "recommend",
            "recommendation",
            "suggest",
            "suggestion",
            "choose",
            "choice",
            "should i use",
            "which language",
            "what language",
            "programming language",
            "new project",
        ]

        for keyword in preference_keywords:
            if keyword in text:
                if _genesis_debug():
                    print(
                        f"[DEBUG] Preference relevance: TRUE ({keyword})"
                    )
                return True

        if _genesis_debug():
            print("[DEBUG] Preference relevance: FALSE")
        return False

    def detect_preference_type(self, preference: str) -> str:
        preference_lower = preference.lower()

        programming_languages = [
            "python",
            "java",
            "javascript",
            "typescript",
            "c++",
            "c#",
            "rust",
            "go",
            "php",
            "ruby"
        ]

        if preference_lower in programming_languages:
            return "programming_language"

        return "general"

    # -------------------------
    # Recall User Information
    # -------------------------

    def recall_profile(self, text: str):
        text = text.strip().lower()
        text = text.rstrip("!?.,")

        profile = self.load_profile()
        goals = self.load_goals()

        if text == "what is my name":
            if "user_name" in profile:
                return f"Your name is {profile['user_name']}."
            return "I don't know your name yet."

        elif text == "how old am i":
            if "age" in profile:
                return f"You are {profile['age']} years old."
            return "I don't know your age yet."

        elif text == "where do i live":
            if "location" in profile:
                return f"You live in {profile['location']}."
            return "I don't know where you live yet."

        elif text == "what is my profession":
            if "profession" in profile:
                return f"Your profession is {profile['profession']}."
            return "I don't know your profession yet."

        elif text == "what is my goal":
            if "main_goal" in goals:
                return f"Your main goal is {goals['main_goal']}."
            return "I don't know your goal yet."

        elif text == "what do you know about me?":
            result = []

            if "user_name" in profile:
                result.append(f"Name: {profile['user_name']}")

            if "age" in profile:
                result.append(f"Age: {profile['age']}")

            if "location" in profile:
                result.append(f"Location: {profile['location']}")

            if "profession" in profile:
                result.append(f"Profession: {profile['profession']}")

            if "main_goal" in goals:
                result.append(f"Goal: {goals['main_goal']}")

            if not result:
                return "I don't know anything about you yet."

            return "\n".join(result)

        return None

    def get_relevent_memory(self, query, category=None, limit=5):
        query_words = set(query.lower().split())

        data = self.load_memory("memory.json")

        if isinstance(data, list):
            memories = data
        elif isinstance(data, dict):
            memories = data.get("memories", [])
        else:
            memories = []

        scored_memories = []

        for memory in memories:
            if not isinstance(memory, dict):
                continue

            text = memory.get("message", "").lower()
            memory_category = memory.get("category", "").lower()

            if category and memory_category != category.lower():
                continue

            memory_words = set(text.split())

            score = len(
            query_words.intersection(memory_words))
        

            if score > 0:
                scored_memories.append({
                "score": score,
                "memory": memory
            })

        # Sort AFTER checking all memories
        scored_memories.sort(key=lambda item: item["score"],reverse=True)

        return [
            item["memory"]
            for item in scored_memories[:limit]
        ]


    def should_remember(self, text: str) -> bool:
        if not text:
            return False
        text = text.strip().lower()
        if len(text) < 5:
            return False

        ignored_message = {
            "hello","hi","hey","thanks","thank you","ok","okay","bye"
        }

        if text in ignored_message:
            return False
        memory_indicators = ["my name is","i am ", "i live","i love","i prefer", "my goal is", "i want to","i study ","i work","my project is","my favorite"]

        for indicator in memory_indicators:
            if indicator in text:
                return True
        return False
    def memory_exists(self, text : str, filename:str = "memory.json") -> bool:
        if not text:
            return False
        new_text = text.strip().lower()
        data = self.load_memory(filename)
        if isinstance(data, list):
            memories = data
        elif isinstance(data, dict):
            memories = data.get("memories", [])
        else:
            memories = []

        for item in memories:
            if isinstance(item, dict):
                exsisting_text = item.get("message", "")
                if not exsisting_text:exsisting_text=item.get("content","")
            else:
                exsisting_text = str(item)
            if exsisting_text.strip().lower() == new_text:
                return True
        return False
    def save_if_important(self, text:str, filename : str = "memory.json") -> bool:
        if not self.should_remember(text):
            return False
        if self.memory_exists(text, filename):
            return False
        data = self.load_memory(filename)
        if not isinstance(data, list):
            memories = []
        else:
            memories = data
        category = self.detect_memory_category(text)
        memories.append({
            "message": text,
            "category": category
        })

        self.save_memory(filename, memories)
        return True

    def detect_memory_category(self, text: str) -> str:
        text = text.lower()
        if "my name is" in text:
            return "profile"
        if "i live in" in text:
            return "profile"
        if "i am" in text:
            return "profile"
        if "my favorite " in text:
            return "preference"
        if "i like " in text :
            return "preference"
        if "i love " in text:
            return "preference"
        if "my goal " in text:
            return "goal"
        if "i want to " in text:
            return "goal"
        if "my project " in text:
            return "project"
        return "general"

    def get_preferences(self):
        preferences = self.load_preferences()

        if not isinstance(preferences, dict):
            return {}

        return preferences

    def update_preference(self, preference: str, liked: bool = True):
        preference = preference.strip()

        if not preference:
            return False

        preferences = self.get_preferences()

        if not isinstance(preferences, dict):
            preferences = {}

        normalized = preference.lower()

        existing_key = None

        # Find existing preference ignoring capitalization
        for key in preferences.keys():
            if str(key).strip().lower() == normalized:
                existing_key = key
                break

        # Update existing preference (replace in place) or append
        # when absent. Item 26A (L2): the old code fell out of a
        # "remove duplicates" for/else -- whose ELSE always ran,
        # because the loop had no break -- and appended
        # preferences[preference] = liked under the caller's
        # spelling, so updating an EXISTING preference whose stored
        # key differed in case/spacing grew a duplicate entry
        # instead of replacing it.
        if existing_key is not None:
            preferences[existing_key] = liked
            kept_key = existing_key
        else:
            preferences[preference] = liked
            kept_key = preference

        # Remove any OTHER case/space variants that duplicate it.
        for key in list(preferences.keys()):
            if key != kept_key and str(key).strip().lower() == normalized:
                del preferences[key]

        self.save_preferences(preferences)

        if _genesis_debug():
            print(
                f"[DEBUG] Preference updated: "
                f"{preference} = {liked}"
            )

        return True

    def get_relevant_preferences(self, text: str):
        preferences = self.get_preferences()

        if not preferences:
            return []

        relevant = []

        query_words = set(text.lower().split())

        for preference, liked in preferences.items():
            preference_words = set(preference.lower().split())

            if query_words.intersection(preference_words):
                relevant.append({
                    "preference": preference,
                    "liked": liked
                })

        return relevant

    def build_preference_context(self, preferences):
        if not preferences:
            return ""

        lines = ["User preferences:"]

        for item in preferences:
            # Item 26B (L3): branch on the TYPE first. The old code
            # only bound preference/liked inside the dict branch but
            # then tested `if preference:` for every item -- a str
            # item raised UnboundLocalError (or reused the previous
            # dict's value and vanished).
            if isinstance(item, dict):
                preference = item.get("preference", "")
                liked = item.get("liked", True)

                if preference:
                    if liked:
                        lines.append(f"- User prefers {preference}.")
                    else:
                        lines.append(f"- User does not like {preference}.")

            elif isinstance(item, str):
                lines.append(f"- User prefers {item}.")

        return "\n".join(lines)

    def detect_preference_type(self, preference: str) -> str:
        preference_lower = preference.strip().lower()

        programming_languages = {
            "python",
            "java",
            "javascript",
            "typescript",
            "c++",
            "c#",
            "rust",
            "go",
            "php",
            "ruby",
            "swift",
            "kotlin"
        }

        if preference_lower in programming_languages:
            return "programming_language"

        return "general"
if __name__ == "__main__":
    memory = MemoryManager()

    print(memory.is_preference_relevant("Recommend a programming language for my new project."))

    print( memory.is_preference_relevant("What is the capital of France?"))



            
