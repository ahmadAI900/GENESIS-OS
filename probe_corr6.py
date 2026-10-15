import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
r = BenchmarkRunner()
print('registry agents:', [a.name for a in r._registry.get_all_agents()])
print('engine registry is runner registry:', r._engine._registry is r._registry)
d = r._engine.decide("What's the difference between correlation and causation?")
print('level:', d.get('level'), 'mode:', d.get('mode'), 'reason:', d.get('reason'))
