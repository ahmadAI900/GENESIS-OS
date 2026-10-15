#!/usr/bin/env python
"""Run one test N times under CPU load and collect every failure signature.

    python tools/verify/verify_test_stability.py \
        --nodeid test_x.py::test_y --runs 20 --load 3

Why a signature and not just a pass/fail count
---------------------------------------------
A flaky test that fails 1 run in 20 is the hardest kind of evidence to
act on, because the report "it failed once" tells nobody why. This tool
reduces each failure to a stable signature -- the exception type, the
assertion line and the normalised message -- so a 20-run sample says
WHETHER it is the same bug every time, which decides whether the fix is
"make the browser probe deterministic" or "stop blaming the browser".

Load is produced by real CPU-burning sibling processes, because the
failures under investigation (browser driver probe timeouts) only
appear when the machine is contended. A clean-machine run would report
green and prove nothing.

Each run is a FRESH PROCESS. Module-level probe caches and one-shot
imports mean a same-process loop measures the first run over and over.
"""

from __future__ import annotations

import argparse
import collections
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent


def _burn(seconds: float):
    end = time.time() + seconds
    x = 0
    while time.time() < end:
        for _ in range(20000):
            x += 1
    return x


def _child_env():
    env = dict(os.environ)
    env.pop("GENESIS_MUTATION", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


_ANON = re.compile(r"0x[0-9a-fA-F]+")


def signature(output: str) -> str:
    """Reduce a pytest report to a comparable one-line signature."""
    lines = [ln.rstrip() for ln in output.splitlines()]
    interesting = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("E   ", "E\t")):
            interesting.append(stripped[4:].strip())
        elif "Error" in stripped and stripped.endswith((")", "Error")):
            interesting.append(stripped)
        elif stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
            interesting.append(stripped)
    if not interesting:
        interesting = [ln.strip() for ln in lines if ln.strip()][-3:]
    text = " | ".join(interesting[:4])
    text = _ANON.sub("0xADDR", text)
    return re.sub(r"\s+", " ", text)[:400]


def run_once(nodeid: str, timeout=900):
    started = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", nodeid, "-q", "--no-header",
         "-p", "no:cacheprovider", "--tb=line", "-rf"],
        cwd=BACKEND, env=_child_env(), capture_output=True, text=True,
        timeout=timeout)
    output = proc.stdout + proc.stderr
    return {
        "rc": proc.returncode,
        "passed": proc.returncode == 0,
        "seconds": round(time.time() - started, 2),
        "signature": None if proc.returncode == 0 else signature(output),
        "output_tail": None if proc.returncode == 0 else output[-3000:],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodeid", required=True)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--load", type=int, default=3)
    parser.add_argument("--label", default="")
    parser.add_argument("--allow-failures", action="store_true",
                        help="report the distribution without failing the "
                             "command when some runs fail")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    print(f"stability: {args.nodeid}")
    if args.label:
        print(f"  label    : {args.label}")
    print(f"  runs     : {args.runs}, fresh process each")
    print(f"  load     : {args.load} burner process(es), "
          f"{os.cpu_count()} logical CPUs")
    print()

    burn_seconds = args.runs * 120 + 600
    load = [multiprocessing.Process(target=_burn, args=(burn_seconds,),
                                    daemon=True) for _ in range(args.load)]
    for p in load:
        p.start()
    time.sleep(1.0)

    results = []
    try:
        for index in range(1, args.runs + 1):
            try:
                result = run_once(args.nodeid)
            except subprocess.TimeoutExpired:
                result = {"rc": -1, "passed": False, "seconds": None,
                          "signature": "TIMEOUT: the run exceeded its limit",
                          "output_tail": ""}
            results.append(result)
            state = "PASS" if result["passed"] else "FAIL"
            print(f"  run {index:2d}/{args.runs}: {state} "
                  f"({result['seconds']}s)")
            if not result["passed"]:
                print(f"      {result['signature'][:220]}")
            sys.stdout.flush()
    finally:
        for p in load:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()

    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]
    durations = [r["seconds"] for r in results if r["seconds"]]

    print()
    print("DISTRIBUTION")
    print("-" * 70)
    print(f"  passed : {len(passed)}/{len(results)}")
    print(f"  failed : {len(failed)}/{len(results)}")
    if durations:
        print(f"  duration: min {min(durations)}s  max {max(durations)}s  "
              f"mean {sum(durations)/len(durations):.1f}s")
    if failed:
        counts = collections.Counter(r["signature"] for r in failed)
        print()
        print("  failure signatures:")
        for sig, n in counts.most_common():
            print(f"    {n}x {sig}")
    print()

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2),
                                      encoding="utf-8")
        print(f"raw records: {args.json_out}")

    if failed and not args.allow_failures:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS" if not failed else "RESULT: FAIL (allowed)")
    return 0 if not failed or args.allow_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())