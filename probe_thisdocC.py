import re
text = "find the section about methodology"
p = re.compile(
    r"^(?:please\s+)?"
    r"(?:search|find|look\s+for|read|summarize|open|"
    r"extract\s+(?:the\s+)?text\s+from|locate|highlight)\s+"
    r"(?:this|that)\s+"
    r"(?P<doc_kind>pdf|document|spreadsheet|sheet|"
    r"presentation|docx?|xlsx?|file|essay|report|"
    r"paper|article|book)"
    r"(?:\s+(?:for|about|with)\s+.+?)?$"
    r"|"
    r"(?:the)\s+"
    r"(?P<doc_kind2>section|chapter|page|paragraph|line|"
    r"figure|table|heading|note)"
    r"(?:\s+(?:for|about|with)\s+.+?)?$",
    re.IGNORECASE,
)
m = p.match(text)
print('match:', m, 'groups:', m.groupdict() if m else None)
