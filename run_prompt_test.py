"""
Part 2: Prompt-Format Fragility Test
Compare current prompt vs Gemma-optimized prompt on 10 failed phrases.
Tests whether Gemma's poor performance is reasoning vs prompt-format.
"""
import sys, time, json, io, re
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()

# 10 phrases that failed in Item 2 (LLM returned null or wrong)
# These were handled by LOCAL (qwen2.5:0.5b) in the routing diagnostic
# We need to force CLOUD (Gemma) for both prompt variants
TEST_PHRASES = [
    ("shut that program down", "application.close"),
    ("enter my username in the text field", "gui.type_text"),
    ("clone that file for me", "file.copy"),
    ("wipe that old temp folder", "folder.delete"),
    ("condense this into a brief overview", "document.summarize"),
    ("pull that picture down from the website", "browser.download"),
    ("pause what's currently playing", "media.play_pause"),
    ("go back to the previous track", "media.previous"),
    ("put that text on the clipboard", "clipboard.copy"),
    ("jot something down for later", "notes.create"),
]

# ================================================================
# CURRENT PROMPT (from _build_prompt)
# ================================================================
def build_current_prompt(text, catalog):
    return f"""You convert a user's computer-control request into ONE Genesis OS capability.

CAPABILITIES (operation | inputs | description):
{catalog}

EXAMPLES:
USER REQUEST: "grab what's on my screen and save it"
{{"operation": "screen.capture", "target": "screen", "parameters": {{}}}}

USER REQUEST: "I can barely see this, fix it"
{{"operation": "display.brightness_set", "target": "brightness", "parameters": {{"direction": "up"}}}}

USER REQUEST: "what's eating up my disk space"
{{"operation": "hardware.storage", "target": "storage", "parameters": {{}}}}

USER REQUEST: "how bright is my screen right now"
{{"operation": "display.brightness_get", "target": "brightness", "parameters": {{}}}}

USER REQUEST: "what is playing right now"
{{"operation": "media.play_pause", "target": "media", "parameters": {{}}}}

USER REQUEST: "stash this somewhere else"
{{"operation": "file.move", "target": "file", "parameters": {{}}}}

USER REQUEST: "get rid of this file for me"
{{"operation": "file.delete", "target": "file", "parameters": {{}}}}

USER REQUEST: "navigate to example.com"
{{"operation": "browser.open_url", "target": "url", "parameters": {{}}}}

USER REQUEST: "play the next song"
{{"operation": "media.next", "target": "media", "parameters": {{}}}}

USER REQUEST: "scan for nearby wifi signals"
{{"operation": "network.list_wifi", "target": "network", "parameters": {{}}}}

USER REQUEST: "lock this machine"
{{"operation": "workstation.lock", "target": "workstation", "parameters": {{}}}}

These are NOT computer-control requests -- reply null:
USER REQUEST: "what's the weather in paris"
null

USER REQUEST: "hii now i make you able to control my computer"
null

USER REQUEST: "you make me happy"
null

USER REQUEST: "she set the table before we arrived"
null

USER REQUEST: "i think we should set up a meeting"
null

RULES:
- Choose exactly ONE operation, or reply null if none fits.
- Reply with ONLY a JSON object on the first line, nothing else.
- Format: {{"operation": "<id>", "target": "<what it acts on>", "parameters": {{}}}}
- Numbers in parameters must be JSON numbers.
- Never invent operations that are not listed.
- If the user is making conversation, asking an opinion, or describing a state (not requesting a computer action), reply null.

USER REQUEST: "{text}"

JSON:"""

# ================================================================
# GEMMA-OPTIMIZED PROMPT
# Key changes for Gemma:
# 1. System/user role separation (Gemma follows instructions better with clear roles)
# 2. Stricter JSON-only instruction (no prose)
# 3. Fewer examples (Gemma gets confused by too many)
# 4. More direct instruction style
# 5. Explicit "output ONLY valid JSON" repeated
# ================================================================
def build_gemma_prompt(text, catalog):
    return f"""<bos><start_of_turn>user
You are a JSON-only classifier. Classify the user request below into exactly ONE Genesis OS capability.

AVAILABLE CAPABILITIES:
{catalog}

INSTRUCTIONS:
1. Read the user request.
2. Find the SINGLE best-matching capability from the list above.
3. Output ONLY a JSON object. No explanation, no prose, no markdown.

EXAMPLE INPUT: "grab what's on my screen and save it"
EXAMPLE OUTPUT: {{"operation": "screen.capture", "target": "screen", "parameters": {{}}}}

EXAMPLE INPUT: "get rid of this file for me"
EXAMPLE OUTPUT: {{"operation": "file.delete", "target": "file", "parameters": {{}}}}

If the request is NOT a computer control command (conversation, opinion, question about non-computer topic), output: null

USER REQUEST: "{text}"

Output ONLY valid JSON:<end_of_turn>
<start_of_turn>model
"""

