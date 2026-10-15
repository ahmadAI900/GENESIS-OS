class ResearchQuality:

    def check(self, report, sources):

        issues = []

        # Check report exists
        if not report or not report.strip():
            issues.append("Empty research report.")

        # Check minimum useful length
        if len(report.split()) < 50:
            issues.append("Research report is too short.")

        # Check source section
        source_words = [
            "source",
            "sources",
            "references"
        ]

        if not any(
            word in report.lower()
            for word in source_words
        ):
            issues.append(
                "Research report does not clearly mention sources."
            )

        # Check that source information exists
        if not sources:
            issues.append(
                "No sources were collected."
            )

        return {
            "passed": len(issues) == 0,
            "issues": issues
        }