"""
Part 1: Per-family breakdown of 34 failures (nulls vs wrong-ops).
Part 2: Prompt-format fragility test.
Part 3: Routing evidence summary.
"""
import json

with open("phase3_item2_live_eee.json") as f:
    data = json.load(f)

# Filter to actionable only
actionable = [r for r in data if r["expected"] is not None]
failures = [r for r in actionable if not r["correct"]]

print("=" * 80)
print("  PART 1: PER-FAMILY FAILURE BREAKDOWN (34 failures)")
print("=" * 80)

from collections import defaultdict
family_failures = defaultdict(lambda: {"null": [], "wrong_op": [], "gate_reject": []})

for r in failures:
    fam = r["family"]
    if r["gate"] == "REJECT":
        family_failures[fam]["gate_reject"].append(r)
    elif r["got"] is None:
        family_failures[fam]["null"].append(r)
    else:
        family_failures[fam]["wrong_op"].append(r)

# Print sorted by total failures
families_sorted = sorted(family_failures.items(), key=lambda x: len(x[1]["null"]) + len(x[1]["wrong_op"]) + len(x[1]["gate_reject"]), reverse=True)

for fam, fdata in families_sorted:
    total_null = len(fdata["null"])
    total_wrong = len(fdata["wrong_op"])
    total_gate = len(fdata["gate_reject"])
    total = total_null + total_wrong + total_gate
    
    print(f"\n  {fam.upper()} ({total} failures)")
    print(f"  {'-' * 60}")
    
    if fdata["null"]:
        print(f"    LLM null returns ({total_null}):")
        for r in fdata["null"]:
            print(f"      \"{r['phrase']}\" (expected: {r['expected']}, label: {r['label']})")
    
    if fdata["wrong_op"]:
        print(f"    Wrong operations ({total_wrong}):")
        for r in fdata["wrong_op"]:
            print(f"      \"{r['phrase']}\" -> {r['got']} (expected: {r['expected']}, label: {r['label']})")
    
    if fdata["gate_reject"]:
        print(f"    Gate rejected ({total_gate}):")
        for r in fdata["gate_reject"]:
            print(f"      \"{r['phrase']}\" (expected: {r['expected']}, label: {r['label']})")

# Summary table
print("\n" + "=" * 80)
print("  FAILURE CLUSTERING SUMMARY")
print("=" * 80)
print(f"  {'Family':20s} {'Total':6s} {'Null':6s} {'Wrong':6s} {'Gate':6s} {'Cluster?':10s}")
print(f"  {'-'*20} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*10}")

for fam, fdata in families_sorted:
    total_null = len(fdata["null"])
    total_wrong = len(fdata["wrong_op"])
    total_gate = len(fdata["gate_reject"])
    total = total_null + total_wrong + total_gate
    
    # Is this family clustered? (more than 2 failures of same type)
    clustered = "YES" if max(total_null, total_wrong, total_gate) >= 2 else "no"
    
    print(f"  {fam:20s} {total:6d} {total_null:6d} {total_wrong:6d} {total_gate:6d} {clustered:10s}")

# Null vs wrong-op ratio
total_nulls = sum(len(f["null"]) for f in family_failures.values())
total_wrong_ops = sum(len(f["wrong_op"]) for f in family_failures.values())
total_gate_rejects = sum(len(f["gate_reject"]) for f in family_failures.values())
print(f"\n  TOTAL: {len(failures)} failures")
print(f"    LLM null returns:  {total_nulls} ({100*total_nulls/len(failures):.0f}%)")
print(f"    Wrong operations:  {total_wrong_ops} ({100*total_wrong_ops/len(failures):.0f}%)")
print(f"    Gate rejected:     {total_gate_rejects} ({100*total_gate_rejects/len(failures):.0f}%)")

# Clustering analysis
print(f"\n  CLUSTERING ANALYSIS:")
families_with_multiple_nulls = [(fam, len(f["null"])) for fam, f in family_failures.items() if len(f["null"]) >= 2]
families_with_multiple_wrong = [(fam, len(f["wrong_op"])) for fam, f in family_failures.items() if len(f["wrong_op"]) >= 2]

if families_with_multiple_nulls:
    print(f"    Families with 2+ null returns: {', '.join(f'{fam}({n})' for fam, n in families_with_multiple_nulls)}")
if families_with_multiple_wrong:
    print(f"    Families with 2+ wrong ops: {', '.join(f'{fam}({n})' for fam, n in families_with_multiple_wrong)}")

# Label distribution among failures
print(f"\n  LABEL DISTRIBUTION AMONG FAILURES:")
label_counts = defaultdict(int)
for r in failures:
    label_counts[r["label"]] += 1
for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
    print(f"    {label:20s}: {count}")
