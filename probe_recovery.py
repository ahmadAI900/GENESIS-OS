import sys
sys.path.insert(0, '.')
from benchmark.runner import BenchmarkRunner
from benchmark.scenarios import BenchmarkScenario
r = BenchmarkRunner()
s = BenchmarkScenario(
    scenario_id='test',
    category='filesystem',
    user_request='delete folder xyz_no_such_folder',
    expected_level=3,
    expected_mode='os',
    recovery_intent=True,
    expected_target='xyz_no_such_folder',
    description='test',
)
result = r.run_scenario(s)
print('passed:', result.passed)
for m in result.metrics:
    print(' ', m.metric, '->', m.passed, ':', m.detail[:80])
