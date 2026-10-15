import re
text = 'find the section about methodology'
p = re.compile(
    r"^(?:please\s+)?"
    r"(?:search|find|look\s+for|read|summarize|open|"
    r"extract\s+(?:the\s+)?text\s+from|locate|highlight)\s+"
    r"(?:the\s+|this|that|these|those|my|our)\s+"
    r"(?P<doc_kind>section|chapter|page|paragraph|line|"
    r"figure|table|heading|note|"
    r"pdf|document|spreadsheet|sheet|"
    r"presentation|docx?|xlsx?|file|essay|report|"
    r"paper|article|book)s?\b"
    r"(?:\s+(?:for|about|with)\s+.+?)?$",
    re.IGNORECASE,
)
m = p.match(text)
print('match:', m, 'groups:', m.groupdict() if m else None)
