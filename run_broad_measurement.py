"""
Phase 3 broad novel-phrasing measurement.
60+ phrases across 15+ capabilities, 5+ families.
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
PHRASES = [
    # === APPLICATION (4) ===
    ("fire up the web browser", "application.open", "application", "direct"),
    ("shut down word", "application.close", "application", "direct"),
    ("what apps are running right now", "application.list", "application", "question"),
    ("swap over to excel", "application.open", "application", "colloquial"),

    # === GUI (4) ===
    ("click the save button", "gui.click", "gui", "direct"),
    ("type my email into the box", "gui.type_text", "gui", "direct"),
    ("scroll down to see more", "gui.scroll", "gui", "direct"),
    ("select everything in the list", "gui.select", "gui", "indirect"),

    # === FILESYSTEM (7) ===
    ("duplicate this document", "file.copy", "filesystem", "colloquial"),
    ("reorganize my downloads folder", "folder.organize", "filesystem", "indirect"),
    ("make a new folder on the desktop", "folder.create", "filesystem", "direct"),
    ("where did that file go", "file.search", "filesystem", "question"),
    ("rename this to something shorter", "file.rename", "filesystem", "indirect"),
    ("can you move this to the archives", "file.move", "filesystem", "indirect"),
    ("clean up my recycle bin", "cleanup.empty_recycle_bin", "filesystem", "colloquial"),

    # === DOCUMENT (4) ===
    ("what does this file say", "document.read", "document", "question"),
    ("fix the typo in section 3", "document.edit", "document", "indirect"),
    ("give me a summary of this report", "document.summarize", "document", "indirect"),
    ("how does this doc compare to the other one", "document.compare", "document", "question"),

    # === SPREADSHEET (4) ===
    ("compare these two spreadsheets", "spreadsheet.compare", "spreadsheet", "direct"),
    ("arrange the data by date", "spreadsheet.sort", "spreadsheet", "indirect"),
    ("what's the total of column C", "spreadsheet.aggregate", "spreadsheet", "question"),
    ("filter the rows where status is complete", "spreadsheet.filter", "spreadsheet", "direct"),

    # === BROWSER (4) ===
    ("go to github.com", "browser.open_url", "browser", "direct"),
    ("find the search box on this page", "browser.find", "browser", "direct"),
    ("grab that image from the site", "browser.download", "browser", "colloquial"),
    ("what's the url of this page", "browser.get_url", "browser", "question"),

    # === SYSTEM / HARDWARE (7) ===
    ("turn the volume down", "volume.down", "system", "direct"),
    ("how much disk space do I have left", "hardware.storage", "system", "question"),
    ("what's my battery level", "hardware.battery", "system", "question"),
    ("capture my screen", "screen.capture", "system", "colloquial"),
    ("secure my workstation", "workstation.lock", "system", "colloquial"),
    ("make the display brighter", "display.brightness_set", "system", "indirect"),
    ("check my system stats", "hardware.stats", "system", "indirect"),

    # === MEDIA (4) ===
    ("resume the music", "media.play_pause", "media", "indirect"),
    ("skip to the next track", "media.next", "media", "direct"),
    ("stop the playback", "media.stop", "media", "direct"),
    ("what song is playing", "media.play_pause", "media", "question"),

    # === NETWORK (2) ===
    ("connect to wifi", "network.connect_wifi", "network", "direct"),
    ("what networks are available", "network.list_wifi", "network", "question"),

    # === PROCESS (2) ===
    ("what's running on my computer", "process.list", "process", "question"),
    ("tell me about that process", "process.inspect", "process", "indirect"),

    # === CLIPBOARD (2) ===
    ("copy that to my clipboard", "clipboard.copy", "clipboard", "direct"),
    ("paste what I copied earlier", "clipboard.paste", "clipboard", "direct"),

    # === NOTES (2) ===
    ("create a note for later", "notes.create", "notes", "direct"),
    ("pull up my notes", "notes.list", "notes", "colloquial"),

    # === FOLDER (3) ===
    ("make a new directory here", "folder.create", "filesystem", "direct"),
    ("remove that empty folder", "folder.delete", "filesystem", "direct"),
    ("where is my documents folder", "folder.open", "filesystem", "question"),

    # === NON-ACTIONABLE (10) ===
    ("this is a beautiful day outside", None, "conversational", "statement"),
    ("I love how this turned out", None, "conversational", "opinion"),
    ("can you believe it's already friday", None, "conversational", "exclamation"),
    ("what do you think about artificial intelligence", None, "conversational", "opinion_question"),
    ("my cat is sleeping on the keyboard right now", None, "conversational", "observation"),
    ("set the table for dinner tonight", None, "conversational", "non_computer"),
    ("open the window it's really hot in here", None, "conversational", "physical_action"),
    ("move to a new city next spring", None, "conversational", "life_event"),
    ("I think we should reconsider the whole approach", None, "conversational", "opinion"),
    ("the weather has been terrible this week", None, "conversational", "statement"),
]

print("=" * 80)
print("  PHASE 3 BROAD NOVEL-PHRASING MEASUREMENT")
print(f"  {len(PHRASES)} phrases across "
      f"{len(set(p[2] for p in PHRASES))} families")
print("=" * 80)
print()

results = []

for i, (phrase, expected, family, label) in enumerate(PHRASES):
    gate = LLMIntentResolver.looks_actionable(phrase)

    if not gate:
        # Gate rejected — check if correct
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
        # Gate passed — try LLM
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
    time.sleep(2)

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

# By family
print("  BY FAMILY:")
families = {}
for r in results:
    fam = r["family"]
    if fam not in families:
        families[fam] = {"total": 0, "correct": 0}
    families[fam]["total"] += 1
    if r["correct"]:
        families[fam]["correct"] += 1

for fam in sorted(families.keys()):
    f = families[fam]
    print(f"    {fam:20s}: {f['correct']}/{f['total']} ({100*f['correct']/f['total']:.1f}%)")

print()
print("  FAILED PHRASES:")
for r in results:
    if not r["correct"]:
        print(f"    [{r['family']:14s}] \"{r['phrase']}\"")
        print(f"      expected={r['expected']}, got={r['got']}, gate={r['gate']}")

# Save raw results
with open("phase3_broad_measurement.json", "w") as f:
    json.dump(results, f, indent=2)
print()
print("  Raw results saved to phase3_broad_measurement.json")
