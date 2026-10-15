"""Reproduce the actual runtime failure described in genesis_fix_prompt_v2.md.

User input: 'open notepad and write Hello from Genesis'

This walks the SAME path run() takes for an L3 request:
    self.classify(text)
        -> _handle_level3_request(text, classification)
            -> _try_multi_step_workflow(text)
                -> plan_level3_objective(text)
                    -> ObjectiveUnderstanding.understand
                    -> WorkflowDecomposer.decompose
                -> check decomposition.executable
                -> "Genesis understood this as a multi-step objective,
                    but could not safely execute every step: ..."

Prints:
    - the classification
    - the understanding steps
    - the decomposition result
    - the executable_intent per step
    - the final response
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TEXT = "open notepad and write Hello from Genesis"


def main() -> int:
    from genesis import GenesisOS

    g = GenesisOS()

    classification = g.classify(TEXT)
    print("=== CLASSIFICATION ===")
    print(classification)

    understanding = g.objective_understanding.understand(TEXT)
    print("\n=== UNDERSTANDING ===")
    print(f"fully_level3={understanding.fully_level3}")
    print(f"executable={understanding.executable}")
    print(f"requires_clarification={understanding.requires_clarification}")
    if understanding.clarification_reason:
        print(f"clarification_reason={understanding.clarification_reason}")
    for s in understanding.steps:
        print(
            f"  - seq={s.sequence} text={s.text!r} "
            f"level={s.level} mode={s.mode} "
            f"operation={s.operation} target={s.target} "
            f"application={s.application} "
            f"is_level3={s.is_level3} "
            f"executable_intent={s.executable_intent} "
            f"requires_clarification={s.requires_clarification} "
            f"reason={s.clarification_reason!r}"
        )
        print(f"    decision={s.decision}")

    decomposition = g.workflow_decomposer.decompose(understanding)
    print("\n=== DECOMPOSITION ===")
    print(f"decomposed={decomposition.decomposed}")
    print(f"executable={decomposition.executable}")
    print(f"step_count={decomposition.step_count}")
    print(f"rejected_steps={list(decomposition.rejected_steps)}")
    print(f"clarification_reason={decomposition.clarification_reason!r}")

    print("\n=== RESPONSE FROM _handle_level3_request ===")
    response = g._handle_level3_request(TEXT, classification)
    print(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())