"""
Combined test: prompt-format fragility + full E2E with verified routing.
Uses Nemotron (only working free model) since Gemma is rate-limited.
"""
import sys, time, json, re, io
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()

# ================================================================
# PART 1: PROMPT-FORMAT FRAGILITY TEST
# ================================================================

# Temporarily swap to Nemotron for testing
# We'll intercept generate_response to force Nemotron
original_provider = None
for p in ai._providers:
    if p.name == "OpenRouter":
        original_provider = p
        p._model = "nvidia/nemotron-3-super-120b-a12b:free"
        print(f"[SWITCH] Provider set to: {p.model_id}")
        break

intent = LLMIntentResolver(ai_engine=ai)
catalog = intent._capability_catalog()

TEST_PHRASES_PROMPT = [
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

print("\n" + "=" * 80)
print("  PART 1: PROMPT-FORMAT FRAGILITY (Nemotron)")
print("=" * 80)

prompt_results = []
for phrase, expected in TEST_PHRASES_PROMPT:
    print(f"\n  Phrase: \"{phrase}\"  (expected: {expected})")
    
    # Current prompt
    try:
        raw_c = ai.generate_response(build_current_prompt(phrase, catalog), mode="cloud")
        op_c = extract_op(raw_c)
    except Exception as e:
        op_c = None
        print(f"    [CURRENT] Error: {str(e)[:80]}")
    
    time.sleep(3)
    
    # Gemma-optimized prompt
    try:
        raw_g = ai.generate_response(build_gemma_prompt(phrase, catalog), mode="cloud")
        op_g = extract_op(raw_g)
    except Exception as e:
        op_g = None
        print(f"    [GEMMA] Error: {str(e)[:80]}")
    
    time.sleep(3)
    
    cc = (op_c == expected)
    cg = (op_g == expected)
    
    tc = "CORRECT" if cc else ("NULL" if op_c is None else f"WRONG:{op_c}")
    tg = "CORRECT" if cg else ("NULL" if op_g is None else f"WRONG:{op_g}")
    print(f"    [CURRENT]  {tc}")
    print(f"    [GEMMA]    {tg}")
    
    prompt_results.append({"phrase": phrase, "expected": expected,
                           "current_op": op_c, "gemma_op": op_g,
                           "current_correct": cc, "gemma_correct": cg})

pc = sum(1 for r in prompt_results if r["current_correct"])
pg = sum(1 for r in prompt_results if r["gemma_correct"])
print(f"\n  Current prompt: {pc}/{len(prompt_results)}")
print(f"  Gemma prompt:   {pg}/{len(prompt_results)}")
print(f"  Delta: {pg - pc:+d}")

# ================================================================
# PART 2: FULL 61-PHRASE E2E WITH VERIFIED ROUTING
# ================================================================

print("\n" + "=" * 80)
print("  PART 2: FULL 61-PHRASE E2E (Nemotron, verified routing)")
print("=" * 80)

PHRASES = [
    ("boot up the spreadsheet program", "application.open", "application"),
    ("shut that program down", "application.close", "application"),
    ("tell me what programs I have open", "application.list", "application"),
    ("switch to the browser", "application.open", "application"),
    ("press that button on the screen", "gui.click", "gui"),
    ("enter my username in the text field", "gui.type_text", "gui"),
    ("scroll up a bit", "gui.scroll", "gui"),
    ("highlight all the text here", "gui.select", "gui"),
    ("clone that file for me", "file.copy", "filesystem"),
    ("make a fresh directory here", "folder.create", "filesystem"),
    ("I need to find a document", "file.search", "filesystem"),
    ("give this file a new name", "file.rename", "filesystem"),
    ("can you relocate this to the backup drive", "file.move", "filesystem"),
    ("wipe that old temp folder", "folder.delete", "filesystem"),
    ("sort out the mess in my downloads", "folder.organize", "filesystem"),
    ("show me what's in the recycle bin", "cleanup.recycle_bin_query", "filesystem"),
    ("read the contents of that file", "document.read", "document"),
    ("fix the formatting in the report", "document.edit", "document"),
    ("condense this into a brief overview", "document.summarize", "document"),
    ("how do these two versions differ", "document.compare", "document"),
    ("tell me what this document is about", "document.read_intel", "document"),
    ("sort this spreadsheet by the last column", "spreadsheet.sort", "spreadsheet"),
    ("show me only the rows where amount exceeds 100", "spreadsheet.filter", "spreadsheet"),
    ("add up all the values in column B", "spreadsheet.aggregate", "spreadsheet"),
    ("these two sheets don't match, compare them", "spreadsheet.compare", "spreadsheet"),
    ("what does this workbook contain", "spreadsheet.inspect", "spreadsheet"),
    ("navigate to example.com", "browser.open_url", "browser"),
    ("locate the input box on this page", "browser.find", "browser"),
    ("pull that picture down from the website", "browser.download", "browser"),
    ("where am I right now on the web", "browser.get_url", "browser"),
    ("take a snapshot of this webpage", "browser.screenshot", "browser"),
    ("lower the sound level", "volume.down", "system"),
    ("how much room is left on my drive", "hardware.storage", "system"),
    ("am I running low on battery", "hardware.battery", "system"),
    ("grab what's on the display", "screen.capture", "system"),
    ("lock this machine", "workstation.lock", "system"),
    ("dim the screen a little", "display.brightness_set", "system"),
    ("what are my system resources doing", "hardware.stats", "system"),
    ("connect to a wireless network", "network.connect_wifi", "system"),
    ("play the next song", "media.next", "media"),
    ("pause what's currently playing", "media.play_pause", "media"),
    ("end the audio playback", "media.stop", "media"),
    ("go back to the previous track", "media.previous", "media"),
    ("scan for nearby wifi signals", "network.list_wifi", "network"),
    ("which wifi networks can I join", "network.list_wifi", "network"),
    ("what processes are active", "process.list", "process"),
    ("give me details on that running task", "process.inspect", "process"),
    ("put that text on the clipboard", "clipboard.copy", "clipboard"),
    ("retrieve what I copied last", "clipboard.paste", "clipboard"),
    ("jot something down for later", "notes.create", "notes"),
    ("show me my saved notes", "notes.list", "notes"),
    ("the sunset looks incredible tonight", None, "conversational"),
    ("I just adopted a new puppy", None, "conversational"),
    ("do you enjoy reading books", None, "conversational"),
    ("my neighbor's dog won't stop barking", None, "conversational"),
    ("let's discuss the quarterly budget next week", None, "conversational"),
    ("coffee is much better than tea", None, "conversational"),
    ("the traffic was awful this morning", None, "conversational"),
    ("I need to call my dentist tomorrow", None, "conversational"),
    ("what's your favorite movie of all time", None, "conversational"),
    ("the kids had a great time at the park", None, "conversational"),
]

# Intercept generate_response to track routing
original_gen = ai.generate_response
routing_calls = []

def intercepted_gen(prompt, mode=None, complexity=None):
    result = original_gen(prompt, mode=mode, complexity=complexity)
    routing_calls.append({"mode": mode, "had_error": False})
    return result

ai.generate_response = intercepted_gen

e2e_results = []
for i, (phrase, expected, family) in enumerate(PHRASES):
    gate = LLMIntentResolver.looks_actionable(phrase)
    
    if not gate:
        correct = (expected is None)
        result = {"phrase": phrase, "expected": expected, "got": None,
                  "family": family, "gate": "REJECT", "correct": correct,
                  "routing": "gate_reject"}
        tag = "GATE_OK" if correct else "GATE_FN"
    else:
        routing_calls.clear()
        start = time.time()
        c = intent.resolve(phrase)
        elapsed = time.time() - start
        
        op = (c.get("operation") or c.get("intent")) if c else None
        correct = (op == expected)
        
        # Determine actual routing from intercepted calls
        modes = [rc["mode"] for rc in routing_calls]
        if "cloud" in modes:
            routing = "cloud"
        elif "local" in modes:
            routing = "local"
        elif "auto" in modes:
            routing = "auto"
        else:
            routing = "none"
        
        result = {"phrase": phrase, "expected": expected, "got": op,
                  "family": family, "gate": "PASS", "correct": correct,
                  "routing": routing, "time": round(elapsed, 1)}
        tag = "CORRECT" if correct else ("NULL" if op is None else f"WRONG:{op}")
    
    marker = "+" if result["correct"] else "-"
    r = result.get("routing", "gate")
    print(f"  {marker} [{r:8s}] [{family:14s}] \"{phrase}\" -> {result.get('got')} ({result.get('time', '-')}s)")
    
    e2e_results.append(result)
    time.sleep(2)

# Save results
with open("phase3_e2e_nemotron_verified.json", "w") as f:
    json.dump(e2e_results, f, indent=2)

# Summary
print("\n" + "=" * 80)
print("  E2E SUMMARY (Nemotron, verified routing)")
print("=" * 80)

total = len(e2e_results)
correct_count = sum(1 for r in e2e_results if r["correct"])
actionable = [r for r in e2e_results if r["expected"] is not None]
non_actionable = [r for r in e2e_results if r["expected"] is None]

tp = sum(1 for r in actionable if r["correct"])
fn = sum(1 for r in actionable if not r["correct"])
tn = sum(1 for r in non_actionable if r["correct"])
fp = sum(1 for r in non_actionable if not r["correct"])

print(f"  Total: {total}")
print(f"  Overall: {correct_count}/{total} ({100*correct_count/total:.1f}%)")
print(f"  Actionable: TP={tp} FN={fn}")
print(f"  Non-actionable: TN={tn} FP={fp}")
print(f"  False positive rate: {fp}/{len(non_actionable)} ({100*fp/len(non_actionable):.1f}%)")
print(f"  False negative rate: {fn}/{len(actionable)} ({100*fn/len(actionable):.1f}%)")

# Routing breakdown
from collections import Counter
routing_counts = Counter(r.get("routing") for r in e2e_results)
print(f"\n  Routing breakdown:")
for routing, count in routing_counts.most_common():
    subset = [r for r in e2e_results if r.get("routing") == routing]
    corr = sum(1 for r in subset if r["correct"])
    print(f"    {routing:15s}: {count} ({corr} correct)")

# By family
print(f"\n  By family:")
families = {}
for r in e2e_results:
    fam = r["family"]
    if fam not in families:
        families[fam] = {"total": 0, "correct": 0, "fn": 0, "fp": 0}
    families[fam]["total"] += 1
    if r["correct"]:
        families[fam]["correct"] += 1
    else:
        if r["expected"] is not None:
            families[fam]["fn"] += 1
        else:
            families[fam]["fp"] += 1

for fam in sorted(families.keys()):
    d = families[fam]
    acc = 100 * d["correct"] / d["total"] if d["total"] else 0
    print(f"    {fam:20s}: {d['correct']}/{d['total']} ({acc:.1f}%) FN:{d['fn']} FP:{d['fp']}")

print(f"\n  Results saved to phase3_e2e_nemotron_verified.json")
