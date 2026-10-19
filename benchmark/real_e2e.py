"""
Genesis OS — Real End-to-End Boot Test
======================================

Boots the real GenesisOS on the host and feeds representative
L1 / L2 / L3 requests through the live decision pipeline
(``GenesisOS.classify``), printing one verdict-carrying line per
check and a derived overall result.

Honesty notes:
  * Nothing in this harness is mocked or simulated. Brain, Memory,
    Conversation, the ten specialized agents,
    WorkflowDecisionEngine and OSManager are the real production
    objects; booting constructs them for real.
  * The run is READ-ONLY: only ``classify`` is called, never
    execute. The real OSManager is instantiated but never asked to
    touch the host, so no host state changes.
  * Classification may consult the configured LLM intent resolver,
    so a run can take as long as that resolver's timeouts allow.
  * The verdict is DERIVED from the run: every check prints PASS or
    FAIL, a RESULT: PASS banner appears only when every check
    actually passed, and any failure exits non-zero. The harness
    cannot print PASS for a failed run.

Run:

    & ".venv\\Scripts\\python.exe" -m backend.benchmark.real_e2e

Exit codes: 0 = every check passed, 1 = at least one check failed
(or boot crashed).
"""
from __future__ import annotations

import os
import sys

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Add backend to path so `from genesis_os import ...` works
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# =========================================================
# REAL GENESIS BOOT
# =========================================================

# The benchmark folder is run with PYTHONPATH=backend so the
# absolute ``import backend.genesis`` would fail there.
# We import genesis directly and tolerate either layout.
try:
    from backend import genesis as genesis_module  # type: ignore  # noqa: E402
except ImportError:  # pragma: no cover
    import genesis as genesis_module  # type: ignore  # noqa: E402


# (tag, text, acceptable classification levels for this tag)
#
# The tag is the expectation, not decoration: L2 samples must come
# back as Level 2 (per GENESIS_MASTER_COMPLETION, "Research X" is an
# L2 Research Agent task), L3 samples as Level 3, L1 samples as
# Level 1, and the mixed L2+L3 sample may land on either real level
# -- never on Level 1 conversation.
SAMPLES = [
    # Level 1
    ("L1", "What is photosynthesis?", (1,)),
    ("L1", "Tell me a joke.", (1,)),
    # Level 2
    ("L2", "Research the latest AI safety papers.", (2,)),
    ("L2", "Write a Python function to merge two sorted lists.", (2,)),
    ("L2", "Study biology with me.", (2,)),
    ("L2", "Analyze this spreadsheet for outliers.", (2,)),
    # Level 3
    ("L3", "open chrome", (3,)),
    ("L3", "open my downloads", (3,)),
    ("L3", "search the web for python tutorials", (3,)),
    ("L3", "open my downloads and find the latest PDF", (3,)),
    # Mixed L2 + L3
    ("L2+L3", "Research laptops and open Chrome", (2, 3)),
    # Compound L3
    ("L3-compound", "open chrome, go to github, and search for langchain", (3,)),
]


def _marker(ok: bool) -> str:
    return "[PASS]" if ok else "[FAIL]"


def _verdict(checks_total: int, checks_failed: int) -> int:
    print()
    print("=" * 72)
    if checks_failed:
        print(
            f"RESULT: FAIL ({checks_failed} of {checks_total} checks failed)"
        )
        rc = 1
    else:
        print(f"RESULT: PASS ({checks_total} checks)")
        rc = 0
    print("=" * 72)
    return rc


