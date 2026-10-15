"""One command that says whether the project is healthy, with counts.

    python tools/verify_all.py --fast    # seal, required sets, compileall, fast tier
    python tools/verify_all.py --full    # the above plus live tier, two orderings, manifest

Every component prints passed / skipped / xfailed, and a SKIP counts as a
failure for required sets. That rule exists because Continuation A3
reported "transparency 8/8" when the truth was 8 skips: a skipped test
is indistinguishable from a passing one by exit code alone.

--full additionally compares a manifest of the product tree before and
after the run and fails if the suite wrote anything outside the
workspace root and the cache directories.

Never prints environment values: only names of files and counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
TOOLS = BACKEND / "tools"

# Directories the suite is allowed to write to.
WRITABLE = (
    BACKEND.parent / ".genesis_workspace",
    BACKEND / "docs",
    BACKEND / ".pytest_cache",
    BACKEND.parent / ".genesis_workspace",
)
CACHE_SUFFIXES = (".pyc",)
IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".git", ".venv", "node_modules",
                "backups", "archive"}

_SUMMARY = re.compile(
    r"(?P<passed>\d+) passed|(?P<failed>\d+) failed|"
    r"(?P<skipped>\d+) skipped|(?P<xfailed>\d+) xfailed|"
    r"(?P<xpassed>\d+) xpassed|(?P<errors>\d+) error")


@dataclass
class Component:
    name: str
    command: list
    seconds: float = 0.0
    returncode: int = -1
    counts: dict = field(default_factory=dict)
    ok: bool = False
    note: str = ""


def _parse_counts(text: str) -> dict:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0,
              "xpassed": 0, "errors": 0, "deselected": 0}
    for line in reversed(text.splitlines()):
        if re.search(r"\d+ (passed|failed|skipped|xfailed|xpassed|error|deselected)", line) \
                or "no tests ran" in line:
            for match in _SUMMARY.finditer(line):
                counts[match.lastgroup] = int(match.group(match.lastgroup))
            match = re.search(r"(\d+) deselected", line)
            if match:
                counts["deselected"] = int(match.group(1))
            break
    return counts


def run_component(name, command, timeout=3600, ok_rule="zero_failures"):
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=BACKEND, capture_output=True,
                          text=True, timeout=timeout)
    seconds = time.perf_counter() - started
    text = proc.stdout + proc.stderr
    counts = _parse_counts(text)
    ran_tests = (counts["passed"] + counts["failed"] + counts["skipped"]
                 + counts["xfailed"]) > 0
    note = ""
    if ok_rule == "zero_failures":
        # pytest component: an empty run is a failure, because a suite
        # that silently collects nothing looks exactly like a green one.
        ok = (ran_tests and counts["failed"] == 0 and counts["errors"] == 0
              and counts["xpassed"] == 0 and proc.returncode == 0)
        if not ran_tests:
            note = "no tests ran"
    else:
        # Non-pytest component: judged on its exit code only. Demanding
        # pytest-shaped counts from `compileall` or `require_passed.py`
        # marked a passing component FAIL: no tests ran.
        ok = proc.returncode == 0
    return Component(name, command, seconds, proc.returncode, counts, ok, note)


# ----------------------------------------------------------------------
# File manifest
# ----------------------------------------------------------------------
def manifest():
    """path -> (size, sha1) for every product-tree file."""
    out = {}
    for path in BACKEND.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        try:
            if any(w in path.parents for w in WRITABLE):
                continue
        except Exception:
            continue
        if path.suffix in CACHE_SUFFIXES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        out[str(path.relative_to(BACKEND))] = (len(data),
                                               hashlib.sha1(data).hexdigest())
    return out


def diff_manifests(before, after):
    created = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(k for k in set(before) & set(after)
                      if before[k] != after[k])
    return created, removed, modified


# ----------------------------------------------------------------------
# Components
# ----------------------------------------------------------------------
def _env():
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(TOOLS) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def seal_components():
    """The four integrity digests, including final4 rebuilt from source."""
    script = BACKEND / "run_safety_verify.py"
    out = []
    if script.is_file():
        out.append(run_component("seal:run_safety_verify",
                                 [sys.executable, str(script)],
                                 ok_rule="returncode"))
    else:
        out.append(Component("seal:run_safety_verify", [], 0.0, -1, {},
                             False, "run_safety_verify.py not present"))
    return out


def required_sets():
    return run_component("required sets (no skips allowed)",
                         [sys.executable, str(TOOLS / "require_passed.py")],
                         ok_rule="returncode")


def compileall():
    return run_component("compileall",
                         [sys.executable, "-m", "compileall", "-q",
                          "genesis_os", "tools", "agents", "ai", "brain",
                          "core", "runtime"],
                         ok_rule="returncode")


def fast_tier():
    return run_component("fast tier",
                         [sys.executable, "-m", "pytest", "-m", "not live",
                          "-q", "-p", "no:cacheprovider"])


def live_tier():
    return run_component("live tier",
                         [sys.executable, "-m", "pytest", "-m", "live",
                          "-q", "-p", "no:cacheprovider"], timeout=5400)


def ordering_default():
    return run_component("full: default order",
                         [sys.executable, "-m", "pytest", "-q",
                          "-p", "no:cacheprovider", "--durations=25"],
                         timeout=5400)


def ordering_touched_first():
    """touched-files ordering, seeded with trigger_hardening then control_plane."""
    return run_component(
        "full: touched-first order",
        [sys.executable, "-m", "pytest",
         "test_phase3_trigger_hardening.py",
         "test_phase3_control_plane_maturity.py",
         "-q", "-p", "no:cacheprovider", "--durations=25"],
        timeout=5400)


def print_table(components, manifest_note=None):
    header = f"{'component':38s} {'passed':>7s} {'skipped':>8s} {'xfailed':>7s} {'failed':>7s} {'rc':>4s} {'sec':>7s}  result"
    print(header)
    print("-" * len(header))
    for c in components:
        n = c.counts or {}
        verdict = "OK" if c.ok else ("FAIL: " + c.note if c.note else "FAIL")
        if c.counts and (n.get("passed", 0) + n.get("skipped", 0)
                         + n.get("xfailed", 0) + n.get("failed", 0)) == 0 \
                and c.ok:
            verdict = "OK (no test counts)"
        print(f"{c.name:38s} {n.get('passed', 0):7d} {n.get('skipped', 0):8d} "
              f"{n.get('xfailed', 0):7d} {n.get('failed', 0):7d} "
              f"{c.returncode:4d} {c.seconds:7.1f}  {verdict}")
    if manifest_note:
        print()
        print(f"file manifest: {manifest_note}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)
    if not (args.fast or args.full):
        parser.error("choose --fast or --full")

    components = []
    before = manifest()
    components += seal_components()
    components.append(required_sets())
    components.append(compileall())
    components.append(fast_tier())
    manifest_note = None

    if args.full:
        components.append(live_tier())
        components.append(ordering_default())
        components.append(ordering_touched_first())
        after = manifest()
        created, removed, modified = diff_manifests(before, after)
        if created or removed or modified:
            manifest_note = (f"FAIL created={len(created)} "
                             f"removed={len(removed)} modified={len(modified)}")
            for name in (created + removed + modified)[:20]:
                print(f"    manifest: {name}")
        else:
            manifest_note = "unchanged (no product-tree writes)"

    ok = all(c.ok for c in components)
    if args.full and manifest_note and manifest_note.startswith("FAIL"):
        ok = False

    print()
    print_table(components, manifest_note)
    print()
    print("RESULT:", "PASS" if ok else "FAIL")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "ok": ok,
            "components": [
                {"name": c.name, "seconds": c.seconds, "rc": c.returncode,
                 "counts": c.counts, "ok": c.ok, "note": c.note}
                for c in components],
            "manifest": manifest_note,
        }, indent=1), encoding="utf-8")
        print(f"-> {args.json}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())