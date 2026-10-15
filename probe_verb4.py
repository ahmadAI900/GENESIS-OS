import re
text = 'open please Command Prompt'
pattern = (
    r"^(?:open|launch|start|fire\s+up|"
    r"spin\s+up|boot\s+up|bring\s+up|"
    r"start\s+up|pop\s+open|pop\s+up)\s+"
    r"(?:please|kindly)\s+"
)
m = re.match(pattern, text, re.IGNORECASE)
print('match:', m)
print('after strip:', re.sub(pattern, "", text, count=1, flags=re.IGNORECASE))
