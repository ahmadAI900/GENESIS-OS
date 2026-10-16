"""Item 6B -- the stale in-tree approval audit log is gone and stays gone.

`genesis_os/approval_audit.jsonl` was a ~806 KB, 2006-entry artifact from
the era when `_audit_path()` was hardcoded to write inside the source
tree. It was untracked and gitignored (so it was never committed), but it
sat in the working directory confusing anyone reading the tree, and
`tools/manifest_diff.py` still listed it as expected to exist and grow.

Item 2 (configurable audit log) removed the behaviour that created it.
This pins the end state:

  * nothing reads the stale file as fixture data (it is only ever an
    "is it untouched?" assertion);
  * a product run recreates the audit log where it is DESIGNED to go
    (a configured path / workspace / temp dir), never inside backend/;
  * the in-tree path is refused even if explicitly configured.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os import approval_channel as AC

BACKEND = Path(__file__).resolve().parent
IN_TREE = BACKEND / "genesis_os" / "approval_audit.jsonl"


def test_the_stale_in_tree_log_is_absent():
    assert not IN_TREE.exists(), (
        f"the stale in-tree audit log is back: {IN_TREE} "
        f"({IN_TREE.stat().st_size if IN_TREE.exists() else 0} bytes). "
        "It is gitignored and must not sit in the tree."
    )


def test_the_in_tree_path_is_gitignored():
    """Even if it reappears it can never be committed.

    Read .gitignore directly rather than shelling out to `git`: the
    capability tripwire correctly fails any test that launches a
    process, because the fast gate must not depend on external binaries.
    """
    ignore_text = (BACKEND / ".gitignore").read_text(encoding="utf-8")
    patterns = {
        line.strip()
        for line in ignore_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "approval_audit.jsonl" in patterns, (
        f".gitignore no longer lists approval_audit.jsonl; a recreated "
        f"in-tree log could be committed. Patterns: {sorted(patterns)}"
    )
    assert ".env" in patterns, ".gitignore must still cover .env"


def test_a_configured_run_writes_the_log_where_designed(tmp_path):
    """The log is still produced -- just not in the source tree."""
    target = tmp_path / "approval_audit.jsonl"
    os.environ["GENESIS_APPROVAL_AUDIT_LOG"] = str(target)
    try:
        request = AC.build_request("file.create", {"path": "C:/probe.txt"})
        AC.append_audit({
            "operation": request.operation,
            "argument_names": sorted(request.arguments),
            "arguments_hash": request.arguments_hash,
            "decision": "denied",
            "channel": "probe",
        })
        resolved = AC._audit_path()
        assert resolved == target.resolve(), resolved
        assert target.exists(), "the audit log was not created where designed"
        assert "probe" in target.read_text(encoding="utf-8")
        assert BACKEND not in resolved.parents, (
            f"the audit log resolved inside the source tree: {resolved}"
        )
    finally:
        os.environ.pop("GENESIS_APPROVAL_AUDIT_LOG", None)


def test_an_in_tree_override_is_skipped_not_honoured(tmp_path):
    """Pointing the env var inside the tree must NOT write there.

    `_audit_path()` builds a candidate list and returns the first entry
    outside backend/. An in-tree override is therefore SKIPPED and the
    next candidate (temp) wins -- which is the behaviour to pin. The
    RuntimeError is reserved for the case where every candidate is
    in-tree, covered by the next test.
    """
    in_tree = BACKEND / "genesis_os" / "approval_audit.jsonl"
    os.environ["GENESIS_APPROVAL_AUDIT_LOG"] = str(in_tree)
    try:
        resolved = AC._audit_path()
        assert resolved != in_tree.resolve(), (
            f"the in-tree override was honoured: {resolved}"
        )
        assert BACKEND not in resolved.parents, (
            f"the audit log resolved inside the source tree: {resolved}"
        )
    finally:
        os.environ.pop("GENESIS_APPROVAL_AUDIT_LOG", None)


def test_nothing_in_the_suite_reads_the_stale_file_as_fixture_data():
    """It may only ever be an 'is it untouched?' assertion, never input."""
    offenders = []
    for path in BACKEND.rglob("test_*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if "approval_audit" not in line:
                continue
            # Reading the repo log for its own bytes is the untouched
            # check and is fine; using it as input would not be.
            if any(tok in line for tok in ("read_text", "open(", "json.load")):
                if "stat(" not in line:
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "something reads the in-tree audit log as data: " f"{offenders}"
    )