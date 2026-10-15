import re
text = 'find the section about methodology'
# Try simpler patterns
p1 = re.compile(r"^(?:search|find)\s+", re.IGNORECASE)
print('1:', p1.match(text))
p2 = re.compile(r"^(?:search|find)\s+(?:the\s+)", re.IGNORECASE)
print('2:', p2.match(text))
p3 = re.compile(r"^(?:search|find)\s+(?:the\s+)section\b", re.IGNORECASE)
print('3:', p3.match(text))
p4 = re.compile(r"^(?:search|find)\s+(?:the\s+)section\b(?:\s+(?:for|about|with)\s+.+?)?$", re.IGNORECASE)
print('4:', p4.match(text))
