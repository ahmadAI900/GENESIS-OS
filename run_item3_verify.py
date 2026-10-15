"""Item 3 verification: 7 original gaps + safety suite + 5 new state-verb phrases."""
import sys
sys.path.insert(0, '.')
from genesis_os.llm_intent_resolver import LLMIntentResolver

print("=" * 70)
print("  ITEM 3 VERIFICATION")
print("=" * 70)

# === 7 original gate-rejected phrases (must now PASS) ===
print("\n--- 7 Original Gaps (must all PASS) ---")
SEVEN = [
    ("how do these two versions differ", "document.compare"),
    ("these two sheets don't match, compare them", "spreadsheet.compare"),
    ("what does this workbook contain", "spreadsheet.inspect"),
    ("where am I right now on the web", "browser.get_url"),
    ("how much room is left on my drive", "hardware.storage"),
    ("what are my system resources doing", "hardware.stats"),
    ("what processes are active", "process.list"),
]
s7_pass = 0
for phrase, expected in SEVEN:
    r = LLMIntentResolver.looks_actionable(phrase)
    tag = "PASS" if r else "FAIL"
    if r: s7_pass += 1
    print(f"  [{tag}] \"{phrase}\" -> {expected}")
print(f"  Result: {s7_pass}/7")

# === Safety suite (must not regress) ===
print("\n--- Category A: Bug phrase (10x, must REJECT) ---")
BUG = "hii now i make you able to control my computer"
a_pass = 0
for i in range(10):
    r = LLMIntentResolver.looks_actionable(BUG)
    tag = "REJECT" if not r else "FAIL"
    if not r: a_pass += 1
    print(f"  [{tag}] run {i+1}/10")
print(f"  Result: {a_pass}/10")

print("\n--- Category B: Imperative (must PASS) ---")
B = ["open notepad", "please open notepad", "copy this file to downloads",
     "take a screenshot", "lock my computer", "set the volume to 40",
     "delete the old folder", "make my screen dimmer", "could you open notepad for me",
     "boot up the spreadsheet program", "shut that program down",
     "press that button on the screen", "enter my username in the text field",
     "scroll up a bit", "highlight all the text here", "clone that file for me",
     "give this file a new name", "wipe that old temp folder",
     "navigate to example.com", "play the next song", "go back to the previous track",
     "scan for nearby wifi signals", "lock this machine"]
b_pass = 0
for p in B:
    r = LLMIntentResolver.looks_actionable(p)
    tag = "PASS" if r else "FAIL"
    if r: b_pass += 1
    print(f"  [{tag}] \"{p}\"")
print(f"  Result: {b_pass}/{len(B)}")

print("\n--- Category C: Question-format (must PASS) ---")
C = ["what's eating up my disk space", "how bright is my screen right now",
     "what is playing right now", "stash this somewhere else",
     "get rid of this file for me", "how do these two sheets stack up against each other",
     "am I running low on battery", "what processes are active"]
c_pass = 0
for p in C:
    r = LLMIntentResolver.looks_actionable(p)
    tag = "PASS" if r else "FAIL"
    if r: c_pass += 1
    print(f"  [{tag}] \"{p}\"")
print(f"  Result: {c_pass}/{len(C)}")

print("\n--- Narration guard (must REJECT) ---")
P = ["she set the table before we arrived", "she opened the window and looked outside",
     "he deleted his old photos years ago", "they moved to a new city last spring",
     "he closed the door quietly behind him", "we organized the files last quarter",
     "he set the alarm for 6am", "we set up the new office yesterday"]
p_pass = 0
for p in P:
    r = LLMIntentResolver.looks_actionable(p)
    tag = "REJECT" if not r else "FAIL"
    if not r: p_pass += 1
    print(f"  [{tag}] \"{p}\"")
print(f"  Result: {p_pass}/{len(P)}")

print("\n--- Non-actionable (must REJECT) ---")
NA = ["do you think it's going to rain today?", "you make me happy",
      "hello there friend", "what can you do for me",
      "the sunset looks incredible tonight", "I just adopted a new puppy",
      "do you enjoy reading books", "my neighbor's dog won't stop barking",
      "let's discuss the quarterly budget next week", "coffee is much better than tea"]
na_pass = 0
for p in NA:
    r = LLMIntentResolver.looks_actionable(p)
    tag = "REJECT" if not r else "FAIL"
    if not r: na_pass += 1
    print(f"  [{tag}] \"{p}\"")
print(f"  Result: {na_pass}/{len(NA)}")

# === 5 new state-verb test phrases (must PASS) ===
print("\n--- 5 New State-Verb Phrases (must PASS) ---")
NEW = [
    ("what's using up all my memory", "hardware.stats"),
    ("how many tabs do I have open", "browser.get_tabs"),
    ("which apps are running right now", "process.list"),
    ("what's the battery status", "hardware.battery"),
    ("where did that download go", "file.search"),
]
n_pass = 0
for phrase, expected in NEW:
    r = LLMIntentResolver.looks_actionable(phrase)
    tag = "PASS" if r else "FAIL"
    if r: n_pass += 1
    print(f"  [{tag}] \"{phrase}\" -> {expected}")
print(f"  Result: {n_pass}/{len(NEW)}")

# === SUMMARY ===
print("\n" + "=" * 70)
print("  SUMMARY")
print("=" * 70)
total_correct = s7_pass + a_pass + b_pass + c_pass + p_pass + na_pass + n_pass
total_tests = 7 + 10 + len(B) + len(C) + len(P) + len(NA) + len(NEW)
print(f"  7 original gaps:     {s7_pass}/7")
print(f"  Bug phrase (10x):    {a_pass}/10")
print(f"  Imperative:          {b_pass}/{len(B)}")
print(f"  Question-format:     {c_pass}/{len(C)}")
print(f"  Narration guard:     {p_pass}/{len(P)}")
print(f"  Non-actionable:      {na_pass}/{len(NA)}")
print(f"  New state-verb:      {n_pass}/{len(NEW)}")
print(f"  TOTAL:               {total_correct}/{total_tests}")
if total_correct == total_tests:
    print("  ALL PASSED")
else:
    print(f"  FAILURES: {total_tests - total_correct}")
