import json
import sys
with open('C:/Users/Muhammad/Desktop/gemini_cli/BENCHMARK_RESULTS.json') as f:
    d = json.load(f)
for f in d['failures']:
    print("[" + f['scenario_id'] + "] " + f['category'])
    print("  request: " + repr(f['user_request']))
    print("  expected: level=" + str(f['expected_level']) + " mode=" + str(f['expected_mode']) + " intent=" + repr(f.get('expected_intent')) + " target=" + repr(f.get('expected_target')))
    print("  got:      level=" + str(f['level_reached']) + " mode=" + str(f['mode_reached']) + " intent=" + repr(f.get('intent_reached')) + " target=" + repr(f.get('target_reached')))
    print("  failed: " + ','.join(f['failed_metrics']))
    print()
