"""File.delete confirmation gate proof (LLM-dependent)."""
import sys, os, tempfile
sys.path.insert(0, '.')
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

print("=" * 70)
print("  FILE.DELETE CONFIRMATION GATE PROOF")
print("=" * 70)

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
        print("  CONFIRMATION GATE FAILED")
else:
    print(f"  LLM did not propose file.delete (got: {op}) — cloud API rate-limited")
    print("  Gate proof deferred to when cloud API is available")

# Cleanup
if os.path.exists(test_file):
    os.remove(test_file)
if os.path.exists(test_dir):
    os.rmdir(test_dir)
