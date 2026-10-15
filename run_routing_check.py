"""
Test 1: Verify which model ACTUALLY handled each Item 2 call.
The AI engine's _select_backend() sends simple requests to local by default.
We need to know if Gemma was even called.

Test 2: Prompt-format fragility test — take 10 failed phrases,
reformat the prompt to be Gemma-friendly, and compare.
"""
import sys, time, json, io, os
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()
intent = LLMIntentResolver(ai_engine=ai)

# ================================================================
# PART 1: Check routing for ALL 61 Item 2 phrases
# ================================================================
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
]

# Patch _select_backend to log what it returns
original_select = ai._select_backend
routing_decisions = []
def patched_select(prompt, complexity=None):
    result = original_select(prompt, complexity)
    routing_decisions.append(result)
    return result
ai._select_backend = patched_select

print("=" * 80)
print("  PART 1: ROUTING VERIFICATION — WHICH MODEL ACTUALLY HANDLES EACH PHRASE?")
print("=" * 80)

results = []
for phrase, expected, family in PHRASES:
    routing_decisions.clear()
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()
    
    start = time.time()
    c = intent._resolve_with_cloud_or_local(phrase)
    elapsed = time.time() - start
    
    sys.stdout = old_stdout
    routing_output = captured.getvalue()
    
    op = (c.get("operation") or c.get("intent")) if c else None
    routing = routing_decisions[-1] if routing_decisions else "unknown"
    
    # Check for fallback
    cloud_failed = "Cloud model failed" in routing_output
    if cloud_failed:
        routing = "cloudFAILED->local"
    
    tag = "OK" if op == expected else ("NULL" if op is None else f"WRONG")
    if expected is None:
        tag = "OK" if op is None else f"FP:{op}"
    
    results.append({
        "phrase": phrase,
        "expected": expected,
        "got": op,
        "family": family,
        "routing": routing,
        "cloud_failed": cloud_failed,
        "correct": op == expected,
    })
    
    marker = "✓" if tag == "OK" else "✗"
    print(f"  {marker} [{routing:12s}] \"{phrase}\" -> {op} (expected {expected}) [{family}]")
    time.sleep(0.2)

# Summary
print("\n" + "=" * 80)
print("  ROUTING SUMMARY")
print("=" * 80)
from collections import Counter
routing_counts = Counter(r["routing"] for r in results)
for routing, count in routing_counts.most_common():
    print(f"    {routing}: {count} phrases")

# How many were routed to local?
local_phrases = [r for r in results if r["routing"] == "local"]
cloud_phrases = [r for r in results if r["routing"] == "cloud"]
both_phrases = [r for r in results if r["routing"] == "cloudFAILED->local"]
print(f"\n  Local (qwen2.5): {len(local_phrases)} phrases")
print(f"  Cloud (Gemma 4): {len(cloud_phrases)} phrases")
print(f"  Cloud failed->local: {len(both_phrases)} phrases")

if cloud_phrases:
    cloud_correct = sum(1 for r in cloud_phrases if r["correct"])
    cloud_wrong = sum(1 for r in cloud_phrases if not r["correct"])
    print(f"\n  Of {len(cloud_phrases)} Gemma-handled phrases:")
    print(f"    Correct: {cloud_correct}")
    print(f"    Wrong: {cloud_wrong}")

if local_phrases:
    local_correct = sum(1 for r in local_phrases if r["correct"])
    local_wrong = sum(1 for r in local_phrases if not r["correct"])
    print(f"\n  Of {len(local_phrases)} local-handled phrases:")
    print(f"    Correct: {local_correct}")
    print(f"    Wrong: {local_wrong}")