def main() -> int:
    print("=" * 72)
    print("          GENESIS OS — REAL END-TO-END BOOT TEST")
    print("=" * 72)
    print()

    # Instantiate the real GenesisOS. This wires up
    # Level 1 (Brain, Memory, Conversation), Level 2
    # (10 specialized agents, AgentRegistry, Orchestrator,
    # MultiAgentExecutor), and Level 3 (OSManager,
    # ActionExecutor, UniversalDesktopWorkflowEngine, ...
    # etc.).
    try:
        g = genesis_module.GenesisOS()
    except Exception as exc:
        print(
            f"  {_marker(False)} GenesisOS boot raised "
            f"{type(exc).__name__}: {exc}"
        )
        return _verdict(1, 1)

    checks_total = 0
    checks_failed = 0

    def tally(ok: bool) -> None:
        nonlocal checks_total, checks_failed
        checks_total += 1
        if not ok:
            checks_failed += 1

    def check(label: str, ok: bool, detail: str = "") -> None:
        tally(ok)
        suffix = f" — {detail}" if detail else ""
        print(f"  {_marker(ok)} {label}{suffix}")

    # Skip startup banner (no TTY); just confirm readiness.
    print("GenesisOS instantiated.")
    print(f"  Level 1 brain:         {g.brain}")
    print(f"  Level 1 memory:        {g.memory}")
    print(f"  Level 1 conversation:  {g.conversation}")
    print(f"  Level 2 registry:      {g.registry.count()} agents")
    print(f"  Level 2 agents:        {[a.name for a in g.registry.get_all_agents()]}")
    print(f"  Level 3 OS:            {g.os_manager.status()}")
    print()

    # =========================================================
    # BOOT CHECKS
    # =========================================================
    print("Boot checks:")
    print("-" * 72)
    check(
        "Level 1 components attached (brain/memory/conversation)",
        all(x is not None for x in (g.brain, g.memory, g.conversation)),
    )
    agent_count = g.registry.count()
    check("Level 2 registry populated", agent_count > 0, f"{agent_count} agents")
    status = g.os_manager.status()
    check(
        "Level 3 OS status reports level 3",
        isinstance(status, dict) and status.get("level") == 3,
        f"status level={status.get('level') if isinstance(status, dict) else status!r}",
    )
    print()

    # =========================================================
    # REPRESENTATIVE L1 / L2 / L3 REQUESTS (read-only classify)
    # =========================================================
    #
    # Each request is fed through the real decision engine.
    # We only invoke `classify` (NOT execute) so the test
    # is read-only and does not touch the host filesystem
    # or any installed application.

    print("Real classification for representative tasks:")
    print("-" * 72)
    observed_levels = set()
    for tag, text, expected in SAMPLES:
        try:
            classification = g.classify(text)
            level = classification.get("level")
            mode = classification.get("mode")
            agent = classification.get("agent")
            agents = classification.get("agents")
            intent = classification.get("intent")
            if isinstance(level, int):
                observed_levels.add(level)
            ok = level in expected and isinstance(mode, str) and bool(mode)
            detail = f"L{level}/{mode} agent={agent} agents={agents} intent={intent}"
            if not ok:
                detail += (
                    " — expected L"
                    + "/".join(str(n) for n in expected)
                )
        except Exception as exc:
            ok = False
            detail = f"classify raised {type(exc).__name__}: {exc}"
        print(
            f"  [{tag:11s}] {text!r:60s} -> {detail} {_marker(ok)}"
        )
        tally(ok)

    reachability = {1, 2, 3}.issubset(observed_levels)
    check(
        "Every Level 1, Level 2 and Level 3 path observed",
        reachability,
        f"observed levels {sorted(observed_levels)}",
    )

    return _verdict(checks_total, checks_failed)


if __name__ == "__main__":
    try:
        _rc = main()
    except BaseException as _exc:  # noqa: BLE001
        print(
            f"FATAL: {type(_exc).__name__}: {_exc}",
            file=sys.stderr,
        )
        _rc = 1
    sys.stdout.flush()
    sys.stderr.flush()
    # GenesisOS starts non-daemon watcher/executor threads and the
    # runtime exposes no shutdown API, so a plain sys.exit would
    # hang forever and no verdict code could ever be observed. The
    # verdict has already been printed and flushed; hard-exit so the
    # process exit status IS the verdict.
    os._exit(_rc)
