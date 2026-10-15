import sys, os
sys.path.insert(0, r'C:\Users\Muhammad\Desktop\gemini_cli\backend')
os.chdir(r'C:\Users\Muhammad\Desktop\gemini_cli\backend')
from agents.workflow_decision import WorkflowDecisionEngine
de = WorkflowDecisionEngine()
for text in ['open chrome', 'write a poem', 'write a hello world', 'write Hello from Genesis', 'write a sentence about cats', 'type hello']:
    d = de.decide(text)
    print(repr(text), '->', 'level=', d.get('level'), 'mode=', d.get('mode'), 'intent=', d.get('intent'), 'target=', d.get('target'))