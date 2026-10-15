import re
text = "what's in the clipboard"
p = re.compile(
    r"^(?:what(?:'s|s| is)\s+(?:in|on)\s+(?:the\s+)?clipboard|"
    r"read\s+(?:the\s+)?clipboard|paste\s+from\s+clipboard|show\s+clipboard|"
    r"(?:show|open)\s+(?:the\s+)?clipboard)$",
    re.IGNORECASE
)
m = p.match(text)
print('match:', m)
