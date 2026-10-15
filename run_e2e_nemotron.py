"""
Full 61-phrase E2E with verified routing. Nemotron only.
1-second delays, saves results incrementally.
"""
import sys, time, json, re
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()

# Swap to Nemotron
for p in ai._providers:
    if p.name == "OpenRouter":
        p._model = "nvidia/nemotron-3-super-120b-a12b:free"
        print(f"[SWITCH] Using: {p.model_id}")
        break

intent = LLMIntentResolver(ai_engine=ai)

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

original_gen = ai.generate_response
routing_log = []

def intercepted_gen(prompt, mode=None, complexity=None):
    result = original_gen(prompt, mode=mode, complexity=complexity)
    routing_log.append(mode)
    return result

ai.generate_response = intercepted_gen

results = []
for i, (phrase, expected, family) in enumerate(PHRASES):
    gate = LLMIntentResolver.looks_actionable(phrase)
    
    if not gate:
        correct = (expected is None)
        result = {"phrase": phrase, "expected": expected, "got": None,
                  "family": family, "gate": "REJECT", "correct": correct,
                  "routing": "gate"}
        tag = "GATE_OK" if correct else "GATE_FN"
    else:
        routing_log.clear()
        start = time.time()
        c = intent.resolve(phrase)
        elapsed = time.time() - start
        
        op = (c.get("operation") or c.get("intent")) if c else None
        correct = (op == expected)
        
        modes = list(routing_log)
        routing = "cloud" if "cloud" in modes else ("local" if "local" in modes else "auto")
        
        result = {"phrase": phrase, "expected": expected, "got": op,
                  "family": family, "gate": "PASS", "correct": correct,
                  "routing": routing, "time": round(elapsed, 1)}
        tag = "CORRECT" if correct else ("NULL" if op is None else f"WRONG:{op}")
    
    marker = "+" if result["correct"] else "-"
    r = result.get("routing", "gate")
    t = result.get("time", "-")
    print(f"  {marker} [{r:8s}] [{family:14s}] \"{phrase}\" -> {result.get('got')} ({t}s)")
    
    results.append(result)
    
    # Save incrementally
    with open("phase3_e2e_nemotron_verified.json", "w") as f:
        json.dump(results, f, indent=2)
    
    time.sleep(1)

# Final summary
print("\n" + "=" * 80)
print("  SUMMARY")
print("=" * 80)
total = len(results)
correct_count = sum(1 for r in results if r["correct"])
actionable = [r for r in results if r["expected"] is not None]
non_actionable = [r for r in results if r["expected"] is None]
tp = sum(1 for r in actionable if r["correct"])
fn = sum(1 for r in actionable if not r["correct"])
tn = sum(1 for r in non_actionable if r["correct"])
fp = sum(1 for r in non_actionable if not r["correct"])

print(f"  Overall: {correct_count}/{total} ({100*correct_count/total:.1f}%)")
print(f"  Actionable: TP={tp} FN={fn} ({100*fn/len(actionable):.1f}% FN rate)")
print(f"  Non-actionable: TN={tn} FP={fp} ({100*fp/len(non_actionable):.1f}% FP rate)")

from collections import Counter
rc = Counter(r.get("routing") for r in results)
print(f"\n  Routing: {dict(rc)}")

families = {}
for r in results:
    fam = r["family"]
    if fam not in families:
        families[fam] = {"t": 0, "c": 0}
    families[fam]["t"] += 1
    if r["correct"]:
        families[fam]["c"] += 1
print(f"\n  By family:")
for fam in sorted(families.keys()):
    d = families[fam]
    print(f"    {fam:20s}: {d['c']}/{d['t']} ({100*d['c']/d['t']:.1f}%)")
