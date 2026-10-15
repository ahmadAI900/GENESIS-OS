import re
p = re.compile(r"(?:read|open|inspect|check)\s+(?:the\s+)?(?:file\s+)?['\"]?([^'\"]+\.(?:txt|csv|json|xml|yaml|yml|pdf|docx?|xlsx?|xlsm?|pptx?|py|js|ts))['\"]?", re.IGNORECASE)
for q in ['open File Explorer', 'open report.docx', 'open my essay.docx', 'open my downloads and open report.docx']:
    m = p.search(q)
    print(q, '->', m.group(1) if m else None)
