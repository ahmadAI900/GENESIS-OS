import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
for q in [
    'open File Explorer',
    'open my essay.docx',
    'open the spreadsheet from yesterday',
    'open my downloads and find the latest PDF',
    'open my documents and open report.docx',
    'open the file called definitely_does_not_exist.xyz',
    'open the file from my project folder',
    'search for Python tutorials',
    'look up the weather in London',
    'search for best laptops 2026',
    'bing how to learn programming',
    'find the section about methodology',
]:
    d = e.decide(q)
    print(str(q[:55]).ljust(60), '-> L' + str(d.get('level')) + '/' + str(d.get('mode')) + ' intent=' + str(d.get('intent')) + ' target=' + str(d.get('target')))
