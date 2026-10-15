import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
r = BenchmarkRunner()
e = r._engine
text = "what is the difference between correlation and causation"
print('comp signal:', e._detect_compound_l3_signal(text))
print('os:', e._detect_os_intent(text))
print('conversational:', e._is_conversational_or_educational(text))
# The engine's decide method - need to trace step by step
import re
normalized = e._normalize_text(text)
print('normalized:', repr(normalized))
# Check the conversational guard more carefully
stripped = text  # politeness already stripped
print('is conversational after normalize:', e._is_conversational_or_educational(stripped))
d = e.decide(text)
print('decision level:', d.get('level'), 'mode:', d.get('mode'), 'reason:', d.get('reason'))
