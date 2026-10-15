import re
text = 'find the section about methodology'
# (?:the\s+|this|that|these|those|my|our)\s+
# "the" is followed by " section" - so "the" + space + " " + "section"
# The alternation is (?:the\s+|this|that|...)
# "the\s+" matches "the " (the + one whitespace)
# Then \s+ requires another whitespace
# But "the " consumed the only space. Then "section" follows.
# So we need the first alternation to also handle the trailing \s+
# Actually the issue is that the alternation is at the same level as \s+
# So (?:the\s+|this|that|...)\s+ requires TWO whitespace runs.
p = re.compile(r"^(?:search|find|look\s+for)\s+(?:the\s+|this|that|these|those|my|our)\s+(?:section|chapter)\b")
print('inline:', p.match(text))
p_alt = re.compile(r"^(?:search|find|look\s+for)\s+(?:the|this|that|these|those|my|our)\s+(?:section|chapter)\b")
print('no \s+ after the:', p_alt.match(text))
