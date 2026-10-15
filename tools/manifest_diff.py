"""Diff the current tree against a backup manifest.

    python tools/manifest_diff.py

Classifies every difference so "unexpected product-code change" is a
decided question rather than something you scroll for.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

# Directories this effort created and expects to differ.
EXPECTED_PREFIXES = (
    "tools/", "docs/", "benchmark_real_os/",
)
EXPECTED_FILES = {
    "conftest.py",                 # data-driven marks + tripwire + fixtures
    "test_genesis_entrypoint_behavior.py",   # B1 behavioural entry point
}
# Paths moved by this effort.
EXPECTED_REMOVED = {"calculator.py"}

# Classified after the first C1 run, with reasons.
#
# SEAL_DIGESTS.txt is NOT a hygiene-session change: the current file is
# byte-identical to the archive shipped with the manifest
# (sha256 318c8c1e...), and the manifest's own entry
# (f64251a1...) disagrees with its own archive. The manifest was already
# wrong about this file at backup time.
EXPECTED_CHANGED = {
    "SEAL_DIGESTS.txt":
        "pre-existing manifest/archive disagreement; disk == archive",
    "genesis_os/approval_audit.jsonl":
        "append-only audit log written by test runs; grows every session",
}

# Added since Oct 9, classified.
EXPECTED_ADDED = {
    ".env": "local config, excluded from the backup",
    "bench_run.log": "log output from a benchmark run",
    "full_test_suite.log": "log output from a suite run",
    "file": "PRODUCT-TREE POLLUTION: a zero-byte file named 'file' "
            "created in the backend root by a test writing a relative "
            "path. Not product code, but it IS a suite writing into the "
            "product tree, which the manifest check in verify_all "
            "--full is meant to catch. Listed, not deleted here.",
    "test_import_smoke.py": "created by this hygiene effort",
    "test_structural_census.py": "created by this hygiene effort",
}


def norm(rel):
    return rel.replace("\\", "/")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    recorded = manifest["files"]

    recorded = {norm(k): v for k, v in recorded.items()}

    def recorded_sha(value):
        """The manifest stores {'bytes': N, 'sha256': '...'}.

        Comparing the dict itself against a hex string reports EVERY
        file as changed. That is how SEAL_DIGESTS.txt first appeared as
        an unexpected modification when it is in fact byte-identical.
        """
        if isinstance(value, dict):
            return value.get("sha256", "")
        return str(value)

    current = {}
    for path in BACKEND.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith((".pytest_cache/", "__pycache__/", ".git/")):
            continue
        if "/__pycache__/" in rel or rel.endswith(".pyc"):
            continue
        try:
            current[rel] = digest(path)
        except OSError:
            continue

    changed, added, removed = [], [], []
    for rel, sha in recorded.items():
        if rel not in current:
            removed.append(rel)
        elif current[rel] != recorded_sha(sha):
            changed.append(rel)
    for rel in current:
        if rel not in recorded:
            added.append(rel)

    def expected(rel):
        return (rel in EXPECTED_FILES or rel.startswith(EXPECTED_PREFIXES)
                or rel in EXPECTED_REMOVED or rel in EXPECTED_CHANGED
                or rel in EXPECTED_ADDED)

    unexpected_changed = sorted(r for r in changed if not expected(r))
    unexpected_removed = sorted(r for r in removed if not expected(r))

    report = {
        "manifest": args.manifest,
        "manifest_created": manifest.get("created_local"),
        "recorded_files": len(recorded),
        "current_files": len(current),
        "changed": sorted(changed),
        "added": sorted(added),
        "removed": sorted(removed),
        "unexpected_changed": unexpected_changed,
        "unexpected_removed": unexpected_removed,
        "unexpected_added": sorted(r for r in added if not expected(r)),
    }
    print(f"recorded {len(recorded)} | current {len(current)}")
    print(f"changed {len(changed)} | added {len(added)} | removed {len(removed)}")
    print()
    print(f"UNEXPECTED changed ({len(unexpected_changed)}):")
    for rel in unexpected_changed:
        print(f"  {rel}")
        print(f"      now: {current[rel][:16]}")
    print(f"UNEXPECTED removed ({len(unexpected_removed)}):")
    for rel in unexpected_removed:
        print(f"  {rel}")
    print(f"UNEXPECTED added ({len(report['unexpected_added'])}):")
    for rel in report["unexpected_added"]:
        print(f"  {rel}  {current[rel][:16]}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, sort_keys=True),
                                   encoding="utf-8")
        print(f"\n-> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())