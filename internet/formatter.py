class Formatter:
    def format(self, data):
        # Item 27B (L7): the old code read "tittle" -- a typo -- so
        # every search result rendered its title as the "Unknown"
        # placeholder, whatever the real title was. Read "title" first
        # and tolerate the legacy "tittle" spelling.
        title = data.get("title") or data.get("tittle") or "Unknown"
        content = data.get("content","No information avaliable.")
        url = data.get("url","")
        response = f"""According to my internet search:
        {title} {content}"""
        if url:
            response += f"\nSource:{url}"
        return response 