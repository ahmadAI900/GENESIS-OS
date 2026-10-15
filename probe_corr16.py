import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
r = BenchmarkRunner()
text = "What's the difference between correlation and causation?"
result = r._engine.decide(text)
print('result:', result.get('level'), result.get('mode'), 'reason:', result.get('reason')[:100])
