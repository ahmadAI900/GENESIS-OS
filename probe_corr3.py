import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
r = BenchmarkRunner()
d = r._engine.decide("What's the difference between correlation and causation?")
print('level:', d.get('level'), 'mode:', d.get('mode'))
