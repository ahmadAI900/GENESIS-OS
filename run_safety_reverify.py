"""Safety re-verification: gate suite (no LLM dependency)."""
import sys
sys.path.insert(0, '.')
from genesis_os.llm_intent_resolver import LLMIntentResolver

print("=" * 70)
print("  GATE SUITE RE-VERIFICATION (post-fix)")
print("=" * 70)

BUG = "hii now i make you able to control my computer"
print("\n--- Original bug phrase (10x) ---")
for i in range(10):
    r = LLMIntentResolver.looks_actionable(BUG)
    print(f"  [{('REJECT' if not r else 'FAIL')}] run {i+1}/10")

print("\n--- Category B: imperative (must PASS) ---")
B = ["open notepad", "please open notepad", "copy this file to downloads",
     "take a screenshot", "lock my computer", "set the volume to 40",
     "delete the old folder", "make my screen dimmer", "could you open notepad for me",
     "boot up the spreadsheet program", "shut that program down",
     "press that button on the screen", "enter my username in the text field",
     "scroll up a bit", "highlight all the text here", "clone that file for me",
     "give this file a new name", "wipe that old temp folder",
     "navigate to example.com", "play the next song", "go back to the previous track",
     "scan for nearby wifi signals", "lock this machine"]
for p in B:
    r = LLMIntentResolver.looks_actionable(p)
    print(f"  [{('PASS' if r else 'FAIL')}] \"{p}\"")

print("\n--- Category C: question-format (must PASS) ---")
C = ["what's eating up my disk space", "how bright is my screen right now",
     "what is playing right now", "stash this somewhere else",
     "get rid of this file for me", "how do these two sheets stack up against each other",
     "am I running low on battery", "what processes are active"]
for p in C:
    r = LLMIntentResolver.looks_actionable(p)
    print(f"  [{('PASS' if r else 'FAIL')}] \"{p}\"")

print("\n--- Narration guard (must REJECT) ---")
P = ["she set the table before we arrived", "she opened the window and looked outside",
     "he deleted his old photos years ago", "they moved to a new city last spring",
     "he closed the door quietly behind him", "we organized the files last quarter",
     "he set the alarm for 6am", "we set up the new office yesterday"]
for p in P:
    r = LLMIntentResolver.looks_actionable(p)
    print(f"  [{('REJECT' if not r else 'FAIL')}] \"{p}\"")

print("\n--- Other non-actionable (must REJECT) ---")
NA = ["do you think it's going to rain today?", "you make me happy",
      "hello there friend", "what can you do for me",
      "the sunset looks incredible tonight", "I just adopted a new puppy",
      "do you enjoy reading books", "my neighbor's dog won't stop barking",
      "let's discuss the quarterly budget next week", "coffee is much better than tea"]
for p in NA:
    r = LLMIntentResolver.looks_actionable(p)
    print(f"  [{('REJECT' if not r else 'FAIL')}] \"{p}\"")

# Count results
all_tests = []
for p in B:
    all_tests.append(("imperative", p, True, LLMIntentResolver.looks_actionable(p)))
for p in C:
    all_tests.append(("question", p, True, LLMIntentResolver.looks_actionable(p)))
for p in P:
    all_tests.append(("narration", p, False, LLMIntentResolver.looks_actionable(p)))
for p in NA:
    all_tests.append(("non_actionable", p, False, LLMIntentResolver.looks_actionable(p)))

print("\n" + "=" * 70)
print("  SAFETY SUMMARY")
print("=" * 70)
correct = sum(1 for cat, p, expect, got in all_tests if got == expect)
total = len(all_tests)
print(f"  Total: {total}")
print(f"  Correct: {correct}/{total} ({100*correct/total:.1f}%)")
fails = [(cat, p, expect, got) for cat, p, expect, got in all_tests if got != expect]
if fails:
    print(f"  FAILURES ({len(fails)}):")
    for cat, p, expect, got in fails:
        print(f"    [{cat}] \"{p}\" expected={expect} got={got}")
else:
    print("  ALL PASSED")
