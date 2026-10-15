"""Section 2 verification — exact prompt command, rewritten."""
from agents.workflow_decision import WorkflowDecisionEngine

e = WorkflowDecisionEngine()
for phrase, expect_target in [
    ("write Hello in notepad", "notepad"),
    ("type Hello from Genesis", None),
    ('type "Hello World" into notepad', "notepad"),
]:
    d = e.decide(phrase)
    assert d.get("level") == 3, f'FAIL {phrase!r}: level={d.get("level")}'
    assert d.get("intent") == "gui.type_text", f'FAIL {phrase!r}: intent={d.get("intent")}'
    print(
        f'PASS: {phrase!r} -> intent=gui.type_text '
        f'target={d.get("target")} params={d.get("parameters")}'
    )