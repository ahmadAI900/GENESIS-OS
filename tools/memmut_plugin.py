"""Serve MUTATED source for one module, from memory, to the import system.

How the mutation reaches the running test process
------------------------------------------------
A pytest plugin named on the command line with `-p memmut_plugin` is
imported by `Config._preparse`, BEFORE `pytest_load_initial_conftests`
runs. That ordering is the whole mechanism: the finder below must be on
`sys.meta_path` before anything imports the target module, and
`backend/conftest.py` (which imports `genesis_os` at module level) is one
of the first things pytest loads. Installing at plugin IMPORT time, not
in `pytest_configure`, is therefore deliberate -- `pytest_configure` is
too late.

    python -m pytest <targets> -p memmut_plugin

Configuration arrives as ONE json blob in `GENESIS_MUTATION`, because a
mutation pattern contains newlines and quotes and passing those through
a Windows command line is exactly where the previous harness lost a
mutation silently.

What this does NOT do
---------------------
It does not write, copy, or modify anything on disk. The mutated source
exists only as a Python string in this process and as a code object
produced from it. That is what lets the same harness measure a BASELINE
against the real tree, which a sandbox copy could not do.

Failure modes are all loud
--------------------------
  * target already imported  -> `MutationNotApplied`, before any test runs
  * pattern matched nothing -> `MutationNotApplied`, before any test runs
  * mutated source unparseable -> `MutationNotApplied`, before any test runs

None of these can reach the test report. A mutation that was never
applied must never look like a mutation that was not detected.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

ENV_VAR = "GENESIS_MUTATION"

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND / "tools") not in sys.path:
    sys.path.insert(0, str(BACKEND / "tools"))

import memory_mutations as mm  # noqa: E402

# Single source of truth, shared with tools/run_memory_mutations.py.
ENV_VAR = mm.MUTATION_ENV_VAR


class MutationSetupError(RuntimeError):
    """The mutation could not be installed. Never reaches a test report."""


class _MutatedSourceLoader(importlib.abc.Loader):
    """Executes pre-compiled mutated source for one module."""

    def __init__(self, source: str, origin: str):
        self._source = source
        self._origin = origin
        # Filename carries the marker so a traceback from inside a
        # mutation is self-identifying: if a failure shows
        # `<memmut:genesis.py>` it came through this harness.
        self._filename = f"<memmut:{origin}>"

    def create_module(self, spec):
        return None  # default module creation

    def exec_module(self, module):
        module.__file__ = self._origin
        code = compile(self._source, self._filename, "exec")
        exec(code, module.__dict__)

    def get_source(self, name):
        return self._source

    def get_filename(self, name):
        return self._origin


class _MutatedSourceFinder(importlib.abc.MetaPathFinder):
    """Answers for exactly one module name; defers everything else."""

    def __init__(self, target: str, source: str, origin: str):
        self._target = target
        self._source = source
        self._origin = origin

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self._target:
            return None
        loader = _MutatedSourceLoader(self._source, self._origin)
        spec = importlib.machinery.ModuleSpec(fullname, loader,
                                              origin=self._origin)
        spec.has_location = True
        return spec


def _read_request():
    raw = os.environ.get(ENV_VAR)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError as error:
        raise MutationSetupError(
            f"{ENV_VAR} is not valid json: {error}\nvalue was: {raw[:400]}"
        ) from error


def install(request) -> dict:
    """Validate the request, compute the mutation, install the finder.

    Returns a small dict describing what was installed, which the plugin
    prints to stdout so a log line proves the mutation was live.
    """
    name = request.get("name") or "<unnamed>"
    module_name = request["module"]
    spec = mm.MemoryMutation(
        name=name,
        module=module_name,
        pattern=request["pattern"],
        replacement=request["replacement"],
        expect_matches=int(request.get("expect_matches", 1)),
    )

    if module_name in sys.modules:
        raise MutationSetupError(
            f"mutation {name!r}: {module_name!r} was imported before the "
            f"mutating finder was installed, so it is already in "
            f"sys.modules and the real source would be used. Import it "
            f"lazily, or load the plugin earlier."
        )

    try:
        origin = importlib.util.find_spec(module_name)
    except (ImportError, ValueError) as error:
        raise MutationSetupError(
            f"mutation {name!r}: cannot locate module {module_name!r} "
            f"({error})") from error
    if origin is None or not origin.origin:
        raise MutationSetupError(
            f"mutation {name!r}: module {module_name!r} has no origin "
            f"(namespace package?); there is no source file to read.")

    source_path = Path(origin.origin)
    original = source_path.read_text(encoding="utf-8")
    mutated = mm.apply_mutation(original, spec)

    finder = _MutatedSourceFinder(module_name, mutated, str(source_path))
    sys.meta_path.insert(0, finder)

    return {
        "name": name,
        "module": module_name,
        "origin": str(source_path),
        "original_bytes": len(original.encode("utf-8")),
        "mutated_bytes": len(mutated.encode("utf-8")),
        "finder": finder,
    }


# ----------------------------------------------------------------------
# Plugin hooks
# ----------------------------------------------------------------------

INSTALLED = {}


def pytest_configure(config):
    """Confirm at configure time that the mutation is actually live.

    `install()` runs at import; this re-checks from inside the test
    process and prints a line, so a log always says whether the run was
    baseline or mutated. It also verifies the finder is still first on
    the path -- something else could have inserted ahead of it.
    """
    request = _read_request()
    if request is None:
        config._genesis_mutation = None
        return
    info = INSTALLED.get("info")
    if info is None:
        # Import ran without GENESIS_MUTATION set (e.g. an inner pytest
        # run). Re-read now so a late-set env var still works.
        info = install(_read_request())
        INSTALLED["info"] = info
    if sys.meta_path[0] is not info["finder"]:
        raise MutationSetupError(
            f"the mutating finder is not first on sys.meta_path; "
            f"something displaced it and the mutation may not apply.")
    config._genesis_mutation = info
    print(f"[memmut] MUTATED {info['module']} :: {info['name']} "
          f"({info['original_bytes']} -> {info['mutated_bytes']} bytes, "
          f"in memory only)")


def pytest_unconfigure(config):
    info = INSTALLED.get("info")
    if info and info["finder"] in sys.meta_path:
        sys.meta_path.remove(info["finder"])


def pytest_report_header(config):
    info = getattr(config, "_genesis_mutation", None)
    if not info:
        return "memmut: BASELINE (no mutation)"
    return f"memmut: MUTATING {info['module']} :: {info['name']}"


# ----------------------------------------------------------------------
# Import-time installation.
#
# Module level, not inside a hook: `-p` plugins are imported during
# Config._preparse, which is before initial conftests load.
# ----------------------------------------------------------------------
_request = _read_request()
if _request is not None:
    try:
        INSTALLED["info"] = install(_request)
    except mm.MutationNotApplied as error:
        # Loud, immediate, and NOT a test failure: a mutation that was
        # never applied is an instrument failure. Printed to stderr so it
        # survives even if pytest dies during startup.
        print(f"[memmut] MUTATION NOT APPLIED: {error}", file=sys.stderr)
        raise