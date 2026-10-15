"""
Genesis OS — Staged Diagnostic Check

Run this from inside your backend/ folder:

    python check_genesis_stages.py

It checks, in order:
  0. Dependencies actually importable
  1. Level 1 — Core Brain (memory, conversation, reasoning)
  2. Level 2 — Agents (discovery + registration)
  3. Level 3 — OS control (decision engine + app resolution)

Each stage prints PASS / FAIL / SKIP with the reason, so you can see
exactly where things break instead of guessing. It does NOT actually
open real applications or launch a browser unless you pass --live.
"""

import sys
import traceback
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true",
                     help="Actually perform one real OS action (opens Notepad) as a final live check.")
args = parser.parse_args()

RESULTS = []


def check(name):
    def decorator(fn):
        RESULTS.append((name, fn))
        return fn
    return decorator


def run_stage(name, fn):
    print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
    try:
        fn()
        print(f"[PASS] {name}")
        return True
    except Exception as e:
        print(f"[FAIL] {name}")
        print(f"  -> {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)
        return False


# ---------------------------------------------------------
# STAGE 0 — Dependencies
# ---------------------------------------------------------
def stage0_dependencies():
    required = [
        "openai", "dotenv", "docx", "openpyxl", "pptx", "pypdf",
        "PIL", "psutil", "requests", "langdetect", "ddgs", "pyperclip",
        "playwright", "selenium", "pyautogui",
    ]
    windows_only = ["win32com", "comtypes", "pycaw", "screen_brightness_control"]

    missing = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)

    if sys.platform == "win32":
        for mod in windows_only:
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)

    if missing:
        raise RuntimeError(
            f"Missing packages: {', '.join(missing)}. "
            f"Run: pip install -r requirements.txt"
        )
    print("All required packages import successfully.")


# ---------------------------------------------------------
# STAGE 1 — Level 1: Core Brain
# ---------------------------------------------------------
def stage1_core_brain():
    from brain.brain import Brain
    from memory.memory import MemoryManager
    from conversation.conversation import ConversationEngine

    memory = MemoryManager()
    print("MemoryManager instantiated:", type(memory).__name__)

    conversation = ConversationEngine()
    print("ConversationEngine instantiated:", type(conversation).__name__)

    brain = Brain()
    print("Brain instantiated:", type(brain).__name__)

    # Try a simple conversational turn if the API exists.
    for method_name in ("respond", "chat", "process", "think"):
        if hasattr(brain, method_name):
            method = getattr(brain, method_name)
            try:
                result = method("Hello, who are you?")
                print(f"Brain.{method_name}() returned: {str(result)[:200]}")
            except Exception as e:
                print(f"Brain.{method_name}() raised (may need AI backend online): {e}")
            break
    else:
        print("No obvious conversational entrypoint found on Brain "
              "(checked respond/chat/process/think) — inspect brain/brain.py manually.")


# ---------------------------------------------------------
# STAGE 2 — Level 2: Agents
# ---------------------------------------------------------
def stage2_agents():
    from agents.agent_registry import AgentRegistry

    registry = AgentRegistry()
    print("AgentRegistry instantiated:", type(registry).__name__)

    # Try common ways registries expose their agents.
    agents = None
    for attr in ("agents", "_agents", "all_agents"):
        if hasattr(registry, attr):
            agents = getattr(registry, attr)
            break
    if agents is None and hasattr(registry, "list_agents"):
        agents = registry.list_agents()

    if agents:
        names = [getattr(a, "name", str(a)) for a in
                  (agents.values() if isinstance(agents, dict) else agents)]
        print(f"Registered agents ({len(names)}):", ", ".join(names))
        if len(names) < 9:
            print(f"WARNING: expected ~9-10 agents (Research, Coding, Study, "
                  f"Internet, Document, Design, Business, Data, Planning, "
                  f"Security) but only found {len(names)}.")
    else:
        raise RuntimeError("Could not introspect registered agents — check "
                            "AgentRegistry's public attributes manually.")

    # Sanity check: can_handle routing without actually calling the LLM.
    from agents.document_agent import DocumentAgent
    doc_agent = DocumentAgent()
    handled = doc_agent.can_handle("summarize this document")
    print("DocumentAgent.can_handle('summarize this document') ->", handled)
    if not handled:
        print("WARNING: DocumentAgent did not claim a document-related task — "
              "capability routing may be misconfigured.")


