class ConversationEngine:

    def __init__(self, max_history=50):
        self.max_history = max_history
        self.history = []

    def add_message(self, role, message=None):

        # If only one argument is provided,
        # treat it as a user message.
        if message is None:
            message = role
            role = "user"

        message = str(message).strip()

        if not message:
            return

        self.history.append({
            "role": str(role),
            "message": message
        })

        if len(self.history) > self.max_history:
            self.history.pop(0)

    def add_user_message(self, message):
        self.add_message("user", message)

    def add_assistant_message(self, message):
        self.add_message("assistant", message)

    def get_history(self):
        return self.history

    def clear(self):
        self.history = []

    def get_last_message(self):
        if self.history:
            return self.history[-1]

        return None

    def get_recent_history(self, limit=10):
        return self.history[-limit:]

    def prepare_message(self, text):
        text = str(text).strip()

        if text:
            self.add_user_message(text)

        return text