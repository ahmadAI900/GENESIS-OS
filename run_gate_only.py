"""Gate-only accuracy measurement (no LLM calls)."""
import sys
sys.path.insert(0, '.')
from genesis_os.llm_intent_resolver import LLMIntentResolver

# Same 61 phrases from Step 2
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

print("=" * 70)
print("  GATE-ONLY ACCURACY (no LLM calls)")
print("=" * 70)
print()

gate_pass = 0
gate_reject = 0
gate_correct_actionable = 0
gate_correct_non_actionable = 0
gate_fn = 0  # actionable but gate rejected
gate_fp = 0  # non-actionable but gate passed (would be false positive if LLM ran)

for phrase, expected, family, label in PHRASES:
    r = LLMIntentResolver.looks_actionable(phrase)
    is_actionable = expected is not None
    
    if r:
        gate_pass += 1
        if is_actionable:
            gate_correct_actionable += 1
            tag = "PASS_OK"
        else:
            gate_fp += 1
            tag = "PASS_FP"
    else:
        gate_reject += 1
        if is_actionable:
            gate_fn += 1
            tag = "REJECT_FN"
        else:
            gate_correct_non_actionable += 1
            tag = "REJECT_OK"
    
    print(f"  [{tag:12s}] [{family:14s}] \"{phrase}\"")

print()
print("=" * 70)
print("  GATE SUMMARY")
print("=" * 70)
total = len(PHRASES)
actionable = sum(1 for p in PHRASES if p[1] is not None)
non_actionable = total - actionable
gate_correct = gate_correct_actionable + gate_correct_non_actionable

print(f"  Total: {total}")
print(f"  Gate correct: {gate_correct}/{total} ({100*gate_correct/total:.1f}%)")
print(f"  Actionable: {actionable}")
print(f"    Gate PASS (correct): {gate_correct_actionable}")
print(f"    Gate REJECT (false negative): {gate_fn}")
print(f"  Non-actionable: {non_actionable}")
print(f"    Gate REJECT (correct): {gate_correct_non_actionable}")
print(f"    Gate PASS (false positive risk): {gate_fp}")
print()
print(f"  GATE FALSE NEGATIVE RATE: {gate_fn}/{actionable} ({100*gate_fn/actionable:.1f}%)")
print(f"  GATE FALSE POSITIVE RATE: {gate_fp}/{non_actionable} ({100*gate_fp/non_actionable:.1f}%)")

# List phrases that gate rejects (would need LLM to handle)
print()
print("  GATE-REJECTED ACTIONABLE PHRASES (LLM needed):")
for phrase, expected, family, label in PHRASES:
    if expected is not None and not LLMIntentResolver.looks_actionable(phrase):
        print(f"    [{family:14s}] \"{phrase}\" -> {expected}")