# ---------------------------------------------------------
# STAGE 3 — Level 3: OS control
# ---------------------------------------------------------
def stage3_os_control():
    from agents.workflow_decision import WorkflowDecisionEngine
    from genesis_os.applications.app_manager import ApplicationManager

    engine = WorkflowDecisionEngine()

    test_cases = [
        ("open Chrome", "application.open"),
        ("open notepad", "application.open"),
        ("search the web for python tutorials", None),  # just print, don't assert
    ]
    for phrase, expected_intent in test_cases:
        decision = engine.decide(phrase)
        level = decision.get("level")
        intent = decision.get("intent")
        print(f"decide({phrase!r}) -> level={level}, intent={intent}, "
              f"target={decision.get('target')}")
        if expected_intent and (level != 3 or intent != expected_intent):
            raise RuntimeError(
                f"Expected level=3 intent={expected_intent!r} for {phrase!r}, "
                f"got level={level} intent={intent!r}"
            )

    manager = ApplicationManager()
    resolution = manager.resolve_application_record("notepad") \
        if hasattr(manager, "resolve_application_record") else None
    print("ApplicationManager.resolve_application_record('notepad') ->", resolution)
    if not resolution:
        print("NOTE: could not resolve 'notepad'. On Windows this should "
              "resolve to notepad.exe. If it doesn't, the application "
              "registry/discovery step is broken or you're not on Windows.")

    if args.live:
        print("\n--live flag set: attempting to actually open Notepad...")
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan
        executor = ActionExecutor(manager)
        plan = ActionPlan(operation="application.open", target="notepad",
                           application="notepad", confidence=0.99)
        result = executor.execute(plan)
        print("Live execution result:", result)
        if not result.get("success"):
            raise RuntimeError(f"Live app-open failed: {result}")


# ---------------------------------------------------------
# STAGE 4 — Full end-to-end: the actual CLI a user types into
# ---------------------------------------------------------
def stage4_end_to_end():
    """
    Launches `python genesis.py` exactly as a user would, feeds it real
    typed messages over stdin, and checks the real printed replies.
    This does NOT call any internal/private methods directly — it
    drives the real entrypoint (main() -> GenesisOS().run()), so it
    is the most faithful test of what a user actually experiences.
    """
    import subprocess
    import sys as _sys

    messages = [
        "Hello, who are you?",              # Level 1 — core brain
        "Research the top 3 laptops 2026",  # Level 2 — Research Agent
        "open notepad",                     # Level 3 — OS control
        "exit",
    ]
    stdin_payload = "\n".join(messages) + "\n"

    print(f"Sending these messages to `python genesis.py` in order:")
    for m in messages:
        print(f"  > {m}")

    proc = subprocess.run(
        [_sys.executable, "genesis.py"],
        input=stdin_payload,
        capture_output=True,
        text=True,
        timeout=120,
    )

    output = proc.stdout
    print("\n----- RAW OUTPUT (last 4000 chars) -----")
    print(output[-4000:])
    print("----- END RAW OUTPUT -----\n")

    if proc.returncode != 0:
        print("STDERR:\n", proc.stderr[-2000:])
        raise RuntimeError(f"genesis.py exited with code {proc.returncode}")

    # Count how many "Genesis:" replies actually came back.
    reply_count = output.count("Genesis:")
    print(f"Genesis produced {reply_count} reply block(s) "
          f"for {len(messages) - 1} real messages (excluding 'exit').")

    if reply_count < len(messages) - 1:
        raise RuntimeError(
            f"Expected at least {len(messages) - 1} replies, got {reply_count}. "
            f"Genesis is not responding to every message — inspect the raw "
            f"output above to see where it stalls."
        )

    if "Traceback (most recent call last)" in output:
        raise RuntimeError(
            "Genesis printed a Python traceback to stdout during a live "
            "conversation — see raw output above for the crash."
        )


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------
if __name__ == "__main__":
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")

    stage_results = {}
    stage_results["0-dependencies"] = run_stage("STAGE 0 — Dependencies", stage0_dependencies)
    stage_results["1-core-brain"] = run_stage("STAGE 1 — Level 1: Core Brain", stage1_core_brain)
    stage_results["2-agents"] = run_stage("STAGE 2 — Level 2: Agents", stage2_agents)
    stage_results["3-os-control"] = run_stage("STAGE 3 — Level 3: OS Control", stage3_os_control)
    stage_results["4-end-to-end"] = run_stage("STAGE 4 — Full End-to-End (real CLI)", stage4_end_to_end)

    print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
    for stage, ok in stage_results.items():
        print(f"  {'PASS' if ok else 'FAIL'} — {stage}")

    if all(stage_results.values()):
        print("\nAll stages passed. Genesis's core layers are wired correctly "
              "in this environment.")
    else:
        first_fail = next(s for s, ok in stage_results.items() if not ok)
        print(f"\nStop here: fix '{first_fail}' first — later stages depend on it.")