"""Read benchmark/BENCHMARK_RESULTS.json and print each failure.

Item 11C: the path was hardcoded to an absolute location OUTSIDE the
repository, including this machine's username. That made the script
non-portable and pointed it at the untracked copy rather than the
versioned one.
"""
import json
import pathlib

RESULTS = (
    pathlib.Path(__file__).resolve().parent
    / "benchmark"
    / "BENCHMARK_RESULTS.json"
)

with open(RESULTS, encoding="utf-8") as fh:
    d = json.load(fh)

for f in d['failures']:
    print("[" + f['scenario_id'] + "] " + f['category'])
    print("  request: " + repr(f['user_request']))
    print("  expected: level=" + str(f['expected_level']) + " mode=" + str(f['expected_mode']) + " intent=" + repr(f.get('expected_intent')) + " target=" + repr(f.get('expected_target')))
    print("  got:      level=" + str(f['level_reached']) + " mode=" + str(f['mode_reached']) + " intent=" + repr(f.get('intent_reached')) + " target=" + repr(f.get('target_reached')))
    print("  failed: " + ','.join(f['failed_metrics']))
    print()