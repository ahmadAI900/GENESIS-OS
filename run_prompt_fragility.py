"""
Step 3: Prompt-format fragility test.
Takes the 10 worst-failure phrases, tests current prompt vs simplified variant.
"""
import sys, time, json, re
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()

for p in ai._providers:
    if p.name == "OpenRouter":
        print("[CONFIG] Cloud:", p.model_id)
        break

intent = LLMIntentResolver(ai_engine=ai)
catalog = intent._capability_catalog()

# ============================================================
# 10 worst failures from contaminated local run + Groq run
# ============================================================
WORST_10 = [
    ("condense this into a brief overview", "document.summarize"),
    ("fix the formatting in the report", "document.edit"),
    ("how do these two versions differ", "document.compare"),
    ("tell me what this document is about", "document.read_intel"),
    ("put that text on the clipboard", "clipboard.copy"),
    ("retrieve what I copied last", "clipboard.paste"),
    ("press that button on the screen", "gui.click"),
    ("highlight all the text here", "gui.select"),
    ("locate the input box on this page", "browser.find"),
    ("pull that picture down from the website", "browser.download"),
]

# ============================================================
# PROMPT VARIANTS
# ============================================================

def current_prompt(text, catalog):
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

def simplified_prompt(text, catalog):
    return f"""Map this user request to exactly one capability below. Output ONLY JSON.

CAPABILITIES:
{catalog}

RULES:
- Output ONLY a JSON object: {{"operation": "<id>", "target": "<what>", "parameters": {{}}}}
- Pick the SINGLE best match from the list above.
- If not a computer-control request, output: null
- Never invent operations not in the list.

REQUEST: "{text}"

JSON:"""

def tightened_prompt(text, catalog):
    return f"""You are a classifier. Given a user request, pick EXACTLY ONE matching operation from the list.

OPERATIONS:
{catalog}

INSTRUCTIONS:
1. Read the user request carefully.
2. Find the operation whose description best matches the user's intent.
3. Output ONLY a JSON object on a single line. No explanation.

Examples:
"grab what is on my screen" -> {{"operation": "screen.capture", "target": "screen", "parameters": {{}}}}
"get rid of this file" -> {{"operation": "file.delete", "target": "file", "parameters": {{}}}}
"play the next song" -> {{"operation": "media.next", "target": "media", "parameters": {{}}}}
"lock this machine" -> {{"operation": "workstation.lock", "target": "workstation", "parameters": {{}}}}

If the request is NOT a computer control command, output: null

REQUEST: "{text}"

OUTPUT:"""

def extract_op(raw):
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
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

# ============================================================
# RUN TEST
# ============================================================
print()
print("=" * 90)
print("  PROMPT-FORMAT FRAGILITY TEST (Groq)")
print("=" * 90)

prompt_results = []
for phrase, expected in WORST_10:
    print(f"\n  Phrase: \"{phrase}\"  (expected: {expected})")

    # Current prompt
    try:
        raw_c = ai.generate_response(current_prompt(phrase, catalog), mode="cloud")
        op_c = extract_op(raw_c)
    except Exception as e:
        op_c = None
        print(f"    [CURRENT] Error: {str(e)[:80]}")
    time.sleep(2)

    # Simplified prompt
    try:
        raw_s = ai.generate_response(simplified_prompt(phrase, catalog), mode="cloud")
        op_s = extract_op(raw_s)
    except Exception as e:
        op_s = None
        print(f"    [SIMPLIFIED] Error: {str(e)[:80]}")
    time.sleep(2)

    # Tightened prompt
    try:
        raw_t = ai.generate_response(tightened_prompt(phrase, catalog), mode="cloud")
        op_t = extract_op(raw_t)
    except Exception as e:
        op_t = None
        print(f"    [TIGHTENED] Error: {str(e)[:80]}")
    time.sleep(2)

    cc = (op_c == expected)
    cs = (op_s == expected)
    ct = (op_t == expected)

    tc = "CORRECT" if cc else ("NULL" if op_c is None else f"WRONG:{op_c}")
    ts = "CORRECT" if cs else ("NULL" if op_s is None else f"WRONG:{op_s}")
    tt = "CORRECT" if ct else ("NULL" if op_t is None else f"WRONG:{op_t}")
    print(f"    [CURRENT]    {tc}")
    print(f"    [SIMPLIFIED] {ts}")
    print(f"    [TIGHTENED]  {tt}")

    prompt_results.append({
        "phrase": phrase, "expected": expected,
        "current_op": op_c, "simplified_op": op_s, "tightened_op": op_t,
        "current_correct": cc, "simplified_correct": cs, "tightened_correct": ct,
    })

# ============================================================
# SUMMARY
# ============================================================
print()
print("=" * 90)
print("  PROMPT FRAGILITY SUMMARY")
print("=" * 90)

n = len(prompt_results)
pc = sum(1 for r in prompt_results if r["current_correct"])
ps = sum(1 for r in prompt_results if r["simplified_correct"])
pt = sum(1 for r in prompt_results if r["tightened_correct"])

print(f"  Current prompt:    {pc}/{n} ({100*pc/n:.1f}%)")
print(f"  Simplified prompt: {ps}/{n} ({100*ps/n:.1f}%)")
print(f"  Tightened prompt:  {pt}/{n} ({100*pt/n:.1f}%)")
print(f"  Best improvement:  {max(pc,ps,pt) - pc:+d}")

print(f"\n  Per-phrase breakdown:")
print(f"  {'Phrase':50s} {'Expected':25s} {'Current':20s} {'Simplified':20s} {'Tightened':20s}")
print(f"  {'-'*135}")
for r in prompt_results:
    ph = r["phrase"][:50]
    exp = str(r["expected"])[:25]
    cur = "CORRECT" if r["current_correct"] else ("NULL" if r["current_op"] is None else f"WRONG:{r['current_op']}")
    simp = "CORRECT" if r["simplified_correct"] else ("NULL" if r["simplified_op"] is None else f"WRONG:{r['simplified_op']}")
    tight = "CORRECT" if r["tightened_correct"] else ("NULL" if r["tightened_op"] is None else f"WRONG:{r['tightened_op']}")
    print(f"  {ph:50s} {exp:25s} {cur:20s} {simp:20s} {tight:20s}")

# Analysis
print(f"\n  Analysis:")
if pc >= ps and pc >= pt:
    print(f"  The current prompt is ALREADY adequate for a capable model.")
    print(f"  Prompt format does NOT meaningfully affect accuracy.")
elif ps > pc or pt > pc:
    better = "simplified" if ps >= pt else "tightened"
    print(f"  The {better} prompt outperforms the current prompt by {max(ps,pt)-pc} phrases.")
    print(f"  Prompt format DOES meaningfully affect accuracy for this model.")

print(f"\n  Saved: phase3_prompt_fragility_results.json")
with open("phase3_prompt_fragility_results.json", "w") as f:
    json.dump(prompt_results, f, indent=2)
