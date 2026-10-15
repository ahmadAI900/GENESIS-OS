import re
text = "search this pdf for 'climate'"
p = re.compile(
    r"^(?:please\s+)?"
    r"(?:search|find|look\s+for|read|summarize|open|"
    r"extract\s+(?:the\s+)?text\s+from)\s+"
    r"(?:this|that|the|these|those)\s+"
    r"(?P<doc_kind>pdf|document|spreadsheet|sheet|"
    r"presentation|docx?|xlsx?|file|essay|report|"
    r"paper|article|book|chapter|page|note)s?\b"
    r"(?:\s+(?:for|about|with)\s+.+?)?$",
    re.IGNORECASE,
)
print('match:', p.match(text))
text2 = "find the section about methodology"
print('match:', p.match(text2))
text3 = "search this PDF for climate"
print('match:', p.match(text3))
