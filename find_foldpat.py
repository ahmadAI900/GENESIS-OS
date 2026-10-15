import re
src = open('agents/workflow_decision.py').read()
# Find the open_folder_std match
for i, line in enumerate(src.split('\n'), 1):
    if 'open_folder_std' in line:
        print(i, ':', line[:200])
