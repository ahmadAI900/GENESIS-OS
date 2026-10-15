"""
Fixed routing interceptor: tracks which model ACTUALLY answered,
not just which was attempted.
Also logs the raw cloud/local call sequence.
"""
import sys, time, json, re
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()

# Try Nemotron (check if daily quota reset)
for p in ai._providers:
    if p.name == "OpenRouter":
        p._model = "nvidia/nemotron-3-super-120b-a12b:free"
        break

# Quick availability check
try:
    test = ai.generate_response("say hi", mode="cloud")
    if "rate" in str(test).lower() or "429" in str(test):
        print(f"Cloud unavailable: {str(test)[:100]}")
        print("Trying local only...")
    else:
        print(f"Cloud available: {str(test)[:50]}")
except Exception as e:
    print(f"Cloud error: {str(e)[:100]}")

# The resolve() method calls generate_response multiple times:
# mode="cloud" -> if fails, mode="local" -> if fails, mode=None (auto)
# We need to track ALL calls and determine which one succeeded

original_gen = ai.generate_response
call_log = []

def intercepted_gen(prompt, mode=None, complexity=None):
    result = original_gen(prompt, mode=mode, complexity=complexity)
    # Check if result is an error string
    is_error = isinstance(result, str) and (
        "error" in result.lower() or "429" in result or "could not generate" in result.lower()
    )
    call_log.append({"mode": mode, "is_error": is_error, "result_len": len(str(result))})
    return result

ai.generate_response = intercepted_gen
intent = LLMIntentResolver(ai_engine=ai)

# Test with 3 phrases
test_phrases = [
    ("shut that program down", "application.close"),
    ("clone that file for me", "file.copy"),
    ("pause what's currently playing", "media.play_pause"),
]

for phrase, expected in test_phrases:
    call_log.clear()
    c = intent.resolve(phrase)
    op = (c.get("operation") or c.get("intent")) if c else None
    
    # Determine which call succeeded
    successful_modes = [cl["mode"] for cl in call_log if not cl["is_error"]]
    failed_modes = [cl["mode"] for cl in call_log if cl["is_error"]]
    
    if successful_modes:
        actual_routing = successful_modes[-1]  # last successful call
    elif failed_modes:
        actual_routing = f"ALL_FAILED({','.join(failed_modes)})"
    else:
        actual_routing = "none"
    
    print(f"  \"{phrase}\" -> {op} (expected: {expected})")
    print(f"    Calls: {[(cl['mode'], 'ERR' if cl['is_error'] else 'OK') for cl in call_log]}")
    print(f"    Actual routing: {actual_routing}")
    print()
    time.sleep(1)
