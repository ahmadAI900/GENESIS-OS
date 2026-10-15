class ResultValidator:

    REQUIRED_FIELDS = [
        "agent",
        "task",
        "success",
        "response",
        "metadata"
    ]

    def validate(self, result):

        missing = []

        for field in self.REQUIRED_FIELDS:

            if field not in result:
                missing.append(field)

        return {
            "valid": len(missing) == 0,
            "missing": missing
        }