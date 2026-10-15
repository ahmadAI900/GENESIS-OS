"""Cross-check the static scan against the dynamic evidence.

Two independent instruments, deliberately not sharing code:

    static_scan.py   what the SOURCE contains, before anything runs
    record_probe.py  what the PROCESS did, while it ran

Where they agree, the classification rests on two kinds of evidence.
Where they disagree, one of them is wrong or the other is blind, and the
test stays `live` until someone says which.

Disagreements reported here:

  static_signal_no_dynamic_event
      The file imports a GUI library or launches a process, and the test
      recorded nothing. Either it mocks the call, or it never reached the
      call, or the recorder is blind. Not silently passed.

  dynamic_event_no_static_signal
      The test really launched or opened something, but the file contains
      no matching import or call. Almost always the product module doing
      it on the test's behalf. Named as such rather than treated as
      suspicious.

Usage:

    python tools/cross_check.py --evidence docs/fast_gate_evidence.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# A dynamic event class -> the static signal that would normally explain it.
DYNAMIC_TO_STATIC = {
    "process": "process_call",
    "os_launch": "process_call",
    "gui": "gui_import",
    "browser": "gui_import",
    "ctypes_call": "gui_call",
    "dll_load": "gui_call",
    "network": None,  # no static proxy; network is common in pure code
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_key(nodeid: str) -> str:
    return nodeid.split("::")[0]


def static_test_keys(nodeid: str) -> list:
    """Candidate keys the static scan may have recorded for a node id.

    Delegates to the single definition in tiering_rules. An earlier
    version of this file matched on the bare method name while
    apply_tiering.py matched on a file-less `Class::method`; both were
    wrong in the same silent way, producing plausible counts and the
    wrong answer.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tiering_rules import static_keys_for
    return static_keys_for(nodeid)


def collect_static_tests(scan: dict) -> dict:
    """file -> {test label -> set of signal names}."""
    out = {}
    for name, entry in scan.get("files", {}).items():
        per_test = {}
        for block in entry.get("tests", []):
            per_test.setdefault(block["test"], set()).update(
                s["signal"] for s in block["signals"])
        out[name] = per_test
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", nargs="+", required=True,
                        help="one or more dynamic evidence files")
    parser.add_argument("--scan", default=str(BACKEND / "docs" /
                                              "fast_gate_static_scan.json"))
    parser.add_argument("--out", default=str(BACKEND / "docs" /
                                             "fast_gate_cross_check.json"))
    args = parser.parse_args(argv)

    scan = load(Path(args.scan))
    static = collect_static_tests(scan)

    dynamic: dict = {}
    for evidence_path in args.evidence:
        data = load(Path(evidence_path))
        for nodeid, record in data.items():
            if nodeid.startswith("__"):
                continue
            dynamic[nodeid] = record

    static_signal_no_event = []
    dynamic_event_no_static = []
    agree = []

    for nodeid, record in sorted(dynamic.items()):
        filename = test_key(nodeid)
        events = record.get("events", [])
        kinds = {e["kind"] for e in events}
        per_test = static.get(filename, {})
        signals = set()
        for candidate in static_test_keys(nodeid):
            signals |= per_test.get(candidate, set())

        file_entry = scan.get("files", {}).get(filename, {})
        file_signals = set(file_entry.get("signals", []))

        # Only fall back to file-level signals when the scan produced no
        # per-test scope at all for this file. Otherwise a file that
        # imports pyautogui in ONE test would mark every other test in
        # it, including ones that never call it.
        has_scoped_tests = bool(per_test)
        effective_signals = signals if signals else (
            set() if has_scoped_tests else file_signals)

        if effective_signals and not kinds:
            static_signal_no_event.append({
                "nodeid": nodeid,
                "file": filename,
                "file_signals": sorted(effective_signals),
                "scope": "test" if signals else "file",
                "recorded_kinds": [],
            })
        elif kinds:
            expected = {DYNAMIC_TO_STATIC[k] for k in kinds
                        if DYNAMIC_TO_STATIC.get(k)}
            if effective_signals & expected:
                agree.append(nodeid)
            else:
                dynamic_event_no_static.append({
                    "nodeid": nodeid,
                    "file": filename,
                    "recorded_kinds": sorted(kinds),
                    "file_signals": sorted(effective_signals),
                    "note": "product module performed the action on the "
                            "test's behalf",
                })

    # A file with a static signal whose tests recorded nothing is listed
    # even when those tests were not in the evidence file at all.
    covered = {test_key(n) for n in dynamic}
    files_with_signal_no_tests = sorted(
        name for name, entry in scan.get("files", {}).items()
        if entry.get("signals") and name not in covered
    )

    payload = {
        "evidence_files": args.evidence,
        "dynamic_tests": len(dynamic),
        "counts": {
            "agree": len(agree),
            "static_signal_no_dynamic_event": len(static_signal_no_event),
            "dynamic_event_no_static_signal": len(dynamic_event_no_static),
        },
        "static_signal_no_dynamic_event": static_signal_no_event,
        "dynamic_event_no_static_signal": dynamic_event_no_static,
        "files_with_static_signal_but_no_evidence": files_with_signal_no_tests,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True),
                   encoding="utf-8")

    print(f"dynamic tests examined : {len(dynamic)}")
    print(f"agree                  : {len(agree)}")
    print(f"static signal, no event: {len(static_signal_no_event)}")
    print(f"event, no static signal: {len(dynamic_event_no_static)}")
    print(f"files with a signal but no evidence at all: "
          f"{len(files_with_signal_no_tests)}")
    for name in files_with_signal_no_tests:
        print(f"    {name}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())