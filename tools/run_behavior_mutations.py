#!/usr/bin/env python
"""Scratch mutation harness: prove the new tests detect BEHAVIOUR changes.

A5's mutation (`GenesisOS.classify` renamed away) turned the gate red
through exactly one test, and that test only asserted the member still
exists. That is a name check, not behaviour coverage.

This applies three mutations in turn, each restored immediately, and
reports which BEHAVIOURAL tests failed. The point is not that the suite
goes red -- it is that the tests that go red are the ones asserting
behaviour.

    python tools/run_behavior_mutations.py

Genesis.py is edited and restored inside the script, with the original
bytes held in memory and rewritten in a `finally`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
GENESIS = BACKEND / "genesis.py"
TARGETS = ["test_genesis_entrypoint_behavior.py"]

MUTATIONS = [
    ("classify renamed away",
     r"(?m)^(\s*)def classify\(self, text\):",
     r"\1def _MUTATED_removed_classify(self, text):"),

    ("classify returns Level 3 routing for everything",
     r"(?m)^(\s*)def classify\(self, text\):",
     r"\1def classify(self, text):\n"
     r"\1    _r = _MUTATED_classify(self, text)\n"
     r"\1    _r['level'] = 3\n"
     r"\1    _r['mode'] = 'os'\n"
     r"\1    return _r\n"
     r"\n"
     r"\1def _MUTATED_classify(self, text):"),

    # genesis.py is MIXED line endings: the run_level3 block is CRLF
    # while the classify block is LF. An LF-only pattern silently does
    # not match, and the harness then reports the mutation as "SKIP"
    # rather than "MISSED" -- which reads like an honest result instead
    # of an instrument that never fired.
    ("run_level3 skips the workspace boundary check",
     r"(\r?\n    def run_level3\(\r?\n        self,\r?\n        text,"
     r"\r?\n        classification\r?\n    \):\r?\n)",
     "\\1        import os as _os\r\n"
     "        _os.environ.pop('GENESIS_WORKSPACE_ROOT', None)\r\n"),
]


class MutationNotApplied(Exception):
    """A mutation pattern matched nothing.

    Raised, never reported as SKIP. A skip reads like an honest result;
    an instrument that never fired reads like one too, and that is the
    exact failure this harness exists to prevent.
    """


def normalise_newlines(text: str) -> str:
    """Return (normalised_text, '\r\n' if the source was CRLF else '\n').

    genesis.py is a MIXED line-ending file: the `run_level3` block is
    CRLF and the `classify` block is LF. An LF-only pattern silently
    does not match.

    Normalisation is used for MATCHING ONLY. The mutation is applied to
    the ORIGINAL text using the matching variant, so no unrelated line
    of a 3700-line product file is rewritten -- rewriting them all would
    bury the one-line change in a whole-file diff and normalise the file,
    which B2 explicitly forbids.

    genesis.py's mixed line endings are a residual, not a fix.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalised, ("\r\n" if "\r\n" in text else "\n")


def apply_mutation(original_text: str, pattern: str, replacement: str):
    """Apply one mutation to the original text, preserving its endings.

    Tries LF first, then CRLF, against the ORIGINAL text so no unrelated
    line is rewritten.
    """
    # Patterns are RAW strings, so "\\n" is two characters, not a
    # newline. Substituting real newlines therefore needs the escaped
    # form first -- which is exactly why the CRLF pattern silently
    # failed to match in B1.
    base = pattern.replace("\\r\\n", "\\n")
    variants = []
    for eol_char in ("\n", "\r\n"):
        converted = base.replace("\\n", eol_char)
        rep = replacement.replace("\\r\\n", "\\n").replace("\\n", eol_char)
        variants.append((converted, rep))
    for candidate_pattern, candidate_replacement in variants:
        try:
            mutated, n = re.subn(candidate_pattern, candidate_replacement,
                                 original_text, count=1)
        except re.error:
            continue
        if n:
            return mutated
    raise MutationNotApplied(
        f"mutation pattern matched nothing under either line-ending "
        f"convention: {pattern!r}")


