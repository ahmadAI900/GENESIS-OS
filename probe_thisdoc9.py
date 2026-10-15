import re
text = 'find the section about methodology'
# Try in pieces
p1 = re.compile(r"^(?:search|find|look\s+for)\s+", re.IGNORECASE)
print('1:', p1.match(text))
p2 = re.compile(r"^(?:search|find|look\s+for)\s+(?:the\s+|this|that|these|those|my|our)\s+", re.IGNORECASE)
print('2:', p2.match(text))
p3 = re.compile(r"^(?:search|find|look\s+for)\s+(?:the\s+|this|that|these|those|my|our)\s+(?:section|chapter)\b", re.IGNORECASE)
print('3:', p3.match(text))
p4 = re.compile(r"^(?:search|find|look\s+for)\s+(?:the\s+|this|that|these|those|my|our)\s+(?:section|chapter)\b(?:\s+(?:for|about|with)\s+.+?)?$", re.IGNORECASE)
print('4:', p4.match(text))
p5 = re.compile(r"^(?:search|find|look\s+for)\s+(?:the\s+|this|that|these|those|my|our)\s+(?:section|chapter)\b(?:\s+(?:for|about|with)\s+[\"']?[\\w\\s]+[\"']?)?$", re.IGNORECASE)
print('5:', p5.match(text))
