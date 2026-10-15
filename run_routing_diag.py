"""
Diagnostic: run 10 failed phrases with full routing instrumentation.
Logs exactly which backend answered each call.
"""
import sys, time, json, io
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

# Capture stderr where AI Engine prints routing info
import contextlib

ai = AIEngine()
engine = WorkflowDecisionEngine(
    registry=None, context=None, conversation=None,
    memory=None, ai_engine=ai,
)

# 10 phrases that failed in Item 2 (gate PASS, LLM returned null or wrong)
PHRASES = [
    ("shut that program down", "application.close"),
    ("enter my username in the text field", "gui.type_text"),
    ("clone that file for me", "file.copy"),
    ("wipe that old temp folder", "folder.delete"),
    ("condense this into a brief overview", "document.summarize"),
    ("pull that picture down from the website", "browser.download"),
    ("pause what's currently playing", "media.play_pause"),
    ("go back to the previous track", "media.previous"),
    ("give me details on that running task", "process.inspect"),
    ("jot something down for later", "notes.create"),
]

print("=" * 80)
print("  ROUTING DIAGNOSTIC — 10 FAILED PHRASES")
print("=" * 80)

# Patch the AI engine to capture routing decisions
original_generate = ai.generate_response
routing_log = []

def patched_generate(*args, **kwargs):
    # Capture what backend is selected
    backend = kwargs.get('mode', 'auto')
    result = original_generate(*args, **kwargs)
    return result

# Instead, let's just run and capture the printed routing info
results = []
for phrase, expected in PHRASES:
    print(f"\n  Phrase: \"{phrase}\"  (expected: {expected})")
    
    # Capture stdout to see routing
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()
    
    start = time.time()
    c = engine._try_semantic_intent_resolution(phrase)
    elapsed = time.time() - start
    
    sys.stdout = old_stdout
    routing_output = captured.getvalue()
    
    op = (c.get("operation") or c.get("intent")) if c else None
    correct = (op == expected)
    
    # Parse routing from output
    used_cloud = "cloud -> google/gemma" in routing_output
    used_local = "local -> qwen2.5" in routing_output
    cloud_failed = "Cloud model failed" in routing_output
    
    if cloud_failed:
        routing = "cloud FAILED -> local fallback"
    elif used_cloud and not used_local:
        routing = "cloud (Gemma 4)"
    elif used_local and not used_cloud:
        routing = "local (qwen2.5 0.5B)"
    elif used_cloud and used_local:
        routing = "cloud + local (both attempted)"
    else:
        routing = "unknown"
    
    tag = "CORRECT" if correct else ("NULL" if op is None else f"WRONG:{op}")
    print(f"    Routing: {routing}")
    print(f"    Result: {tag} ({elapsed:.1f}s)")
    print(f"    Raw routing lines:")
    for line in routing_output.split('\n'):
        if 'AI Engine' in line or 'AI Router' in line:
            print(f"      {line.strip()}")
    
    results.append({
        "phrase": phrase,
        "expected": expected,
        "got": op,
        "correct": correct,
        "routing": routing,
        "cloud_failed": cloud_failed,
        "time": round(elapsed, 1),
    })
    time.sleep(0.3)

print("\n" + "=" * 80)
print("  ROUTING SUMMARY")
print("=" * 80)
cloud_ok = sum(1 for r in results if "cloud (Gemma" in r["routing"])
cloud_fail_local = sum(1 for r in results if "cloud FAILED" in r["routing"])
local_only = sum(1 for r in results if "local (qwen" in r["routing"])
print(f"  Cloud (Gemma 4) answered: {cloud_ok}/{len(results)}")
print(f"  Cloud failed, local fallback: {cloud_fail_local}/{len(results)}")
print(f"  Local only: {local_only}/{len(results)}")
print()
correct_when_cloud = sum(1 for r in results if "cloud (Gemma" in r["routing"] and r["correct"])
correct_when_local = sum(1 for r in results if "local" in r["routing"] and r["correct"])
print(f"  Correct when Gemma answered: {correct_when_cloud}/{cloud_ok}" if cloud_ok else "  Correct when Gemma answered: 0/0")
print(f"  Correct when local answered: {correct_when_local}/{cloud_fail_local + local_only}" if (cloud_fail_local + local_only) else "  Correct when local answered: 0/0")
