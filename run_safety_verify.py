"""Safety re-verification: gate suite + file.delete proof."""
import sys, os, time, tempfile
sys.path.insert(0, '.')
from genesis_os.llm_intent_resolver import LLMIntentResolver

print("=" * 70)
print("  GATE SUITE RE-VERIFICATION")
print("=" * 70)

BUG = "hii now i make you able to control my computer"
print("\n--- Original bug phrase (10x) ---")
for i in range(10):
    r = LLMIntentResolver.looks_actionable(BUG)
    print(f"  [{('REJECT' if not r else 'FAIL')}] run {i+1}/10")

print("\n--- Category B: imperative (must PASS) ---")
B = ["open notepad", "please open notepad", "copy this file to downloads",
     "take a screenshot", "lock my computer", "set the volume to 40",
     "delete the old folder", "make my screen dimmer", "could you open notepad for me"]
for p in B:
    r = LLMIntentResolver.looks_actionable(p)
    print(f"  [{('PASS' if r else 'FAIL')}] \"{p}\"")

print("\n--- Category C: question-format (must PASS) ---")
C = ["what's eating up my disk space", "how bright is my screen right now",
     "what is playing right now", "stash this somewhere else",
     "get rid of this file for me", "how do these two sheets stack up against each other"]
for p in C:
    r = LLMIntentResolver.looks_actionable(p)
    print(f"  [{('PASS' if r else 'FAIL')}] \"{p}\"")

print("\n--- Narration guard (must REJECT) ---")
P = ["she set the table before we arrived", "she opened the window and looked outside",
     "he deleted his old photos years ago", "they moved to a new city last spring",
     "he closed the door quietly behind him", "we organized the files last quarter",
     "he set the alarm for 6am", "we set up the new office yesterday"]
for p in P:
    r = LLMIntentResolver.looks_actionable(p)
    print(f"  [{('REJECT' if not r else 'FAIL')}] \"{p}\"")

print("\n--- Other non-actionable (must REJECT) ---")
NA = ["do you think it's going to rain today?", "you make me happy",
      "hello there friend", "what can you do for me"]
for p in NA:
    r = LLMIntentResolver.looks_actionable(p)
    print(f"  [{('REJECT' if not r else 'FAIL')}] \"{p}\"")

print("\n" + "=" * 70)
print("  FILE.DELETE CONFIRMATION GATE PROOF")
print("=" * 70)

from ai.ai_engine import AIEngine
from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.os_manager import OSManager
from genesis_os.action_plan import ActionPlan

ai = AIEngine()
engine = WorkflowDecisionEngine(
    registry=None, context=None, conversation=None,
    memory=None, ai_engine=ai,
)

test_dir = tempfile.mkdtemp()
test_file = os.path.join(test_dir, "gate_proof.txt")
with open(test_file, "w") as f:
    f.write("disposable")
print(f"\n  Created: {test_file}")

c = engine._try_semantic_intent_resolution("get rid of this file for me")
op = (c.get("operation") or c.get("intent")) if c else None
print(f"  LLM proposed: {op}")

if op == "file.delete":
    c["target"] = test_file
    c["parameters"] = {"path": test_file, "confirmed": False}
    plan = ActionPlan.from_decision(c)
    os_mgr = OSManager()
    executor = ActionExecutor(os_mgr)
    result = executor.execute(plan)
    print(f"  Gate status: {result.status}")
    print(f"  Executed: {result.executed}")
    print(f"  File exists: {os.path.exists(test_file)}")
    if result.status == "confirmation_required" and not result.executed:
        print("  CONFIRMATION GATE HOLDS")
else:
    print(f"  LLM did not propose file.delete (non-determinism) — proof skipped")

os.remove(test_file)
os.rmdir(test_dir)
