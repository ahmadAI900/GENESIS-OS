"""
Prompt-format fragility test — rate-limit safe version.
5 phrases only, 5-second gaps between calls.
Forces cloud mode for every call.
"""
import sys, time, json, re
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()
intent = LLMIntentResolver(ai_engine=ai)
catalog = intent._capability_catalog()

# 5 phrases that failed (mix of nulls and wrong ops from different families)
TEST_PHRASES = [
    ("shut that program down", "application.close"),
    ("clone that file for me", "file.copy"),
    ("condense this into a brief overview", "document.summarize"),
    ("pause what's currently playing", "media.play_pause"),
    ("put that text on the clipboard", "clipboard.copy"),
]

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

def extract_op(raw_response):
    if not isinstance(raw_response, str):
        return None
    raw = raw_response.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed.get("operation") or parsed.get("intent")
        if parsed is None:
            return None
    except:
        pass
    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed.get("operation") or parsed.get("intent")
        except:
            pass
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed.get("operation") or parsed.get("intent")
        except:
            pass
    return None

print("=" * 80)
print("  PROMPT-FORMAT FRAGILITY TEST (Rate-limit safe)")
print("  5 phrases, 5-second gaps, forced cloud")
print("=" * 80)

results = []

for i, (phrase, expected) in enumerate(TEST_PHRASES):
    print(f"\n  [{i+1}/5] Phrase: \"{phrase}\"  (expected: {expected})")
    
    # Current prompt
    current_prompt = build_current_prompt(phrase, catalog)
    try:
        raw_current = ai.generate_response(current_prompt, mode="cloud")
        op_current = extract_op(raw_current)
    except Exception as e:
        raw_current = str(e)
        op_current = None
    
    time.sleep(5)  # 5-second gap
    
    # Gemma-optimized prompt
    gemma_prompt = build_gemma_prompt(phrase, catalog)
    try:
        raw_gemma = ai.generate_response(gemma_prompt, mode="cloud")
        op_gemma = extract_op(raw_gemma)
    except Exception as e:
        raw_gemma = str(e)
        op_gemma = None
    
    time.sleep(5)  # 5-second gap before next phrase
    
    correct_c = (op_current == expected)
    correct_g = (op_gemma == expected)
    
    tag_c = "CORRECT" if correct_c else ("NULL" if op_current is None else f"WRONG:{op_current}")
    tag_g = "CORRECT" if correct_g else ("NULL" if op_gemma is None else f"WRONG:{op_gemma}")
    
    print(f"    [CURRENT]  {tag_c}")
    print(f"    [GEMMA]    {tag_g}")
    
    if not correct_c and isinstance(raw_current, str) and "429" in raw_current:
        print(f"    [NOTE] Current prompt hit rate limit")
    if not correct_g and isinstance(raw_gemma, str) and "429" in raw_gemma:
        print(f"    [NOTE] Gemma prompt hit rate limit")
    
    results.append({
        "phrase": phrase,
        "expected": expected,
        "current_op": op_current,
        "gemma_op": op_gemma,
        "current_correct": correct_c,
        "gemma_correct": correct_g,
    })

print("\n" + "=" * 80)
print("  RESULTS")
print("=" * 80)

cc = sum(1 for r in results if r["current_correct"])
gc = sum(1 for r in results if r["gemma_correct"])
cn = sum(1 for r in results if r["current_op"] is None and not r["current_correct"])
gn = sum(1 for r in results if r["gemma_op"] is None and not r["gemma_correct"])

print(f"  Current prompt:   {cc}/{len(results)} correct ({cn} nulls)")
print(f"  Gemma-optimized:  {gc}/{len(results)} correct ({gn} nulls)")
print(f"  Improvement:      {gc - cc:+d}")

for r in results:
    c = "OK" if r["current_correct"] else "FAIL"
    g = "OK" if r["gemma_correct"] else "FAIL"
    imp = "IMPROVED" if (not r["current_correct"] and r["gemma_correct"]) else \
          ("REGRESSED" if (r["current_correct"] and not r["gemma_correct"]) else "SAME")
    print(f"  [{imp:10s}] \"{r['phrase']}\" current={c} gemma={g}")

if gc > cc:
    print(f"\n  VERDICT: Prompt-format IS a factor. +{gc-cc}/{len(results)} improvement.")
elif gc < cc:
    print(f"\n  VERDICT: Prompt-format makes it WORSE. Model reasoning issue.")
else:
    print(f"\n  VERDICT: No difference. Model reasoning issue.")
