"""
Phase 0 baseline driver — non-interactive.

Reproduces a single user turn through the same GenesisOS pipeline
that genesis.py's REPL uses, but without blocking on stdin.
"""

import sys

sys.path.insert(0, r"C:\Users\Muhammad\Desktop\gemini_cli\backend")

from genesis import GenesisOS


def run_once(text):
    genesis = GenesisOS()

    # ----- Mirror genesis.run() loop body for a single turn -----
    prepared_message = genesis.conversation.prepare_message(text)

    routing_text = genesis._resolve_session_reference(prepared_message)

    if genesis.language_normalizer.needs_translation(prepared_message):
        translated = genesis.language_normalizer.to_english_command(prepared_message)
        if translated:
            print(f"[Genesis] Understood: '{translated['english']}'")
            routing_text = translated["english"]

    classification = genesis.classify(routing_text)

    if classification.get("level") != 3:
        rebound = genesis.session_context_binder.try_rebind(routing_text)
        if rebound is not None:
            print(
                "[Genesis Decision] "
                "Continuation of previous operating-system request."
            )
            classification = rebound

    print(
        f"[Genesis Router] Level {classification['level']} "
        f"\u2192 {classification['mode']}"
    )

    if classification.get("reason"):
        print(f"[Genesis Decision] {classification['reason']}")

    if classification["mode"] == "single_agent":
        a = classification.get("agent")
        if a:
            print(f"[Genesis Decision] Selected: {a}")
    elif classification["mode"] == "multi_agent":
        print("[Genesis Decision] Multi-agent workflow selected.")
        for agent in classification.get("agents", []):
            print(f"  \u2192 {agent}")
    elif classification["level"] == 3:
        print("[Genesis Decision] Operating-system capability selected.")
        if classification.get("intent"):
            print(f"[Genesis OS] Intent: {classification['intent']}")
        if classification.get("application"):
            print(f"[Genesis OS] Target: {classification['application']}")

    if classification["level"] == 3:
        response = genesis._handle_level3_request(routing_text, classification)
    elif classification["level"] == 2:
        try:
            memory_context = genesis.long_term_memory.recall_context(routing_text)
        except Exception:
            memory_context = ""
        agent_task = routing_text + (
            "\n\n[USER MEMORY \u2014 use naturally when relevant]\n"
            + memory_context
            + "\n[END USER MEMORY]"
            if memory_context
            else ""
        )
        response = genesis.run_level2(agent_task, classification)
        genesis._record_level2_entities(classification, response)
    else:
        print("[Genesis Core] Processing Level 1 conversation...")
        response = genesis._handle_unmatched_request(routing_text)
        if response is None:
            try:
                enriched = genesis.long_term_memory.enrich_prompt(prepared_message)
            except Exception:
                enriched = prepared_message
            response = genesis.brain.think(enriched)

    print(f"\nGenesis: {response}")


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or "Hello, who are you?"
    run_once(text)