"""
Genesis OS — Level 3.11
Web Intelligence.

Real internet search integrated as a Level 3 OS capability.

This module deliberately REUSES the existing Genesis internet
stack (internet.search.InternetSearch). It does not duplicate
any provider logic; it packages search results into the
standard verified OS result contract.
"""

from __future__ import annotations


class WebIntelligence:

    VERSION = "3.11.0"

    MAX_RESULTS = 5

    def __init__(self, search=None):
        # Reuse the EXISTING internet infrastructure.
        if search is not None:
            self._search = search
        else:
            from internet.search import InternetSearch

            self._search = InternetSearch()

    def research(self, query, max_results: int = MAX_RESULTS) -> dict:
        """
        Search the live internet and return structured,
        ranked results.

        This is a READ operation on the network. It never
        fabricates content: when the network or provider is
        unavailable the result honestly reports failure.
        """

        if not isinstance(query, str) or not query.strip():
            return {
                "success": False,
                "operation": "web.research",
                "error": "A search query is required.",
                "executed": False,
                "verified": False,
            }

        query_text = query.strip()

        try:
            raw_results = self._search.search_multiple(
                query_text,
                max_results=max(1, min(int(max_results), 10)),
            )
        except Exception as error:
            return {
                "success": False,
                "operation": "web.research",
                "query": query_text,
                "error": f"Live web search failed: {error}",
                "executed": True,
                "verified": False,
            }

        if not isinstance(raw_results, list):
            return {
                "success": False,
                "operation": "web.research",
                "query": query_text,
                "error": "The search provider returned an invalid response.",
                "executed": True,
                "verified": False,
            }

        results = []

        for item in raw_results[:max_results]:
            if not isinstance(item, dict):
                continue

            title = str(item.get("title", "") or "").strip()
            body = str(item.get("content", item.get("body", "")) or "").strip()
            url = str(item.get("url", item.get("href", "")) or "").strip()

            if not title and not body:
                continue

            results.append({
                "title": title or url or "(untitled result)",
                "snippet": body[:400],
                "url": url,
            })

        unavailable_markers = (
            "search unavailable",
            "not installed",
        )

        degraded = any(
            any(marker in r["title"].lower() or marker in r["snippet"].lower()
                for marker in unavailable_markers)
            for r in results
        )

        if not results:
            return {
                "success": False,
                "operation": "web.research",
                "query": query_text,
                "error": "No results were returned for this query.",
                "executed": True,
                "verified": False,
            }

        if degraded:
            return {
                "success": False,
                "operation": "web.research",
                "query": query_text,
                "error": (
                    "The optional web-search provider is not "
                    "installed. Install 'duckduckgo_search' to "
                    "enable live research."
                ),
                "executed": False,
                "verified": False,
            }

        lines = [
            f"{i}. {r['title']}"
            + (f" - {r['snippet'][:160]}" if r["snippet"] else "")
            for i, r in enumerate(results, start=1)
        ]

        return {
            "success": True,
            "operation": "web.research",
            "query": query_text,
            "results": results,
            "result_count": len(results),
            "summary": "\n".join(lines),
            "executed": True,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "live_provider_response",
            "message": (
                f"Found {len(results)} live result(s) for "
                f"'{query_text}'."
            ),
        }
