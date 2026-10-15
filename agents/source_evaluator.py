from urllib.parse import urlparse


class SourceEvaluator:

    def evaluate(self, source):

        url = source.get("url", "")
        title = source.get("title", "")

        domain = urlparse(url).netloc.lower()

        score = 3
        reasons = []

        # Government sources
        if domain.endswith(".gov"):
            score = 5
            reasons.append("Government source")

        # Educational institutions
        elif domain.endswith(".edu"):
            score = 5
            reasons.append("Educational institution")

        # Research organizations
        elif any(
            keyword in domain
            for keyword in [
                "research",
                "science",
                "institute"
            ]
        ):
            score = 4
            reasons.append("Research-oriented source")

        # Known general high-quality organizations
        elif any(
            keyword in domain
            for keyword in [
                "who.int",
                "nature.com",
                "sciencedirect.com",
                "ieee.org",
                "acm.org"
            ]
        ):
            score = 5
            reasons.append("Established scientific organization")

        else:
            reasons.append("General web source")

        return {
            "title": title,
            "url": url,
            "score": score,
            "reasons": reasons
        }