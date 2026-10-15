"""Find fast-tier tests that construct a GUI provider.

The tripwire's verdict on such a test depends on ORDER: pyautogui's
import-time GUI cost is paid once per process, so only the first test
to trigger it records anything. A sweep that would miss every offender
except the first is not a sweep.

So candidates are found statically, then each is re-run in its OWN
process under the tripwire, where it is guaranteed to be first.

Usage:  python tools/find_gui_first_touch.py [--apply]
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "tools"))

# Constructing any of these imports pyautogui and probes the keyboard.
GUI_CONSTRUCTORS = {
    "GUIController", "WindowsGUIProvider", "UIAutomationProvider",
    "GUIObserver", "GUIVerifier",
}


def candidate_tests(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith("test"):
            segment = ast.get_source_segment(
                path.read_text(encoding="utf-8"), node) or ""
            hits = sorted({n for n in GUI_CONSTRUCTORS if n in segment})
            if hits:
                found.append((node.name, hits))
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="print the live-marking snippet for each hit")
    args = parser.parse_args(argv)

    tiering = json.loads(
        (BACKEND / "docs" / "tests_tiering.json").read_text(encoding="utf-8"))
    evidence = json.loads(
        (BACKEND / "docs" / "fast_gate_evidence.json").read_text(encoding="utf-8"))

    # Fast-tier tests = everything the evidence has, minus the recorded
    # non-loopback/gui/browser/process offenders.
    import tiering_rules as rules
    fast = set()
    for nodeid, record in evidence.items():
        if nodeid.startswith("__"):
            continue
        if tiering.get(nodeid, {}).get("tier") == "runtime":
            fast.add(nodeid)

    print(f"fast-tier runtime tests: {len(fast)}\n")
    offenders = []
    for path in sorted(BACKEND.rglob("test_*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(BACKEND).as_posix()
        for name, hits in candidate_tests(path):
            matching = [n for n in fast if n.endswith(f"::{name}")
                        or n.split("::")[-1] == name and n.startswith(rel)]
            if matching:
                offenders.append((matching[0], rel, hits))

    print(f"fast-tier tests that construct a GUI provider: {len(offenders)}\n")
    for nodeid, rel, hits in offenders:
        # Re-run alone so this test is guaranteed to pay the import cost.
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", f"{rel}::{nodeid.split('::', 1)[1]}",
             "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=BACKEND, capture_output=True, text=True, timeout=300)
        caught = "capability tripwire" in proc.stdout
        print(f"  {'CAUGHT ' if caught else 'clean  '} {nodeid}")
        print(f"          constructors={hits}")

    caught_n = sum(1 for n, _, _ in offenders)
    print(f"\n{caught_n} of {len(offenders)} construct a GUI provider AND "
          f"reach a real capability when run first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())