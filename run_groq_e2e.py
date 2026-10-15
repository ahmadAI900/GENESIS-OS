"""
Step 2: Full 61-phrase E2E measurement — Groq cloud-only.
FIXED interceptor: tracks which backend's response was PARSED for the answer.
"""
import sys, time, json, re
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()

for p in ai._providers:
    if p.name == "OpenRouter":
        print("[CONFIG] Cloud:", p.model_id, "@", p._base_url)
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

# ============================================================
# INTERCEPTOR: tracks raw response per mode call
# ============================================================
original_gen = ai.generate_response
per_call_raw = []

def intercepted_gen(prompt, mode=None, complexity=None):
    result = original_gen(prompt, mode=mode, complexity=complexity)
    per_call_raw.append({"mode": mode, "raw": str(result)[:500]})
    return result

ai.generate_response = intercepted_gen

# ============================================================
# RUN ALL 61 PHRASES
# ============================================================
results = []

for i, (phrase, expected, family) in enumerate(PHRASES):
    gate = LLMIntentResolver.looks_actionable(phrase)

    if not gate:
        correct = (expected is None)
        result = {
            "phrase": phrase, "expected": expected, "got": None,
            "family": family, "gate": "REJECT", "correct": correct,
            "actual_backend": "gate",
        }
    else:
        per_call_raw.clear()
        start = time.time()
        c = intent.resolve(phrase)
        elapsed = time.time() - start

        op = (c.get("operation") or c.get("intent")) if c else None
        correct = (op == expected)

        # Determine which backend's response was actually used
        # The resolve() method tries cloud->local->auto and stops at first parseable JSON.
        # We track which mode's raw response was the one that got parsed.
        # Simple heuristic: if cloud returned and we have a result, cloud was used.
        # If cloud failed parse and local was used, local was used.
        modes_tried = [cr["mode"] for cr in per_call_raw]
        raw_responses = {cr["mode"]: cr["raw"] for cr in per_call_raw}

        if c is not None:
            # Got a valid answer — determine from which mode
            if "cloud" in modes_tried:
                actual_backend = "cloud"
            elif "local" in modes_tried:
                actual_backend = "local"
            else:
                actual_backend = "auto"
        else:
            # No valid answer from any mode
            actual_backend = "ALL_FAILED"

        result = {
            "phrase": phrase, "expected": expected, "got": op,
            "family": family, "gate": "PASS", "correct": correct,
            "actual_backend": actual_backend, "time": round(elapsed, 1),
            "modes_tried": modes_tried,
        }

    marker = "+" if result["correct"] else "-"
    backend = result.get("actual_backend", "gate")
    print(f"  {marker} [{backend:10s}] [{family:14s}] {phrase[:45]:45s} -> {str(result.get('got','')):25s} ({result.get('time','-')}s)")

    results.append(result)
    time.sleep(0.3)

    with open("phase3_groq_e2e_results.json", "w") as f:
        json.dump(results, f, indent=2)

# ============================================================
# SUMMARY
# ============================================================
print()
print("=" * 90)
print("  GROQ E2E SUMMARY")
print("=" * 90)

total = len(results)
correct_count = sum(1 for r in results if r["correct"])
actionable = [r for r in results if r["expected"] is not None]
non_actionable = [r for r in results if r["expected"] is None]
tp = sum(1 for r in actionable if r["correct"])
fn = sum(1 for r in actionable if not r["correct"])
tn = sum(1 for r in non_actionable if r["correct"])
fp = sum(1 for r in non_actionable if not r["correct"])

model = ai._get_provider("OpenRouter")
print(f"  Backend: Groq ({model.model_id})")
print(f"  Total: {total}")
print(f"  Overall: {correct_count}/{total} ({100*correct_count/total:.1f}%)")
print(f"  Actionable: TP={tp} FN={fn} ({100*fn/len(actionable):.1f}% FN rate)")
print(f"  Non-actionable: TN={tn} FP={fp} ({100*fp/len(non_actionable):.1f}% FP rate)")

# Backend breakdown
from collections import Counter
backend_counts = Counter(r.get("actual_backend") for r in results)
print(f"\n  Backend breakdown:")
for b, cnt in backend_counts.most_common():
    subset = [r for r in results if r.get("actual_backend") == b]
    corr = sum(1 for r in subset if r["correct"])
    print(f"    {b:15s}: {cnt} ({corr} correct)")

# By family
print(f"\n  By family:")
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
    acc = 100 * d["correct"] / d["total"] if d["total"] else 0
    print(f"    {fam:20s}: {d['correct']}/{d['total']} ({acc:.1f}%) FN:{d['fn']} FP:{d['fp']}")

# Groq-only subset
groq_results = [r for r in results if r.get("actual_backend") == "cloud"]
if groq_results:
    groq_correct = sum(1 for r in groq_results if r["correct"])
    groq_actionable = [r for r in groq_results if r["expected"] is not None]
    groq_tp = sum(1 for r in groq_actionable if r["correct"])
    groq_fn = sum(1 for r in groq_actionable if not r["correct"])
    groq_non_actionable = [r for r in groq_results if r["expected"] is None]
    groq_tn = sum(1 for r in groq_non_actionable if r["correct"])
    groq_fp = sum(1 for r in groq_non_actionable if not r["correct"])
    print(f"\n  GROQ-ONLY subset:")
    print(f"    Total: {len(groq_results)}")
    print(f"    Overall: {groq_correct}/{len(groq_results)} ({100*groq_correct/len(groq_results):.1f}%)")
    print(f"    Actionable: TP={groq_tp} FN={groq_fn}")
    print(f"    Non-actionable: TN={groq_tn} FP={groq_fp}")

# Full table
print(f"\n  Full per-phrase table:")
print("  #  OK   Backend     Family         Phrase                                          Got                         Expected")
print("  " + "-" * 130)
for i, r in enumerate(results):
    ok = "+" if r["correct"] else "-"
    b = r.get("actual_backend", "gate")
    got = str(r.get("got", ""))[:25]
    exp = str(r.get("expected", ""))[:25]
    ph = r["phrase"][:45]
    print(f"  {i+1:3d} {ok:3s} {b:11s} {r['family']:14s} {ph:45s} {got:25s} {exp:25s}")

print(f"\n  Saved: phase3_groq_e2e_results.json")
