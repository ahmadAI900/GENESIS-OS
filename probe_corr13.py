import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
r = BenchmarkRunner()
text = "What's the difference between correlation and causation?"
d = r._engine.decide(text)
print('level:', d.get('level'), 'mode:', d.get('mode'), 'reason:', d.get('reason'))
