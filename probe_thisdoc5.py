import sys, re
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine, _strip_politeness
e = WorkflowDecisionEngine()
text = 'search this pdf for climate'
stripped = _strip_politeness(text)
print('stripped:', stripped)
m = re.search(r"^(?:please\s+)?(?:search|find|look\s+for|read|summarize|open|extract\s+(?:the\s+)?text\s+from)\s+(?:this|that|the|these|those)\s+(?P<doc_kind>pdf|document|spreadsheet|sheet|presentation|docx?|xlsx?|file|essay|report|paper|article|book|chapter|page|note)s?\b(?:\s+(?:for|about|with)\s+.+?)?$", stripped, re.IGNORECASE)
print('this_doc match:', m)
print('os decision:', e._detect_os_intent(text))
print('compound:', e._detect_compound_l3_signal(text))
d = e.decide(text)
print('final:', d.get('level'), d.get('mode'), d.get('reason')[:80])
