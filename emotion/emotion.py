class EmotionEngine:

    def __init__(self):
        print("[Emotion] Engine initialized")

        self.emotion_keywords = {
            "happy": [
                "happy",
                "excited",
                "great",
                "awesome",
                "wonderful",
                "amazing",
                "glad",
                "love this"
            ],

            "sad": [
                "sad",
                "unhappy",
                "depressed",
                "cry",
                "crying",
                "upset",
                "heartbroken"
            ],

            "angry": [
                "angry",
                "mad",
                "furious",
                "hate",
                "annoyed",
                "irritated"
            ],

            "frustrated": [
                "frustrated",
                "frustrating",
                "fed up",
                "can't solve",
                "cannot solve"
            ],

            "confused": [
                "confused",
                "don't understand",
                "do not understand",
                "what does this mean",
                "i'm lost",
                "i am lost"
            ],

            "worried": [
                "worried",
                "nervous",
                "scared",
                "afraid",
                "anxious",
                "concerned"
            ],

            "bored": [
                "bored",
                "boring",
                "nothing to do",
                "i'm bored",
                "i am bored"
            ],

            "tired": [
                "tired",
                "exhausted",
                "sleepy",
                "so tired",
                "very tired"
            ]
        }

    def detect(self, text: str) -> str:

        if not text:
            return "neutral"

        text = text.lower().strip()

        detected_emotions = []

        for emotion, keywords in self.emotion_keywords.items():

            for keyword in keywords:

                if keyword in text:
                    detected_emotions.append(emotion)
                    break

        if not detected_emotions:
            return "neutral"

        return detected_emotions[0]