# ================================================================
# TEST both prompts on 10 phrases, forced through cloud
# ================================================================
intent = LLMIntentResolver(ai_engine=ai)
catalog = intent._capability_catalog()

print("=" * 80)
print("  PROMPT-FORMAT FRAGILITY TEST")
print("  Testing 10 failed phrases with current vs Gemma-optimized prompt")
print("  FORCING cloud (Gemma 4 31B) for all calls")
print("=" * 80)

def force_cloud_generate(prompt):
    """Force the AI engine to use cloud only."""
    return ai.generate_response(prompt, mode="cloud")

def extract_op(raw_response):
    """Extract operation from LLM response."""
    if not isinstance(raw_response, str):
        return None
    raw = raw_response.strip()
    # Direct JSON parse
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed.get("operation") or parsed.get("intent")
        if parsed is None:
            return None
    except:
        pass
    # Strip markdown fences
    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed.get("operation") or parsed.get("intent")
        except:
            pass
    # First balanced braces
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed.get("operation") or parsed.get("intent")
        except:
            pass
    return None

results = []

for phrase, expected in TEST_PHRASES:
    print(f"\n  Phrase: \"{phrase}\"  (expected: {expected})")
    
    # Test 1: Current prompt
    current_prompt = build_current_prompt(phrase, catalog)
    try:
        raw_current = force_cloud_generate(current_prompt)
        op_current = extract_op(raw_current)
    except Exception as e:
        raw_current = str(e)
        op_current = None
        print(f"    [CURRENT] Error: {e}")
    
    time.sleep(1)  # Rate limit buffer
    
    # Test 2: Gemma-optimized prompt
    gemma_prompt = build_gemma_prompt(phrase, catalog)
    try:
        raw_gemma = force_cloud_generate(gemma_prompt)
        op_gemma = extract_op(raw_gemma)
    except Exception as e:
        raw_gemma = str(e)
        op_gemma = None
        print(f"    [GEMMA]   Error: {e}")
    
    correct_current = (op_current == expected)
    correct_gemma = (op_gemma == expected)
    
    tag_c = "CORRECT" if correct_current else ("NULL" if op_current is None else f"WRONG:{op_current}")
    tag_g = "CORRECT" if correct_gemma else ("NULL" if op_gemma is None else f"WRONG:{op_gemma}")
    
    print(f"    [CURRENT]  {tag_c}")
    print(f"    [GEMMA]    {tag_g}")
    
    # Show raw responses for debugging
    if not correct_current and not correct_gemma:
        print(f"    [CURRENT raw] {raw_current[:200] if isinstance(raw_current, str) else raw_current}")
        print(f"    [GEMMA raw]   {raw_gemma[:200] if isinstance(raw_gemma, str) else raw_gemma}")
    
    results.append({
        "phrase": phrase,
        "expected": expected,
        "current_op": op_current,
        "gemma_op": op_gemma,
        "current_correct": correct_current,
        "gemma_correct": correct_gemma,
    })
    
    time.sleep(0.5)

# Summary
print("\n" + "=" * 80)
print("  PROMPT-FORMAT FRAGILITY RESULTS")
print("=" * 80)

current_correct = sum(1 for r in results if r["current_correct"])
gemma_correct = sum(1 for r in results if r["gemma_correct"])
current_nulls = sum(1 for r in results if r["current_op"] is None and not r["current_correct"])
gemma_nulls = sum(1 for r in results if r["gemma_op"] is None and not r["gemma_correct"])

print(f"  Current prompt:   {current_correct}/{len(results)} correct ({current_nulls} nulls)")
print(f"  Gemma-optimized:  {gemma_correct}/{len(results)} correct ({gemma_nulls} nulls)")
print(f"  Improvement:      {gemma_correct - current_correct:+d}")

# Per-phrase comparison
print(f"\n  PER-PHRASE COMPARISON:")
for r in results:
    c = "OK" if r["current_correct"] else "FAIL"
    g = "OK" if r["gemma_correct"] else "FAIL"
    improved = "IMPROVED" if (not r["current_correct"] and r["gemma_correct"]) else \
               ("REGRESSED" if (r["current_correct"] and not r["gemma_correct"]) else "SAME")
    print(f"    [{improved:10s}] \"{r['phrase']}\" current={c} gemma={g}")

# Verdict
print(f"\n  VERDICT:")
if gemma_correct > current_correct:
    print(f"  Prompt-format IS a factor. Gemma-optimized prompt improves by {gemma_correct - current_correct}/{len(results)}.")
    print(f"  This is a MECHANISM FRAGILITY issue, not purely model weakness.")
elif gemma_correct < current_correct:
    print(f"  Gemma-optimized prompt is WORSE. This is a MODEL REASONING issue.")
else:
    print(f"  No difference. This is a MODEL REASONING issue, not prompt-format.")
