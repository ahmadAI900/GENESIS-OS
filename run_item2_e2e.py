"""
Item 2 — Real live E2E broad measurement.
61 phrases, same as prior session, through the REAL wired LLM path.
Model: google/gemma-4-31b-it:free
"""
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

# Exact same 61 phrases from prior session for direct comparison
PHRASES = [
    ("boot up the spreadsheet program", "application.open", "application", "colloquial"),
    ("shut that program down", "application.close", "application", "colloquial"),
    ("tell me what programs I have open", "application.list", "application", "indirect"),
    ("switch to the browser", "application.open", "application", "indirect"),
    ("press that button on the screen", "gui.click", "gui", "indirect"),
    ("enter my username in the text field", "gui.type_text", "gui", "indirect"),
    ("scroll up a bit", "gui.scroll", "gui", "direct"),
    ("highlight all the text here", "gui.select", "gui", "colloquial"),
    ("clone that file for me", "file.copy", "filesystem", "colloquial"),
    ("make a fresh directory here", "folder.create", "filesystem", "colloquial"),
    ("I need to find a document", "file.search", "filesystem", "indirect"),
    ("give this file a new name", "file.rename", "filesystem", "indirect"),
    ("can you relocate this to the backup drive", "file.move", "filesystem", "indirect"),
    ("wipe that old temp folder", "folder.delete", "filesystem", "colloquial"),
    ("sort out the mess in my downloads", "folder.organize", "filesystem", "colloquial"),
    ("show me what's in the recycle bin", "cleanup.recycle_bin_query", "filesystem", "indirect"),
    ("read the contents of that file", "document.read", "document", "direct"),
    ("fix the formatting in the report", "document.edit", "document", "indirect"),
    ("condense this into a brief overview", "document.summarize", "document", "indirect"),
    ("how do these two versions differ", "document.compare", "document", "question"),
    ("tell me what this document is about", "document.read_intel", "document", "indirect"),
    ("sort this spreadsheet by the last column", "spreadsheet.sort", "spreadsheet", "direct"),
    ("show me only the rows where amount exceeds 100", "spreadsheet.filter", "spreadsheet", "indirect"),
    ("add up all the values in column B", "spreadsheet.aggregate", "spreadsheet", "indirect"),
    ("these two sheets don't match, compare them", "spreadsheet.compare", "spreadsheet", "colloquial"),
    ("what does this workbook contain", "spreadsheet.inspect", "spreadsheet", "question"),
    ("navigate to example.com", "browser.open_url", "browser", "direct"),
    ("locate the input box on this page", "browser.find", "browser", "indirect"),
    ("pull that picture down from the website", "browser.download", "browser", "colloquial"),
    ("where am I right now on the web", "browser.get_url", "browser", "question"),
    ("take a snapshot of this webpage", "browser.screenshot", "browser", "colloquial"),
    ("lower the sound level", "volume.down", "system", "colloquial"),
    ("how much room is left on my drive", "hardware.storage", "system", "question"),
    ("am I running low on battery", "hardware.battery", "system", "question"),
    ("grab what's on the display", "screen.capture", "system", "colloquial"),
    ("lock this machine", "workstation.lock", "system", "colloquial"),
    ("dim the screen a little", "display.brightness_set", "system", "indirect"),
    ("what are my system resources doing", "hardware.stats", "system", "question"),
    ("connect to a wireless network", "network.connect_wifi", "system", "indirect"),
    ("play the next song", "media.next", "media", "direct"),
    ("pause what's currently playing", "media.play_pause", "media", "colloquial"),
    ("end the audio playback", "media.stop", "media", "indirect"),
    ("go back to the previous track", "media.previous", "media", "direct"),
    ("scan for nearby wifi signals", "network.list_wifi", "network", "colloquial"),
    ("which wifi networks can I join", "network.list_wifi", "network", "question"),
    ("what processes are active", "process.list", "process", "question"),
    ("give me details on that running task", "process.inspect", "process", "indirect"),
    ("put that text on the clipboard", "clipboard.copy", "clipboard", "colloquial"),
    ("retrieve what I copied last", "clipboard.paste", "clipboard", "colloquial"),
    ("jot something down for later", "notes.create", "notes", "colloquial"),
    ("show me my saved notes", "notes.list", "notes", "indirect"),
    ("the sunset looks incredible tonight", None, "conversational", "statement"),
    ("I just adopted a new puppy", None, "conversational", "life_event"),
    ("do you enjoy reading books", None, "conversational", "opinion_question"),
    ("my neighbor's dog won't stop barking", None, "conversational", "complaint"),
    ("let's discuss the quarterly budget next week", None, "conversational", "suggestion"),
    ("coffee is much better than tea", None, "conversational", "opinion"),
    ("the traffic was awful this morning", None, "conversational", "statement"),
    ("I need to call my dentist tomorrow", None, "conversational", "reminder"),
    ("what's your favorite movie of all time", None, "conversational", "opinion_question"),
    ("the kids had a great time at the park", None, "conversational", "observation"),
]

