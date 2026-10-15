import re
p = re.compile(r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+|my\s+|an?\s+)?(?:empty\s+)?folder\s+['\"]?(.+?)['\"]?$", re.IGNORECASE)
for q in ['delete downloads folder', 'delete the empty folder old_stuff', 'remove folder temp', 'delete folder draft']:
    m = p.match(q)
    print(repr(q), '->', m.group(1) if m else None)
