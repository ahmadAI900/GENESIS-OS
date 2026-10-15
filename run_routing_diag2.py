"""
Routing diagnostic: intercept generate_response to capture ACTUAL backend used.
Then run 10 failed phrases through a prompt-format variant.
"""
import sys, time, json, io
sys.path.insert(0, '.')
from ai.ai_engine import AIEngine
from genesis_os.llm_intent_resolver import LLMIntentResolver

ai = AIEngine()

# Intercept generate_response to log actual backend
original_gen = ai.generate_response
routing_log = []

def intercepted_gen(prompt, mode=None, complexity=None):
    backend = mode or "auto"
    result = original_gen(prompt, mode=mode, complexity=complexity)
    routing_log.append({"backend": backend, "result_type": type(result).__name__})
    return result

ai.generate_response = intercepted_gen

intent = LLMIntentResolver(ai_engine=ai)

# ================================================================
# PART 1: Run all 51 actionable phrases and track actual routing
# ================================================================
PHRASES = [
    ("boot up the spreadsheet program", "application.open"),
    ("shut that program down", "application.close"),
    ("tell me what programs I have open", "application.list"),
    ("switch to the browser", "application.open"),
    ("press that button on the screen", "gui.click"),
    ("enter my username in the text field", "gui.type_text"),
    ("scroll up a bit", "gui.scroll"),
    ("highlight all the text here", "gui.select"),
    ("clone that file for me", "file.copy"),
    ("make a fresh directory here", "folder.create"),
    ("I need to find a document", "file.search"),
    ("give this file a new name", "file.rename"),
    ("can you relocate this to the backup drive", "file.move"),
    ("wipe that old temp folder", "folder.delete"),
    ("sort out the mess in my downloads", "folder.organize"),
    ("show me what's in the recycle bin", "cleanup.recycle_bin_query"),
    ("read the contents of that file", "document.read"),
    ("fix the formatting in the report", "document.edit"),
    ("condense this into a brief overview", "document.summarize"),
    ("how do these two versions differ", "document.compare"),
    ("tell me what this document is about", "document.read_intel"),
    ("sort this spreadsheet by the last column", "spreadsheet.sort"),
    ("show me only the rows where amount exceeds 100", "spreadsheet.filter"),
    ("add up all the values in column B", "spreadsheet.aggregate"),
    ("these two sheets don't match, compare them", "spreadsheet.compare"),
    ("what does this workbook contain", "spreadsheet.inspect"),
    ("navigate to example.com", "browser.open_url"),
    ("locate the input box on this page", "browser.find"),
    ("pull that picture down from the website", "browser.download"),
    ("where am I right now on the web", "browser.get_url"),
    ("take a snapshot of this webpage", "browser.screenshot"),
    ("lower the sound level", "volume.down"),
    ("how much room is left on my drive", "hardware.storage"),
    ("am I running low on battery", "hardware.battery"),
    ("grab what's on the display", "screen.capture"),
    ("lock this machine", "workstation.lock"),
    ("dim the screen a little", "display.brightness_set"),
    ("what are my system resources doing", "hardware.stats"),
    ("connect to a wireless network", "network.connect_wifi"),
    ("play the next song", "media.next"),
    ("pause what's currently playing", "media.play_pause"),
    ("end the audio playback", "media.stop"),
    ("go back to the previous track", "media.previous"),
    ("scan for nearby wifi signals", "network.list_wifi"),
    ("which wifi networks can I join", "network.list_wifi"),
    ("what processes are active", "process.list"),
    ("give me details on that running task", "process.inspect"),
    ("put that text on the clipboard", "clipboard.copy"),
    ("retrieve what I copied last", "clipboard.paste"),
    ("jot something down for later", "notes.create"),
    ("show me my saved notes", "notes.list"),
]

print("=" * 80)
print("  ROUTING DIAGNOSTIC — ALL 51 ACTIONABLE PHRASES")
print("  Intercepting generate_response() to capture ACTUAL backend")
print("=" * 80)

results = []
for phrase, expected in PHRASES:
    routing_log.clear()
    start = time.time()
    c = intent.resolve(phrase)
    elapsed = time.time() - start
    
    op = (c.get("operation") or c.get("intent")) if c else None
    correct = (op == expected)
    
    # Parse routing log
    modes_called = [r["backend"] for r in routing_log]
    if "cloud" in modes_called and "local" in modes_called:
        routing = "cloud_then_local"
    elif "cloud" in modes_called:
        routing = "cloud_only"
    elif "local" in modes_called:
        routing = "local_only"
    elif "auto" in modes_called:
        routing = "auto"
    else:
        routing = "none"
    
    tag = "OK" if correct else ("NULL" if op is None else f"WRONG:{op}")
    marker = "OK" if correct else "FAIL"
    
    print(f"  {marker} [{routing:20s}] modes={modes_called} \"{phrase}\" -> {op} ({elapsed:.1f}s)")
    
    results.append({
        "phrase": phrase,
        "expected": expected,
        "got": op,
        "correct": correct,
        "routing": routing,
        "modes_called": modes_called,
        "time": round(elapsed, 1),
    })
    time.sleep(0.3)

# Summary
print("\n" + "=" * 80)
print("  ROUTING SUMMARY")
print("=" * 80)
from collections import Counter
routing_counts = Counter(r["routing"] for r in results)
for routing, count in routing_counts.most_common():
    subset = [r for r in results if r["routing"] == routing]
    correct_count = sum(1 for r in subset if r["correct"])
    print(f"  {routing:20s}: {count} phrases ({correct_count} correct)")

# How many times was cloud called?
cloud_calls = sum(1 for r in results if "cloud" in r["modes_called"])
local_calls = sum(1 for r in results if "local" in r["modes_called"])
print(f"\n  Cloud calls: {cloud_calls}/{len(results)}")
print(f"  Local calls: {local_calls}/{len(results)}")
