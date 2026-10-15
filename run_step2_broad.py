"""
Phase 3 Step 2 — Broad novel-phrasing measurement.
60+ genuinely novel phrases across 15+ capabilities, 5+ families.
Each phrase grepped to confirm it does NOT appear in any existing test/scenario/report file.
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

# (phrase, expected_operation_or_None, family, label)
# All phrases verified via grep to NOT appear in any existing file.
PHRASES = [
    # ═══════════════════════════════════════════════════
    # APPLICATION (4 phrases)
    # ═══════════════════════════════════════════════════
    ("boot up the spreadsheet program", "application.open", "application", "colloquial"),
    ("shut that program down", "application.close", "application", "colloquial"),
    ("tell me what programs I have open", "application.list", "application", "indirect"),
    ("switch to the browser", "application.open", "application", "indirect"),

    # ═══════════════════════════════════════════════════
    # GUI (4 phrases)
    # ═══════════════════════════════════════════════════
    ("press that button on the screen", "gui.click", "gui", "indirect"),
    ("enter my username in the text field", "gui.type_text", "gui", "indirect"),
    ("scroll up a bit", "gui.scroll", "gui", "direct"),
    ("highlight all the text here", "gui.select", "gui", "colloquial"),

    # ═══════════════════════════════════════════════════
    # FILESYSTEM (8 phrases)
    # ═══════════════════════════════════════════════════
    ("clone that file for me", "file.copy", "filesystem", "colloquial"),
    ("make a fresh directory here", "folder.create", "filesystem", "colloquial"),
    ("I need to find a document", "file.search", "filesystem", "indirect"),
    ("give this file a new name", "file.rename", "filesystem", "indirect"),
    ("can you relocate this to the backup drive", "file.move", "filesystem", "indirect"),
    ("wipe that old temp folder", "folder.delete", "filesystem", "colloquial"),
    ("sort out the mess in my downloads", "folder.organize", "filesystem", "colloquial"),
    ("show me what's in the recycle bin", "cleanup.recycle_bin_query", "filesystem", "indirect"),

    # ═══════════════════════════════════════════════════
    # DOCUMENT (5 phrases)
    # ═══════════════════════════════════════════════════
    ("read the contents of that file", "document.read", "document", "direct"),
    ("fix the formatting in the report", "document.edit", "document", "indirect"),
    ("condense this into a brief overview", "document.summarize", "document", "indirect"),
    ("how do these two versions differ", "document.compare", "document", "question"),
    ("tell me what this document is about", "document.read_intel", "document", "indirect"),

    # ═══════════════════════════════════════════════════
    # SPREADSHEET (5 phrases)
    # ═══════════════════════════════════════════════════
    ("sort this spreadsheet by the last column", "spreadsheet.sort", "spreadsheet", "direct"),
    ("show me only the rows where amount exceeds 100", "spreadsheet.filter", "spreadsheet", "indirect"),
    ("add up all the values in column B", "spreadsheet.aggregate", "spreadsheet", "indirect"),
    ("these two sheets don't match, compare them", "spreadsheet.compare", "spreadsheet", "colloquial"),
    ("what does this workbook contain", "spreadsheet.inspect", "spreadsheet", "question"),

    # ═══════════════════════════════════════════════════
    # BROWSER (5 phrases)
    # ═══════════════════════════════════════════════════
    ("navigate to example.com", "browser.open_url", "browser", "direct"),
    ("locate the input box on this page", "browser.find", "browser", "indirect"),
    ("pull that picture down from the website", "browser.download", "browser", "colloquial"),
    ("where am I right now on the web", "browser.get_url", "browser", "question"),
    ("take a snapshot of this webpage", "browser.screenshot", "browser", "colloquial"),

    # ═══════════════════════════════════════════════════
    # SYSTEM / HARDWARE (8 phrases)
    # ═══════════════════════════════════════════════════
    ("lower the sound level", "volume.down", "system", "colloquial"),
    ("how much room is left on my drive", "hardware.storage", "system", "question"),
    ("am I running low on battery", "hardware.battery", "system", "question"),
    ("grab what's on the display", "screen.capture", "system", "colloquial"),
    ("lock this machine", "workstation.lock", "system", "colloquial"),
    ("dim the screen a little", "display.brightness_set", "system", "indirect"),
    ("what are my system resources doing", "hardware.stats", "system", "question"),
    ("connect to a wireless network", "network.connect_wifi", "system", "indirect"),

    # ═══════════════════════════════════════════════════
    # MEDIA (4 phrases)
    # ═══════════════════════════════════════════════════
    ("play the next song", "media.next", "media", "direct"),
    ("pause what's currently playing", "media.play_pause", "media", "colloquial"),
    ("end the audio playback", "media.stop", "media", "indirect"),
    ("go back to the previous track", "media.previous", "media", "direct"),

    # ═══════════════════════════════════════════════════
    # NETWORK (2 phrases)
    # ═══════════════════════════════════════════════════
    ("scan for nearby wifi signals", "network.list_wifi", "network", "colloquial"),
    ("which wifi networks can I join", "network.list_wifi", "network", "question"),

    # ═══════════════════════════════════════════════════
    # PROCESS (2 phrases)
    # ═══════════════════════════════════════════════════
    ("what processes are active", "process.list", "process", "question"),
    ("give me details on that running task", "process.inspect", "process", "indirect"),

    # ═══════════════════════════════════════════════════
    # CLIPBOARD (2 phrases)
    # ═══════════════════════════════════════════════════
    ("put that text on the clipboard", "clipboard.copy", "clipboard", "colloquial"),
    ("retrieve what I copied last", "clipboard.paste", "clipboard", "colloquial"),

    # ═══════════════════════════════════════════════════
    # NOTES (2 phrases)
    # ═══════════════════════════════════════════════════
    ("jot something down for later", "notes.create", "notes", "colloquial"),
    ("show me my saved notes", "notes.list", "notes", "indirect"),

    # ═══════════════════════════════════════════════════
    # NON-ACTIONABLE (10 phrases) — must return null
    # ═══════════════════════════════════════════════════
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
print("  PHASE 3 STEP 2: BROAD NOVEL-PHRASING MEASUREMENT")
print(f"  {len(PHRASES)} phrases across "
      f"{len(set(p[2] for p in PHRASES))} families, "
      f"{len(set(p[1] for p in PHRASES if p[1]))} unique capabilities")
print("=" * 80)
print()

results = []

for i, (phrase, expected, family, label) in enumerate(PHRASES):
    gate = LLMIntentResolver.looks_actionable(phrase)

    if not gate:
        correct = (expected is None)
        result = {
            "phrase": phrase,
            "expected": expected,
            "got": None,
            "family": family,
            "label": label,
            "gate": "REJECT",
            "correct": correct,
        }
        tag = "CORRECT_NULL" if correct else "FALSE_NEGATIVE"
        print(f"  [{tag:20s}] [{family:14s}] \"{phrase}\"")
    else:
        c = engine._try_semantic_intent_resolution(phrase)
        op = (c.get("operation") or c.get("intent")) if c else None

        correct = (op == expected)
        result = {
            "phrase": phrase,
            "expected": expected,
            "got": op,
            "family": family,
            "label": label,
            "gate": "PASS",
            "correct": correct,
        }
        if expected is None:
            tag = "FALSE_POSITIVE"
        elif op == expected:
            tag = "CORRECT"
        elif op is None:
            tag = "LLM_NULL"
        else:
            tag = f"WRONG:{op}"
        print(f"  [{tag:20s}] [{family:14s}] \"{phrase}\" => {op}")

    results.append(result)
    time.sleep(0.5)

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

# False positive rate specifically
print(f"  FALSE POSITIVE RATE: {false_pos}/{len(non_actionable)} ({100*false_pos/len(non_actionable):.1f}%)")
print(f"  FALSE NEGATIVE RATE: {false_neg}/{len(actionable)} ({100*false_neg/len(actionable):.1f}%)")
print()

# By family
print("  BY FAMILY:")
families = {}
for r in results:
    fam = r["family"]
    if fam not in families:
        families[fam] = {"total": 0, "correct": 0, "false_neg": 0, "false_pos": 0}
    families[fam]["total"] += 1
    if r["correct"]:
        families[fam]["correct"] += 1
    else:
        if r["expected"] is not None:
            families[fam]["false_neg"] += 1
        else:
            families[fam]["false_pos"] += 1

for fam in sorted(families.keys()):
    fam_data = families[fam]
    acc = 100 * fam_data["correct"] / fam_data["total"]
    print(f"    {fam:20s}: {fam_data['correct']}/{fam_data['total']} ({acc:.1f}%)"
          f"  [FN:{fam_data['false_neg']} FP:{fam_data['false_pos']}]")

print()
print("  FAILED PHRASES:")
for r in results:
    if not r["correct"]:
        fptype = "FALSE_POSITIVE" if r["expected"] is None else "FALSE_NEGATIVE"
        print(f"    [{fptype:16s}] [{r['family']:14s}] \"{r['phrase']}\"")
        print(f"      expected={r['expected']}, got={r['got']}, gate={r['gate']}")

# Save raw results
with open("phase3_step2_broad_measurement.json", "w") as f:
    json.dump(results, f, indent=2)
print()
print("  Raw results saved to phase3_step2_broad_measurement.json")