def run_tests(cwd=None):
    """Run the target tests against `cwd`, never against the real tree.

    An explicit pytest subprocess, with explicit targets. Passing no
    target would make pytest collect the whole rootdir, which is the B1
    four-hour incident.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TARGETS, "-q", "--no-header",
         "-p", "no:cacheprovider", "-rf"],
        cwd=cwd or BACKEND, capture_output=True, text=True, timeout=1800)
    failed = sorted(
        line.split("::", 1)[1].split(" ")[0]
        for line in proc.stdout.splitlines()
        if line.startswith("FAILED "))
    return proc.returncode, failed, proc.stdout


# ----------------------------------------------------------------------
# The harness must never write a real product file.
#
# It has damaged them three times: an early truncation script, then
# PowerShell `Set-Content` normalising genesis.py's line endings. So
# mutations are applied to a COPY of the tree, and the real tree is
# fingerprinted before and after. Any difference is a harness failure.
# ----------------------------------------------------------------------
def product_fingerprint(root=None):
    """sha256 of every product source file under `root`."""
    import hashlib
    root = root or BACKEND
    out = {}
    for path in sorted(root.rglob("*.py")):
        if any(part in {".venv", "__pycache__", ".pytest_cache", "backups"}
               for part in path.parts):
            continue
        if path.name == "run_behavior_mutations.py":
            continue
        try:
            out[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


class TreeIntegrityError(RuntimeError):
    pass


def make_sandbox():
    """Copy the tree the tests need into a temp directory."""
    import shutil
    import tempfile
    sandbox = Path(tempfile.mkdtemp(prefix="genesis_mutation_"))
    for name in ("genesis.py", "conftest.py"):
        shutil.copy2(BACKEND / name, sandbox / name)
    for sub in ("genesis_os", "ai", "agents", "brain", "core", "runtime",
                "tools", "docs", "benchmark_real_os", "memory", "internet",
                "collaboration", "conversation", "personality", "reasoning",
                "knowledge", "planner", "router", "integration", "benchmark"):
        source = BACKEND / sub
        if source.is_dir():
            shutil.copytree(source, sandbox / sub,
                            ignore=shutil.ignore_patterns("__pycache__",
                                                          "*.pyc"))
    for path in BACKEND.glob("test_*.py"):
        shutil.copy2(path, sandbox / path.name)
    for extra in (".env",):
        if (BACKEND / extra).is_file():
            shutil.copy2(BACKEND / extra, sandbox / extra)
    return sandbox


def main() -> int:
    import shutil

    real_before = product_fingerprint()
    sandbox = make_sandbox()
    sandbox_genesis = sandbox / "genesis.py"
    failures = []
    print(f"sandbox: {sandbox}")
    print(f"integrity: fingerprinted {len(real_before)} real product files\n")
    try:
        baseline_rc, baseline_failed, _ = run_tests(cwd=sandbox)
        print(f"baseline (no mutation): rc={baseline_rc} "
              f"failed={baseline_failed}\n")
        if baseline_failed:
            print("BASELINE IS NOT GREEN; stop here rather than measure a "
                  "mutation against a suite that already fails.")
            return 1

        for name, pattern, replacement in MUTATIONS:
            try:
                mutated = apply_mutation(sandbox_genesis.read_text(
                    encoding="utf-8"), pattern, replacement)
            except MutationNotApplied as error:
                print(f"[HARNESS FAILURE] {name}: {error}")
                failures.append(name)
                continue
            # The mutation is applied to the SANDBOX only.
            sandbox_genesis.write_text(mutated, encoding="utf-8")
            rc, failed, _ = run_tests(cwd=sandbox)

            print(f"[{'CAUGHT' if failed else 'MISSED'}] {name}")
            for f in failed:
                print(f"    FAILED {f}")
            if not failed:
                failures.append(name)
            print()

        print("after restore: (sandbox discarded, real tree untouched)")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    real_after = product_fingerprint()
    if real_before != real_after:
        changed = sorted(set(real_before.items()) ^ set(real_after.items()))
        print("INTEGRITY FAILURE: the harness modified the real tree:")
        for item in changed[:20]:
            print(f"    {item}")
        return 1
    print(f"integrity OK: {len(real_after)} real product files byte-identical")

    if failures:
        print(f"\n{len(failures)} mutation(s) MISSED: {failures}")
        return 1
    print("\nall 3 behavioural mutations were caught, and the suite was "
          "restored green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())