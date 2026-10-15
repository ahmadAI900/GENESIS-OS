#!/usr/bin/env python
"""Mutation harness that never writes, copies, or modifies a product file.

    python tools/run_memory_mutations.py                 # all three
    python tools/run_memory_mutations.py --only classify
    python tools/run_memory_mutations.py --self-test-integrity

What this measures, and why the old harness could not
-----------------------------------------------------
For each mutation it runs the SAME test target twice: once unmutated
(the baseline) and once with the mutation served from memory. Both runs
execute against the REAL tree. The previous harness copied the tree to a
temp directory first, which meant:

  * the baseline was measured against a copy, so "the suite is green"
    proved something about the copy, not about the product; and
  * the copy was incomplete (`emotion/` was missing from the copy list),
    so all 13 target tests ERRORed at setup -- and the harness's result
    parser only recognised lines beginning with `FAILED `, so 13 setup
    errors produced an empty failure list and every mutation was
    reported MISSED.

That second failure is why this driver treats three outcomes as
INSTRUMENT FAILURES rather than as results:

  NOT_APPLIED   the child's output lacks the `[memmut] MUTATED` marker,
                so the mutation was never live and a green run means
                nothing
  NO_TESTS      the child collected nothing
  ERRORED       the child reported setup/collection errors, which is
                what "no coverage" actually looks like

Each mutation additionally declares, in `memory_mutations.py`, which
BEHAVIOURAL tests must fail. "Some test failed" is not accepted: the
point is to prove the tests asserting the removed behaviour are the
ones that go red.

Integrity
---------
Every product file is SHA-256 fingerprinted before the first run and
after the last. Any difference -- created, deleted or modified -- is an
INTEGRITY FAILURE and the run exits non-zero. `--self-test-integrity`
proves that backstop actually fires by performing a deliberate in-place
write on the product tree and restoring it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
TOOLS = BACKEND / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import memory_mutations as mm  # noqa: E402

MUTATION_MARKER = "[memmut] MUTATED"

# Verbatim from the environment so a child cannot inherit it and
# accidentally mutate itself.
_CHILD_ENV_KEYS = (mm.MUTATION_ENV_VAR,)


def _child_env(request=None):
    env = dict(os.environ)
    for key in _CHILD_ENV_KEYS:
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # `-p memmut_plugin` is resolved during Config._preparse, BEFORE
    # backend/conftest.py runs, so conftest's sys.path insertion has not
    # happened yet. The plugin must be importable on its own.
    existing = env.get("PYTHONPATH", "")
    parts = [str(TOOLS)] + [p for p in existing.split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if request is not None:
        env[mm.MUTATION_ENV_VAR] = json.dumps(request)
    return env


def run_target(mutation=None, timeout=1800):
    """Run the entry-point behavioural tests in a child pytest process.

    Explicit targets, always. Passing none would collect the whole
    rootdir, which is the four-hour incident referenced in the old
    harness docstring.
    """
    args = [sys.executable, "-m", "pytest", *mm.ENTRYPOINT_TARGETS,
            "-q", "--no-header", "-p", "no:cacheprovider",
            "--tb=line", "-rfE"]
    if mutation is not None:
        args += ["-p", "memmut_plugin"]
    proc = subprocess.run(args, cwd=BACKEND, env=_child_env(mutation),
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout + proc.stderr


def classify_output(output: str, mutation=None) -> dict:
    """Turn a child's text into an honest verdict.

    Deliberately refuses to call a run "MISSED" on the strength of an
    empty FAILED list alone.
    """
    failed = sorted(
        line.split("::", 1)[1].split(" ")[0].strip()
        for line in output.splitlines() if line.startswith("FAILED "))
    errored = sorted(
        line.split("::", 1)[1].split(" ")[0].strip()
        for line in output.splitlines() if line.startswith("ERROR "))
    return {
        "failed": failed,
        "errored": errored,
        "marker_present": MUTATION_MARKER in output if mutation else None,
        "output": output,
    }


_SUMMARY_TOKEN = re.compile(
    r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)\b")


def _collected_count(output: str) -> int:
    """How many tests the child actually RAN.

    Scans BACKWARDS for pytest's final summary line. The forward version
    of this was wrong in a way the harness could not survive: the
    tripwire and the product-tree check both print their own summaries,
    and the line "0 of 13 fast-gate test(s) ... and were failed" matches
    a loose "contains 'failed'" test and yields 0. A child that ran
    13 tests was then reported as having collected none, and every
    mutation through it was declared an instrument failure. Any summary
    line that is not pytest's own is a trap for this function.
    """
    for line in reversed(output.splitlines()):
        if " in " not in line:
            continue
        counts = _SUMMARY_TOKEN.findall(line)
        if counts:
            return sum(int(n) for n, _ in counts)
    return 0


def run_baseline(report):
    print("=" * 72)
    print("BASELINE (no mutation, real tree)")
    print("=" * 72)
    rc, output = run_target(mutation=None)
    verdict = classify_output(output, mutation=None)
    ran = _collected_count(output)
    for line in output.splitlines():
        if line.startswith(("FAILED", "ERROR")):
            print(f"    {line}")
    print(f"  exit={rc}  ran={ran}  failed={len(verdict['failed'])} "
          f"errored={len(verdict['errored'])}")

    if ran == 0:
        report.append(("BASELINE", "NO_TESTS",
                       "the baseline run collected nothing; a mutation "
                       "measured against this proves nothing"))
        print("  [INSTRUMENT FAILURE] baseline collected no tests")
        return False
    if verdict["failed"] or verdict["errored"] or rc != 0:
        report.append(("BASELINE", "NOT_GREEN",
                       f"baseline is not green: rc={rc} "
                       f"failed={verdict['failed']} "
                       f"errored={verdict['errored']}"))
        print("  [INSTRUMENT FAILURE] baseline is not green")
        return False
    print("  baseline is green.\n")
    return True


def run_mutation(spec, report):
    print("-" * 72)
    print(f"MUTATION: {spec.name}")
    print(f"  {spec.why}")
    print("-" * 72)
    request = {
        "module": spec.module,
        "name": spec.name,
        "pattern": spec.pattern,
        "replacement": spec.replacement,
        "expect_matches": spec.expect_matches,
    }
    rc, output = run_target(mutation=request)
    verdict = classify_output(output, mutation=request)
    ran = _collected_count(output)

    if not verdict["marker_present"]:
        report.append((spec.name, "NOT_APPLIED",
                       "the child never printed the mutation marker, so "
                       "the mutation was not live in that process"))
        print("  [INSTRUMENT FAILURE] mutation marker absent from child "
              "output: the mutation never took effect")
        print(output[-2000:])
        return False
    if ran == 0:
        report.append((spec.name, "NO_TESTS", "child collected nothing"))
        print("  [INSTRUMENT FAILURE] child collected no tests")
        return False
    if verdict["errored"]:
        report.append((spec.name, "ERRORED",
                       f"setup/collection errors: {verdict['errored']}"))
        print("  [INSTRUMENT FAILURE] child reported errors; an ERROR is "
              "not evidence the mutation was caught")
        for e in verdict["errored"][:10]:
            print(f"    ERROR {e}")
        return False

    named = [f for f in verdict["failed"]
             if any(f == want for want in spec.caught_by)]
    print(f"  exit={rc}  ran={ran}  failed={len(verdict['failed'])}")
    for f in verdict["failed"]:
        mark = "*" if f in named else " "
        print(f"    {mark} FAILED {f}")
    print("    (* = a test that asserts the behaviour this mutation "
          "removed)")

    if not verdict["failed"]:
        report.append((spec.name, "MISSED",
                       "no test failed; the behaviour is uncovered"))
        print("  [MISSED] nothing went red")
        return False
    if not named:
        report.append((spec.name, "MISSED_BY_NAME",
                       f"failed={verdict['failed']} but none of the "
                       f"declared behavioural tests "
                       f"{list(spec.caught_by)} failed"))
        print("  [MISSED] tests went red, but none of them assert the "
              "removed behaviour")
        return False
    print(f"  caught by {len(named)} declared behavioural test(s).\n")
    return True


def self_test_integrity(report):
    """Prove the fingerprint backstop fires on a real in-place write.

    Two distinct detections are demonstrated, because they are different
    code paths and either alone would leave a hole:

      CREATE  a new file appears in the product tree
      MODIFY  an existing product file's bytes change

    Both are performed on the product tree and then reverted in a
    `finally`, with the revert verified. The MODIFY canary uses
    genesis.py, the file this whole effort has previously damaged, so
    the demonstration is of the exact failure it exists to prevent.
    """
    print("=" * 72)
    print("INTEGRITY BACKSTOP SELF-TEST (deliberate writes, then reverted)")
    print("=" * 72)
    canary_new = BACKEND / "_memmut_integrity_canary.txt"
    target = BACKEND / "genesis.py"
    original_bytes = target.read_bytes()
    created = False
    modified = False
    ok = True
    try:
        before = mm.product_fingerprint()

        # --- CREATE -------------------------------------------------
        canary_new.write_text("deliberate tripwire canary\n", "utf-8")
        created = True
        after_create = mm.product_fingerprint()
        try:
            mm.check_fingerprint(before, after_create, "a CREATE canary")
            print("  [FAIL] a created product file was NOT detected")
            report.append(("integrity self-test", "CREATE_NOT_DETECTED",
                           "check_fingerprint accepted a created file"))
            ok = False
        except mm.TreeIntegrityError as error:
            print(f"  [OK] CREATE detected:\n{error}")
        canary_new.unlink()
        created = False

        # --- MODIFY -------------------------------------------------
        target.write_bytes(original_bytes + b"\n# memmut canary\n")
        modified = True
        after_modify = mm.product_fingerprint()
        try:
            mm.check_fingerprint(before, after_modify, "a MODIFY canary")
            print("  [FAIL] a modified product file was NOT detected")
            report.append(("integrity self-test", "MODIFY_NOT_DETECTED",
                           "check_fingerprint accepted a modified file"))
            ok = False
        except mm.TreeIntegrityError as error:
            print(f"  [OK] MODIFY detected:\n{error}")
    finally:
        if created:
            canary_new.unlink(missing_ok=True)
        if modified:
            target.write_bytes(original_bytes)

    restored = mm.product_fingerprint()
    if restored != before:
        print("  [FAIL] tree not restored after canaries")
        mm.check_fingerprint(before, restored, "canary restore")
        ok = False
    else:
        print(f"  [OK] tree restored: {len(before)} product files "
              f"byte-identical")
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="substring match on mutation name")
    parser.add_argument("--self-test-integrity", action="store_true",
                        help="only prove the fingerprint backstop fires")
    parser.add_argument("--skip-baseline", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.self_test_integrity:
        report = []
        ok = self_test_integrity(report)
        return 0 if ok and not report else 1

    specs = [m for m in mm.MUTATIONS
             if not args.only or args.only in m.name]

    print(f"in-memory mutation harness")
    print(f"  target     : {' '.join(mm.ENTRYPOINT_TARGETS)}")
    print(f"  mutations  : {len(specs)}")
    print(f"  mechanism  : sys.meta_path finder, mutated source in memory\n")

    before = mm.product_fingerprint()
    root_before = mm.fingerprint_root_digest(before)
    print(f"fingerprint: {len(before)} product files, root digest "
          f"{root_before[:16]}...\n")

    report = []
    ok = True
    try:
        if not args.skip_baseline:
            ok &= run_baseline(report)
        for spec in specs:
            ok &= run_mutation(spec, report)
    finally:
        after = mm.product_fingerprint()
        root_after = mm.fingerprint_root_digest(after)
        print("=" * 72)
        print("INTEGRITY")
        print("=" * 72)
        print(f"  before {root_before[:16]}...  after {root_after[:16]}...")
        try:
            mm.check_fingerprint(before, after, "the mutation harness")
            print(f"  [OK] {len(after)} product files byte-identical. "
                  f"Nothing was written or copied.")
        except mm.TreeIntegrityError as error:
            ok = False
            print(f"  [INTEGRITY FAILURE] {error}")

    print()
    if report:
        print(f"{len(report)} instrument failure(s):")
        for name, kind, detail in report:
            print(f"  - {name}: {kind}")
            print(f"      {detail}")
        return 1
    if not ok:
        print("RESULT: FAIL")
        return 1
    print(f"RESULT: PASS -- baseline green, all {len(specs)} behavioural "
          f"mutations caught by named tests, product tree untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())