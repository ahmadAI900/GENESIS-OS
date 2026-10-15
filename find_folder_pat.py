import re
src = open('agents/workflow_decision.py').read()
# Find the folder-open pattern
for m in re.finditer(r'r"\(open[^"]*\)', src):
    print(m.group()[:300])
    print('---')
