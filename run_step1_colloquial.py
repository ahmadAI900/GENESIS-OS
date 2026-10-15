"""Step 1: Test colloquial phrasing pass rates (6 runs each)."""
import sys, time, json
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()
engine = WorkflowDecisionEngine(
    registry=None, context=None, conversation=None,
    memory=None, ai_engine=ai,
)

RUNS = 6
phrases = [
    ("stash this somewhere else", "file.move"),
    ("get rid of this file for me", "file.delete"),
]

print("=" * 70)
print("  STEP 1: COLLOQUIAL PHRASING PASS-RATE TEST")
print(f"  {RUNS} runs per phrase")
print("=" * 70)

all_results = {}

for phrase, expected in phrases:
    print(f"\n  Phrase: \"{phrase}\"  (expected: {expected})")
    print(f"  {'Run':>4s}  {'Gate':>6s}  {'LLM Op':>20s}  {'Correct':>8s}")
    print(f"  {'-'*4}  {'-'*6}  {'-'*20}  {'-'*8}")
    
    successes = 0
    gate_passes = 0
    llm_correct = 0
    run_results = []
    
    for i in range(RUNS):
        gate = LLMIntentResolver.looks_actionable(phrase)
        gate_passes += 1 if gate else 0
        
        if gate:
            c = engine._try_semantic_intent_resolution(phrase)
            op = (c.get("operation") or c.get("intent")) if c else None
            correct = (op == expected)
            llm_correct += 1 if correct else 0
            successes += 1 if correct else 0
            tag = "CORRECT" if correct else f"WRONG:{op}"
            print(f"  {i+1:4d}  {'PASS':>6s}  {str(op):>20s}  {tag:>8s}")
            run_results.append({"run": i+1, "gate": True, "op": op, "correct": correct})
        else:
            print(f"  {i+1:4d}  {'REJECT':>6s}  {'(gate blocked)':>20s}  {'GATE_NEG':>8s}")
            run_results.append({"run": i+1, "gate": False, "op": None, "correct": False})
        
        time.sleep(0.5)
    
    print(f"\n  Gate pass rate:  {gate_passes}/{RUNS} ({100*gate_passes/RUNS:.1f}%)")
    print(f"  LLM correct (when gate passes): {llm_correct}/{gate_passes}" if gate_passes else "  LLM correct: 0/0 (gate blocked all)")
    print(f"  End-to-end correct: {successes}/{RUNS} ({100*successes/RUNS:.1f}%)")
    
    all_results[phrase] = {
        "expected": expected,
        "runs": RUNS,
        "gate_passes": gate_passes,
        "llm_correct_when_gate_passes": llm_correct,
        "end_to_end_correct": successes,
        "pass_rate": f"{100*successes/RUNS:.1f}%",
        "details": run_results,
    }

print("\n" + "=" * 70)
print("  SUMMARY")
print("=" * 70)
for phrase, data in all_results.items():
    print(f"  \"{phrase}\" -> {data['expected']}: {data['end_to_end_correct']}/{data['runs']} ({data['pass_rate']})")

with open("step1_colloquial_results.json", "w") as f:
    json.dump(all_results, f, indent=2)
print("\n  Results saved to step1_colloquial_results.json")
