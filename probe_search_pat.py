import re
p = re.compile(r"(?:find|search\s+for|show\s+me|locate)\s+(?:the\s+|my\s+)?(?:files?\s+(?:named\s+|related\s+to\s+|about\s+)?|documents?\s+|presentation\s+|essay\s+|spreadsheet\s+|sheet\s+|pdf\s+)?['\"]?(.+?)['\"]?$", re.IGNORECASE)
for q in ['search for Python tutorials', 'search for best laptops 2026', 'look up the weather in London', 'find the section about methodology', 'find the largest file in my downloads', 'bing how to learn programming']:
    m = p.match(q)
    print(q, '->', m.group(1) if m else None)