print("=" * 80)
print("  ITEM 2 — REAL LIVE E2E BROAD MEASUREMENT")
print(f"  Model: google/gemma-4-31b-it:free")
print(f"  {len(PHRASES)} phrases, {len(set(p[2] for p in PHRASES))} families")
print("=" * 80)
print()

results = []
llm_errors = 0
cloud_fails = 0

for i, (phrase, expected, family, label) in enumerate(PHRASES):
    gate = LLMIntentResolver.looks_actionable(phrase)

    if not gate:
        correct = (expected is None)
        result = {
            "phrase": phrase, "expected": expected, "got": None,
            "family": family, "label": label, "gate": "REJECT",
            "correct": correct, "model": None,
        }
        tag = "CORRECT_NULL" if correct else "FALSE_NEGATIVE"
        print(f"  [{tag:20s}] [{family:14s}] \"{phrase}\"")
    else:
        start = time.time()
        c = engine._try_semantic_intent_resolution(phrase)
        elapsed = time.time() - start
        op = (c.get("operation") or c.get("intent")) if c else None

        # Track which model answered
        model_used = "unknown"
        if c and "source" in c:
            model_used = c["source"]
        elif elapsed < 3:
            model_used = "local"
        else:
            model_used = "cloud"

        if c is None:
            llm_errors += 1

        correct = (op == expected)
        result = {
            "phrase": phrase, "expected": expected, "got": op,
            "family": family, "label": label, "gate": "PASS",
            "correct": correct, "model": model_used, "time": round(elapsed, 1),
        }
        if expected is None:
            tag = "FALSE_POSITIVE"
        elif op == expected:
            tag = "CORRECT"
        elif op is None:
            tag = "LLM_NULL"
        else:
            tag = f"WRONG:{op}"
        print(f"  [{tag:20s}] [{family:14s}] \"{phrase}\" => {op}  ({elapsed:.1f}s)")

    results.append(result)
    time.sleep(0.3)

# === SUMMARY ===
print()
print("=" * 80)
print("  SUMMARY")
print("=" * 80)

total = len(results)
correct = sum(1 for r in results if r["correct"])
actionable = [r for r in results if r["expected"] is not None]
non_actionable = [r for r in results if r["expected"] is None]

true_pos = sum(1 for r in actionable if r["correct"])
false_neg = sum(1 for r in actionable if not r["correct"])
true_neg = sum(1 for r in non_actionable if r["correct"])
false_pos = sum(1 for r in non_actionable if not r["correct"])

print(f"  Model: google/gemma-4-31b-it:free")
print(f"  Total phrases:     {total}")
print(f"  Overall accuracy:  {correct}/{total} ({100*correct/total:.1f}%)")
print()
print(f"  Actionable:        {len(actionable)}")
print(f"    True positive:   {true_pos}")
print(f"    False negative:  {false_neg}")
print(f"  Non-actionable:    {len(non_actionable)}")
print(f"    True negative:   {true_neg}")
print(f"    False positive:  {false_pos}")
print()
print(f"  FALSE POSITIVE RATE: {false_pos}/{len(non_actionable)} ({100*false_pos/len(non_actionable):.1f}%)")
print(f"  FALSE NEGATIVE RATE: {false_neg}/{len(actionable)} ({100*false_neg/len(actionable):.1f}%)")
print(f"  LLM errors (None returned): {llm_errors}")

# By family
print()
print("  BY FAMILY:")
families = {}
for r in results:
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
    acc = 100 * d["correct"] / d["total"]
    print(f"    {fam:20s}: {d['correct']}/{d['total']} ({acc:.1f}%)  [FN:{d['fn']} FP:{d['fp']}]")

print()
print("  FAILED PHRASES:")
for r in results:
    if not r["correct"]:
        fptype = "FALSE_POSITIVE" if r["expected"] is None else "FALSE_NEGATIVE"
        print(f"    [{fptype:16s}] [{r['family']:14s}] \"{r['phrase']}\"")
        print(f"      expected={r['expected']}, got={r['got']}, gate={r['gate']}")

# Save
with open("phase3_item2_live_eee.json", "w") as f:
    json.dump(results, f, indent=2)
print()
print("  Raw results saved to phase3_item2_live_eee.json")
