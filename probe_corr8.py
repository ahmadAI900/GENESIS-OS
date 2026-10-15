import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
from benchmark.scenarios import BenchmarkScenario
r = BenchmarkRunner()
s = BenchmarkScenario(
    scenario_id='test',
    category='conversation',
    user_request="What's the difference between correlation and causation?",
    expected_level=1,
    expected_mode='conversation',
    description='test',
)
result = r.run_scenario(s)
print('passed:', result.passed)
print('level reached:', result.level_reached)
print('mode reached:', result.mode_reached)
for m in result.metrics:
    print(' ', m.metric, '->', m.passed, ':', m.detail[:80])
