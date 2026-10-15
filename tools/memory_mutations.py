"""In-memory mutation specs, and the product-tree fingerprint.

Why this replaces the sandbox-copy harness
------------------------------------------
The previous harness (`run_behavior_mutations.py`) copied ~20 product
directories to a temp directory, mutated the copy, and ran the tests
there. It reported every mutation MISSED, and the reason was two
independent bugs in the instrument, not in the tests:

  1. The copy list omitted `emotion`. `brain/brain.py` imports
     `emotion.emotion`, so every test in the target module ERRORed at
     setup. Reproduced here: 13 errors, 0 runs.
  2. The result parser only looked at lines starting with `FAILED `. A
     collection or setup ERROR therefore produced an EMPTY failure list,
     which the harness rendered as `MISSED`.

Bug 2 is the serious one and it is the exact failure this instrument
exists to prevent: an instrument that never fired was indistinguishable
from a suite with no coverage. A mutation harness that reports MISSED
when the test file did not even run is worse than no harness, because it
converts "I did not measure" into "the behaviour is untested".

So: no copying, no writing. A mutation is a (module, text-transform)
pair applied to source held in memory and served to the import system by
a `sys.meta_path` finder (see `memmut_plugin.py`). The real tree is the
thing under test, so the baseline can be measured -- which the sandbox
made impossible, because the sandbox was not the tree.

Two invariants this module exists to enforce
--------------------------------------------
  * A transform that does not change the source is a HARD ERROR
    (`MutationNotApplied`), never a skip. It is also an error to match
    more times than declared, which is the other way a stale pattern
    goes quiet.
  * The product tree is fingerprinted before and after every harness
    run and must be byte-identical (`TreeIntegrityError`).

Line endings
------------
Matching happens on NORMALISED text (CRLF and lone CR folded to LF).
The mutation is then served from memory, so normalising costs nothing:
there is no file to keep consistent and no whole-file diff to bury the
change in. Patterns here are ordinary triple-quoted strings containing
REAL newlines, so there is no `\r\n`/`\n` escape puzzle in a raw string
-- the bug that made the old harness's third mutation silently not match.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# The single name the mutation request travels under. Defined here, not in
# the plugin, so the driver and the plugin cannot drift apart.
MUTATION_ENV_VAR = "GENESIS_MUTATION"

# Directories that are build/run residue rather than product. A tree that
# contains them is not being fingerprinted for its source, and bytecode
# caches legitimately change on any Python run.
FINGERPRINT_EXCLUDED_DIRS = frozenset({
    ".venv", "__pycache__", ".pytest_cache", "backups", ".git",
    ".genesis_workspace", "node_modules",
})

# The harness writes its own report under docs/ and its own scratch
# artefacts under tools/. Those are harness output, not product, and must
# not make the integrity check fire on the harness's own bookkeeping.
FINGERPRINT_EXCLUDED_FILES = frozenset({
    "docs/manifest_diff_c1.json",
})


class MutationNotApplied(RuntimeError):
    """A transform changed nothing, or changed the wrong amount.

    Raised, never reported as SKIP or MISSED. See the module docstring.
    """


class TreeIntegrityError(RuntimeError):
    """A product file's bytes changed while the harness ran."""


# ----------------------------------------------------------------------
# Normalisation
# ----------------------------------------------------------------------

