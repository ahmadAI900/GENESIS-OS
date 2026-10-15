"""Fail when a required test set did not actually run.

A test that skips is indistinguishable from a test that passes if you
only look at the exit code. Continuation A3 reported "transparency 8/8"
and the truth was 8 skips: the guard that decides whether the recorder is
transparent computed its flag from a module-level `pytest_configure`,
which pytest never calls on a test module, so every test skipped and the
count still read 8.

That is the failure this script exists to make impossible to repeat. A
required set is required to RUN AND PASS in a stated mode. Skips,
deselections and xfails are failures here, reported by name.

    python tools/require_passed.py --list
    python tools/require_passed.py                     # every set
    python tools/require_passed.py recorder_transparency tripwire_mutation
    python tools/require_passed.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


@dataclass
class RequiredSet:
    name: str
    targets: list
    why: str
    # Marker expressions that must be active. An empty list means the set
    # must run in the DEFAULT mode with no -m filter at all.
    marker_args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)


# Each entry states what a false pass would mean, so the list can be
# argued with rather than merely trusted.
REQUIRED_SETS = {
    "recorder_transparency": RequiredSet(
        name="recorder_transparency",
        targets=["tools/test_record_probe_transparency.py"],
        marker_args=["--record", "-p", "record_probe"],
        why="the recorder must not change what the code under test does. "
            "Skipping these proves nothing: they are 8 skips that read as "
            "8/8.",
    ),
    "recorder_canaries": RequiredSet(
        name="recorder_canaries",
        targets=["tools/test_record_probe_canaries.py"],
        marker_args=["--record", "-p", "record_probe"],
        why="the recorder's coverage matrix. Every canary must have run, "
            "or the recorder's blind spots are unmeasured.",
    ),
    "tripwire_mutation": RequiredSet(
        name="tripwire_mutation",
        targets=["tools/test_tripwire_mutation.py"],
        why="proves the tripwire still fails an unmarked offender. A gate "
            "that stops catching things looks exactly like a gate that "
            "has nothing to report.",
    ),
    "class_census": RequiredSet(
        name="class_census",
        targets=["test_structural_census.py"],
        why="the structural census is the census; a silent skip means the "
            "suite's shape is unverified.",
    ),
    "approval_channel": RequiredSet(
        name="approval_channel",
        targets=["test_approval_channel.py"],
        why="approval is the safety boundary. A skipped approval test is "
            "an unverified approval path.",
    ),
    "workspace_boundary": RequiredSet(
        name="workspace_boundary",
        targets=["test_workspace_boundary.py"],
        why="the boundary that stops tests writing into the product tree.",
    ),
}

_SUMMARY = re.compile(
    r"(?P<passed>\d+) passed|(?P<failed>\d+) failed|"
    r"(?P<skipped>\d+) skipped|(?P<xfailed>\d+) xfailed|"
    r"(?P<xpassed>\d+) xpassed|(?P<errors>\d+) error")
_NODE_STATUS = re.compile(r"^(?P<status>PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)"
                          r"\s+(?P<nodeid>\S+)")


def _parse_summary(text: str) -> dict:
    out = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0,
           "xpassed": 0, "errors": 0}
    # The summary line is the last one carrying counts. It must be found
    # by "skipped" as well as "passed"/"failed": the A3 shape is a line
    # reading "8 skipped in 0.20s", and a scan that only looks for
    # "passed" walks straight past it and reports zeros -- which is
    # indistinguishable from "nothing ran", i.e. another false pass.
    for line in reversed(text.splitlines()):
        if re.search(r"\d+ (passed|failed|skipped|xfailed|xpassed|error)", line) \
                or "no tests ran" in line:
            for match in _SUMMARY.finditer(line):
                out[match.lastgroup] = int(match.group(match.lastgroup))
            break
    return out


def _parse_node_statuses(text: str) -> dict:
    statuses = {}
    for line in text.splitlines():
        match = _NODE_STATUS.match(line.strip())
        if match:
            statuses[match.group("nodeid")] = match.group("status")
    return statuses


def run_set(required: RequiredSet, timeout: int = 1800) -> dict:
    cmd = [sys.executable, "-m", "pytest", *required.targets,
           "-p", "no:cacheprovider", "-rA", "--no-header", "-q"]
    cmd += required.marker_args
    # pytest imports plugins by MODULE NAME, so `-p record_probe` needs
    # tools/ on the path. Getting this wrong is silent: the run reports
    # "no tests ran at all" and every test in the set skips, which is
    # exactly the shape of the A3 "transparency 8/8" lie.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BACKEND / "tools"), env.get("PYTHONPATH", "")]).strip(os.pathsep)
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True,
                          timeout=timeout, env=env)
    text = proc.stdout + proc.stderr
    summary = _parse_summary(text)
    statuses = _parse_node_statuses(text)
    return {
        "name": required.name,
        "why": required.why,
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "summary": summary,
        "non_passing": sorted(
            f"{nodeid} -> {status}"
            for nodeid, status in statuses.items()
            if status != "PASSED"),
        "ran_anything": summary["passed"] + summary["failed"]
        + summary["skipped"] + summary["xfailed"] + summary["xpassed"]
        > 0,
        "output_tail": text[-3000:],
    }


def evaluate(names=None) -> dict:
    selected = [REQUIRED_SETS[n] for n in (names or REQUIRED_SETS)]
    results = []
    for required in selected:
        if required is None:
            results.append({"name": "?", "ok": False,
                            "error": "unknown required set"})
            continue
        try:
            result = run_set(required)
        except subprocess.TimeoutExpired:
            results.append({"name": required.name, "ok": False,
                            "error": "timed out"})
            continue
        summary = result["summary"]
        problems = []
        if not result["ran_anything"]:
            problems.append("no tests ran at all")
        if summary["skipped"]:
            problems.append(f"{summary['skipped']} skipped")
        if summary["xfailed"]:
            problems.append(f"{summary['xfailed']} xfailed")
        if summary["xpassed"]:
            problems.append(f"{summary['xpassed']} xpassed unexpectedly")
        if summary["failed"]:
            problems.append(f"{summary['failed']} failed")
        if summary["errors"]:
            problems.append(f"{summary['errors']} errored")
        if result["returncode"] != 0 and not problems:
            problems.append(f"exit code {result['returncode']}")
        result["ok"] = not problems
        result["problems"] = problems
        results.append(result)
    return {"results": results,
            "ok": all(r.get("ok") for r in results)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*",
                        help=f"required sets to check; default all. "
                             f"known: {', '.join(sorted(REQUIRED_SETS))}")
    parser.add_argument("--list", action="store_true",
                        help="list the required sets and exit")
    parser.add_argument("--json", default=None,
                        help="write the full report to this path")
    args = parser.parse_args(argv)

    if args.list:
        for name in sorted(REQUIRED_SETS):
            entry = REQUIRED_SETS[name]
            print(f"{name}\n    targets : {' '.join(entry.targets)}"
                  f"{' ' + ' '.join(entry.marker_args) if entry.marker_args else ''}")
            print(f"    why     : {entry.why}")
        return 0

    report = evaluate(args.names or None)
    print()
    for result in report["results"]:
        status = "OK   " if result.get("ok") else "FAIL "
        print(f"{status} {result['name']}")
        if result.get("problems"):
            print(f"       {', '.join(result['problems'])}")
        for item in result.get("non_passing", [])[:10]:
            print(f"       {item}")
        if result.get("error"):
            print(f"       {result['error']}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, sort_keys=True),
                                   encoding="utf-8")
        print(f"\n-> {args.json}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())