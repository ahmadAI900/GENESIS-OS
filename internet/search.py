try:
    from ddgs import DDGS
except ImportError:
    DDGS = None


class InternetSearch:

    def search(self, query):
        print(f"[Internet] Searching: {query}")

        try:
            if DDGS is None:
                return {"title": "Search Unavailable", "content": "The optional web-search provider is not installed.", "url": ""}
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=1))

            if results:
                return {
                    "title": results[0]["title"],
                    "content": results[0]["body"],
                    "url": results[0]["href"]
                }

            return {
                "title": "No Result",
                "content": "I couldn't find any information.",
                "url": ""
            }

        except Exception as e:
            return {
                "title": "Search Error",
                "content": str(e),
                "url": ""
            }


    def search_multiple(self, query, max_results=5):
        print(f"[Internet] Multi-source search: {query}")

        try:
            if DDGS is None:
                return [{"title": "Search Unavailable", "content": "The optional web-search provider is not installed.", "url": ""}]
            with DDGS() as ddgs:
                results = list(
                    ddgs.text(
                        query,
                        max_results=max_results
                    )
                )

            formatted_results = []

            for result in results:
                formatted_results.append({
                    "title": result.get("title", ""),
                    "content": result.get("body", ""),
                    "url": result.get("href", "")
                })

            return formatted_results

        except Exception as e:
            return [{
                "title": "Search Error",
                "content": str(e),
                "url": ""
            }]