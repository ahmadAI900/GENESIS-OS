import re
text = 'open please Command Prompt'
# First regex: leading politeness + verb
pattern1 = (
    r"^(?:please\s+|kindly\s+|can\s+you\s+|"
    r"could\s+you\s+|would\s+you\s+|"
    r"i\s+want\s+(?:you\s+)?to\s+|"
    r"i\s+need\s+(?:you\s+)?to\s+|"
    r"i'd\s+like\s+(?:you\s+)?to\s+|"
    r"i\s+would\s+like\s+(?:you\s+)?to\s+|"
    r"let's\s+|let\s+us\s+|"
    r"do\s+me\s+a\s+fav(?:o)ur\s+and\s+)?"
    r"(?:please\s+|kindly\s+)?"
    r"(?:open|launch|start|fire\s+up|"
    r"spin\s+up|boot\s+up|bring\s+up|"
    r"start\s+up|pop\s+open|pop\s+up)\s+"
)
after1 = re.sub(pattern1, "", text.strip(), count=1, flags=re.IGNORECASE)
print('after1:', repr(after1))
# Second regex: verb + please
pattern2 = (
    r"^(?:open|launch|start|fire\s+up|"
    r"spin\s+up|boot\s+up|bring\s+up|"
    r"start\s+up|pop\s+open|pop\s+up)\s+"
    r"(?:please|kindly)\s+"
)
after2 = re.sub(pattern2, "", after1, count=1, flags=re.IGNORECASE)
print('after2:', repr(after2))
