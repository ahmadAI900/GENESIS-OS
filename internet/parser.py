class Parser:

    def extract(self, data):
        title = data.get("title","Unknown")
        content = data.get("content", "No information Avaliable.")
        url = data.get("url","")
        return {
            "title": title,
            "content": content,
            "url": url
        }