def normalise(text: str) -> str:
    """Fold CRLF and lone CR to LF.

    genesis.py is 3722 CRLF and 0 bare LF today, and the old harness's
    comments describe it as MIXED. It has been both at some point, so
    the harness must not care which: normalise, match, mutate, serve
    from memory.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def apply_mutation(source: str, spec: "MemoryMutation") -> str:
    """Return `source` with `spec` applied, or raise `MutationNotApplied`.

    The transform is a LITERAL substring replacement, not a regular
    expression. That is deliberate and it was learned the hard way:
    `def classify(self, text):` read as a regex makes `(self, text)` a
    capture group, so the pattern matches `def classifyself, text:` and
    silently matches nothing in a file where it plainly appears. A
    mutation spec is a piece of source text, not a search expression, and
    nothing here needs the power of a regex -- every mutation is an
    anchored, whole-line edit.

    Raises if:
      * the text does not occur at all;
      * it occurs a different number of times than `spec.expect_matches`;
      * the result is identical to the input;
      * the result does not compile.

    The last check matters: a mutation that produces unparseable source
    makes every test ERROR, which bug 2 above would then render MISSED.
    """
    normalised = normalise(source)
    needle = normalise(spec.pattern)
    count = normalised.count(needle)
    mutated = normalised.replace(needle, normalise(spec.replacement))

    if count != spec.expect_matches:
        raise MutationNotApplied(
            f"mutation {spec.name!r} expected to match "
            f"{spec.expect_matches} time(s) but matched {count}. "
            f"Text was: {spec.pattern!r}. "
            f"A stale spec is an instrument that has stopped "
            f"measuring, so this is a hard failure, not a skip.")

    if mutated == normalised:
        # Possible only if the replacement is identical to the match.
        raise MutationNotApplied(
            f"mutation {spec.name!r} matched {count} time(s) but produced "
            f"source identical to the input; the transform is a no-op.")

    try:
        compile(mutated, f"<memmut:{spec.module}>", "exec")
    except SyntaxError as error:
        raise MutationNotApplied(
            f"mutation {spec.name!r} produced source that does not "
            f"compile ({error}). A mutation that breaks the parse makes "
            f"every test ERROR, which the old harness rendered MISSED."
        ) from error

    return mutated


# ----------------------------------------------------------------------
# The three behavioural mutations
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class MemoryMutation:
    name: str
    module: str
    pattern: str
    replacement: str
    expect_matches: int = 1
    # The BEHAVIOURAL tests that must fail. The harness does not accept
    # "some test failed"; it accepts "a test that asserts the behaviour
    # this mutation removed failed".
    caught_by: tuple = field(default=())
    why: str = ""


# The entry point's behavioural coverage lives in this file. It is the
# file Continuation A5's rename mutation turned red through, and it is
# the file whose tests assert OBSERVABLE behaviour rather than the
# existence of a member.
ENTRYPOINT_TARGETS = ("test_genesis_entrypoint_behavior.py",)


MUTATIONS: tuple = (
    MemoryMutation(
        name="classify renamed away",
        module="genesis",
        pattern="    def classify(self, text):\n",
        replacement="    def _MUTATED_removed_classify(self, text):\n",
        expect_matches=1,
        caught_by=(
            "test_classify_routes_a_greeting_to_level_1",
            "test_classify_routes_open_application_to_level_3",
            "test_classify_sets_the_right_operation_for_an_application_open",
            "test_classify_marks_a_compound_request_as_mixed",
        ),
        why=(
            "A5's mutation. Must be caught by tests that CALL classify, "
            "not by a test that asserts the member exists."
        ),
    ),
    MemoryMutation(
        name="classify returns Level 3 routing for everything",
        module="genesis",
        pattern="    def classify(self, text):\n",
        replacement=(
            "    def classify(self, text):\n"
            "        _result = _MUTATED_classify(self, text)\n"
            "        _result['level'] = 3\n"
            "        _result['mode'] = 'os'\n"
            "        return _result\n"
            "\n"
            "    def _MUTATED_classify(self, text):\n"
        ),
        expect_matches=1,
        caught_by=(
            "test_classify_routes_a_greeting_to_level_1",
        ),
        why=(
            "The single-level shortcut. Caught by the greeting test, "
            "which asserts level 1 / mode conversation: every other "
            "classify test still expects level 3 and would pass."
        ),
    ),
    MemoryMutation(
        name="run_level3 skips the workspace boundary check",
        module="genesis",
        pattern=(
            "    def run_level3(\n"
            "        self,\n"
            "        text,\n"
            "        classification\n"
            "    ):\n"
        ),
        replacement=(
            "    def run_level3(\n"
            "        self,\n"
            "        text,\n"
            "        classification\n"
            "    ):\n"
            "        import os as _os\n"
            "        _os.environ.pop('GENESIS_WORKSPACE_ROOT', None)\n"
        ),
        expect_matches=1,
        caught_by=(
            "test_run_level3_does_not_create_a_file_outside_the_workspace",
        ),
        why=(
            "Disarms the boundary for this call by removing the env key "
            "the executor reads. The old harness's pattern for this one "
            "was a raw string containing \\r\\n escapes, which is why it "
            "was the mutation that silently matched nothing."
        ),
    ),
)

MUTATIONS_BY_NAME = {m.name: m for m in MUTATIONS}


# ----------------------------------------------------------------------
# Product-tree fingerprint
# ----------------------------------------------------------------------

def iter_product_files(root: Path | None = None):
    """Every product file under `root`, excluding build/run residue."""
    root = Path(root or BACKEND)
    for dirpath, dirnames, filenames in __import__("os").walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in FINGERPRINT_EXCLUDED_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if rel in FINGERPRINT_EXCLUDED_FILES:
                continue
            yield path, rel


def product_fingerprint(root: Path | None = None) -> dict:
    """sha256 -> {relative posix path: sha256} for every product file.

    Every file, not just `.py`: the previous harness hashed only
    `*.py`, which would not have noticed a test writing a zero-byte file
    called `file` into the tree -- which is exactly the artefact this
    fingerprint now has to defend against.
    """
    root = Path(root or BACKEND)
    out = {}
    for path, rel in iter_product_files(root):
        try:
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            # A file that vanished mid-walk is itself a change; record it
            # as absent rather than skipping it silently.
            out[rel] = "<unreadable>"
    return out


def fingerprint_diff(before: dict, after: dict) -> list:
    """Human-readable description of every difference between two maps."""
    lines = []
    for rel in sorted(set(before) | set(after)):
        b, a = before.get(rel), after.get(rel)
        if b == a:
            continue
        if b is None:
            lines.append(f"  + CREATED   {rel}")
        elif a is None:
            lines.append(f"  - DELETED   {rel}")
        else:
            lines.append(f"  ~ MODIFIED  {rel}\n"
                         f"      before {b}\n"
                         f"      after  {a}")
    return lines


def check_fingerprint(before: dict, after: dict, context: str = "") -> None:
    """Raise `TreeIntegrityError` naming every file that changed."""
    diff = fingerprint_diff(before, after)
    if not diff:
        return
    raise TreeIntegrityError(
        f"product tree changed during {context or 'the harness run'}:\n"
        + "\n".join(diff))


def fingerprint_root_digest(fingerprint: dict) -> str:
    """One hash summarising a whole fingerprint map, for logging."""
    joined = "\n".join(f"{k}:{v}" for k, v in sorted(fingerprint.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()