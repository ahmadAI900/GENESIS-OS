import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
r = BenchmarkRunner()
text = "What's the difference between correlation and causation?"
d = r._engine.decide(text)
print('decision:', d)
