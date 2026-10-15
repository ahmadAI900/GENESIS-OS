class Formatter:
    def format(self, data):
        title = data.get("tittle","Unknown")
        content = data.get("content","No information avaliable.")
        url = data.get("url","")
        response = f"""According to my internet search:
        {title} {content}"""
        if url:
            response += f"\nSource:{url}"
        return response 