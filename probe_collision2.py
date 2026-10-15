import sys
sys.path.insert(0, '.')
from agents.workflow_decision import WorkflowDecisionEngine
e = WorkflowDecisionEngine()
queries = [
    'open my essay.docx',
    'open the spreadsheet from yesterday',
    'open the file from my project folder',
    'open my downloads and find the latest PDF',
    'open my documents and open report.docx',
    'open the file called definitely_does_not_exist.xyz',
    'find the section about methodology',
    'open Command Prompt',
    'open please Command Prompt',
    'launch please Command Prompt',
    'start please Command Prompt',
    'open maps', 'launch maps', 'start maps',
    'open File Explorer', 'open please File Explorer',
    'Define machine learning.',
    "What's the difference between correlation and causation?",
    'If all roses are flowers and some flowers fade quickly, can we conclude some roses fade quickly?',
    'Remember that my project is called Genesis.',
    'Look up recent papers on transformer architectures.',
    'Compare these two spreadsheets.',
    'Create a new note: buy milk',
    'What are my notes?',
    'Show my notes',
    'delete the empty folder old_stuff',
    'rename folder draft to final',
    'open windows update',
    'open notifications settings',
    'how much storage do I have left',
    'what did I download yesterday',
    'open the latest PDF from my downloads',
    'show me the most recent spreadsheet in downloads',
    'calculate the average for each column',
    'sum the totals',
    'open Calendar and create a meeting tomorrow at 3pm',
    'open Mail and check my unread messages',
    'open Files and show me my desktop',
    'Quiz me on capitals of Europe.',
    'Write a market analysis for a coffee shop and design a logo.',
    'Study calculus with me and create practice problems.',
]
for q in queries:
    d = e.decide(q)
    print(str(q).ljust(60), '-> L' + str(d.get('level')) + '/' + str(d.get('mode')) + ' intent=' + str(d.get('intent')) + ' target=' + str(d.get('target')))
