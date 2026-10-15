import sys, re
sys.path.insert(0, '.')
from agents.workflow_decision import _FILESYSTEM_ANCHOR_RE
text = "what is in the clipboard"
print('anchor match:', _FILESYSTEM_ANCHOR_RE.search(text))
