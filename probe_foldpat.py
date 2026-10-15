import re
p = re.compile(
    r"(?:open|show(?:\s+me)?|explore|go\s+to|take\s+me\s+to|navigate\s+to)\s+"
    r"(?:my\s+|the\s+)?"
    r"(downloads|download|documents|document|desktop|pictures|music|"
    r"videos|project|workspace|reports|invoices|archive|backups|"
    r"workspace|temp|scratch|home|root|notes)"
    r"(?:\s+folder)?$",
    re.IGNORECASE
)
for q in ['open my downloads', 'navigate to my documents', 'go to my downloads', 'navigate to my workspace', 'go to my reports', 'navigate to my projects', 'navigate to my home', 'navigate to my root']:
    m = p.match(q)
    print(repr(q), '->', m.group(1) if m else None)
