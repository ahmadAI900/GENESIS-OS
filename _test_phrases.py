"""
Broader regression test: key phrases from the 61-phrase set.
"""
import sys
import time
sys.path.insert(0, '.')

from ai.providers import GroqProvider
from genesis_os.llm_intent_resolver import LLMIntentResolver
from ai.ai_engine import AIEngine
from agents.workflow_decision import WorkflowDecisionEngine

groq = GroqProvider(api_key="REDACTED_GROQ_KEY")
ai = AIEngine(providers=[groq])
wde = WorkflowDecisionEngine()
intent = LLMIntentResolver(ai_engine=ai, decision_engine=wde)

PHRASES = [
    ("boot up the spreadsheet program", "application.open"),
    ("press that button on the screen", "gui.click"),
    ("clone that file for me", "file.copy"),
    ("make a fresh directory here", "folder.create"),
    ("navigate to example.com", "browser.open_url"),
    ("lower the sound level", "volume.down"),
    ("lock this machine", "workstation.lock"),
    ("play the next song", "media.next"),
    ("scan for nearby wifi signals", "network.list_wifi"),
    ("what processes are active", "process.list"),
    ("jot something down for later", "notes.create"),
    ("the sunset looks incredible tonight", None),
    ("I just adopted a new puppy", None),
    ("fix the formatting in the report", "document.edit"),
    ("condense this into a brief overview", "document.summarize"),
    ("how do these two versions differ", "document.compare"),
    ("put that text on the clipboard", "clipboard.copy"),
    ("retrieve what I copied last", "clipboard.paste"),
]

correct = 0
for phrase, expected in PHRASES:
    gate = LLMIntentResolver.looks_actionable(phrase)
    if not gate:
        got = None
    else:
        c = intent.resolve(phrase)
        got = c.get("operation") if c else None
    is_correct = (got == expected)
    if is_correct:
        correct += 1
    marker = "+" if is_correct else "-"
    print("%s %-45s expected=%-25s got=%s" % (marker, phrase[:45], str(expected), got))
    sys.stdout.flush()
    time.sleep(0.5)

print()
print("Result: %d/%d (%.1f%%)" % (correct, len(PHRASES), 100 * correct / len(PHRASES)))
