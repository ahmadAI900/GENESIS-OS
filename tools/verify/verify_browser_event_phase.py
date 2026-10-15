#!/usr/bin/env python
"""Phase-resolve the browser/driver event for test_pure_level3_*_agents.

    python tools/verify/verify_browser_event_phase.py

The tiering evidence for
`test_level3_11_unified_intelligence.py::test_pure_level3_objectives_do_not_invoke_agents`
records `playwright.sync_api.sync_playwright x1` and "duration over
10.0s (22.39s)", which is why the test is `live`. But the recorder
accumulates setup, call and teardown into one record per nodeid, so on
its own it cannot say WHICH phase reached the browser.

The brief asks exactly that, and the answer decides whether the
deterministic-probe fixture is attached in the right place. So this
measures the two phases separately in one fresh process:

    SETUP   constructing GenesisOS(), which is what the module-scoped
            `genesis` fixture does before any test body runs
    CALL    the test body's own dispatch, run against that same runtime

If SETUP already reaches playwright, then the probe happens during
fixture setup, and a fixture attached to the test is the correct place
to pin it. If only CALL reaches it, the construction cost is unrelated
to the browser and pinning the probe would not help.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent
for extra in (BACKEND, BACKEND / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def summarise(events, label):
    rows = [(e.get("kind"), e.get("api"), e.get("count", 1))
            for e in events]
    print(f"  {label}: {len(rows)} distinct event(s)")
    for kind, api, count in rows:
        flag = "  <-- BROWSER/DRIVER" if kind in ("browser", "gui") else ""
        print(f"      {kind:<10} {api:<45} x{count}{flag}")
    return any(kind in ("browser", "gui") for kind, _, _ in rows)


def main() -> int:
    import record_probe

    record_probe.ensure_installed()

    # ---- SETUP: what the module-scoped `genesis` fixture does ---------
    setup_frame = record_probe.new_capture("SETUP")
    record_probe._CAPTURE_STACK.append(setup_frame)
    from genesis import GenesisOS
    runtime = GenesisOS()
    record_probe._CAPTURE_STACK.remove(setup_frame)
    setup_browser = summarise(setup_frame["events"],
                              "SETUP  GenesisOS() construction")

    # ---- CALL: the test body's own dispatch ---------------------------
    call_frame = record_probe.new_capture("CALL")
    record_probe._CAPTURE_STACK.append(call_frame)
    try:
        runtime.run_level3(
            "Open Chrome and search YouTube for Python tutorials.",
            runtime.classify(
                "Open Chrome and search YouTube for Python tutorials."),
        )
    except Exception as error:  # the dispatch is allowed to fail
        print(f"  (dispatch raised {type(error).__name__}; the recorded "
              f"events are what matter)")
    finally:
        record_probe._CAPTURE_STACK.remove(call_frame)
    call_browser = summarise(call_frame["events"], "CALL   run_level3 dispatch")

    print()
    print(f"  providers registered : {runtime.browser_provider_names}")
    print(f"  browser_degraded     : {runtime.browser_degraded}")
    print(f"  degraded_reason      : {runtime.browser_degraded_reason}")
    print()
    if setup_browser:
        print("  VERDICT: a browser/driver event occurs during SETUP, i.e. "
              "inside the\n           module-scoped fixture, before any test "
              "body runs. A fixture\n           attached to the test pins the "
              "right thing.")
        return 0
    print("  VERDICT: no browser/driver event during SETUP. The browser "
          "reach is in the\n           test body, so pinning the probe cache "
          "would not address it.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
