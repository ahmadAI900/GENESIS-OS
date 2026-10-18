"""Item 15A (S12): overwrite escalation was missing for six document writes.

`document.create_docx` had an overwrite evaluator. Its five non-docx
siblings -- create_txt, create_csv, create_json, create_markdown,
create_pdf -- and `document.transform` did not.

All six open their destination with mode "w", which truncates whatever
was there. So writing onto an existing file destroyed it while the
blast-radius authority resolved REVERSIBLE_LOCAL and no grant was ever
requested.

Measured against the committed original, with the workspace root set so
the separate workspace-boundary check cannot mask the result:

    OPERATION                 EVALUATOR?   EXISTING TARGET
    document.create_docx      True         irreversible_or_outward
    document.transform        False        reversible_local   <-- gap
    document.create_txt       False        reversible_local   <-- gap
    document.create_csv       False        reversible_local   <-- gap
    document.create_json      False        reversible_local   <-- gap
    document.create_markdown  False        reversible_local   <-- gap
    document.create_pdf       False        reversible_local   <-- gap

NOTE ON MEASUREMENT, because it nearly produced a false negative here:
without GENESIS_WORKSPACE_ROOT set, EVERY path escalates via the
unrelated workspace-boundary check, and the gap is invisible. The
reproduction has to place the target INSIDE the workspace.

`file.create` appears in the table and is NOT broken: its resolver
deliberately returns None without an explicit `overwrite` flag, because
the manager refuses in that case. A test pins that, so the two
mechanisms are not confused later.
"""
from __future__ import annotations

import os
import sys

import pytest


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A real workspace root, set the way the boundary check reads it."""
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv("GENESIS_WORKSPACE_ROOT", str(root))

    # workspace_boundary resolves the root through a cached helper in
    # some code paths; clear anything memoised on the imported modules.
    import genesis_os.workspace_boundary as wb
    import genesis_os.blast_radius as br

    for module in (wb, br):
        for name in list(vars(module)):
            obj = vars(module)[name]
            if hasattr(obj, "cache_clear"):
                obj.cache_clear()

    from genesis_os.workspace_boundary import workspace_root

    assert str(workspace_root()) == str(root)
    return root


CREATE_OPS = [
    "document.create_txt",
    "document.create_csv",
    "document.create_json",
    "document.create_markdown",
    "document.create_pdf",
]
ALL_SIX = ["document.transform", *CREATE_OPS]


def _args_for(operation, target):
    if operation == "document.transform":
        return {"path": str(target) + ".src", "output_path": str(target)}
    return {"path": str(target)}


@pytest.fixture
def resolve():
    from genesis_os.blast_radius import resolve_blast_radius

    return resolve_blast_radius


@pytest.fixture
def has_evaluator():
    from genesis_os.blast_radius import has_dynamic_evaluator

    return has_dynamic_evaluator


# --------------------------------------------------------------------------
# The defect: overwriting an existing file must escalate
# --------------------------------------------------------------------------

@pytest.mark.parametrize("operation", ALL_SIX)
def test_overwriting_an_existing_file_escalates(operation, workspace, resolve):
    from genesis_os.capabilities import BlastRadius

    target = workspace / "report.txt"
    target.write_text("PRECIOUS DATA")

    radius = resolve(operation, _args_for(operation, target))

    assert radius is BlastRadius.IRREVERSIBLE_OR_OUTWARD, (
        f"{operation} writing onto an existing in-workspace file "
        f"resolved {getattr(radius, 'value', radius)}; that destroys "
        "data and must require a grant"
    )


@pytest.mark.parametrize("operation", ALL_SIX)
def test_each_operation_has_an_evaluator(operation, has_evaluator):
    assert has_evaluator(operation) is True, (
        f"{operation} has no overwrite evaluator registered, so its "
        "static REVERSIBLE_LOCAL default is all the authority ever sees"
    )


# --------------------------------------------------------------------------
# The counterpart: a FREE destination stays ungated
# --------------------------------------------------------------------------

@pytest.mark.parametrize("operation", ALL_SIX)
def test_creating_a_new_file_stays_reversible(operation, workspace, resolve):
    from genesis_os.capabilities import BlastRadius

    target = workspace / "brand_new.txt"

    assert not target.exists()

    radius = resolve(operation, _args_for(operation, target))

    assert radius is BlastRadius.REVERSIBLE_LOCAL, (
        f"{operation} escalated for a destination that does not exist: "
        f"{getattr(radius, 'value', radius)}. Creating a new file is "
        "reversible -- delete it -- and gating it would make the "
        "overwrite check useless."
    )


# --------------------------------------------------------------------------
# document.transform specifically: the source must not become the target
# --------------------------------------------------------------------------

def test_transform_reads_output_path_not_the_source(workspace, resolve):
    """`path` is the SOURCE and always exists.

    If the destination key were `path`, every transform would escalate
    as a self-overwrite -- including transforms onto a free
    destination. This is the failure mode that makes registering the
    key correctly matter more than registering it at all.
    """
    from genesis_os.capabilities import BlastRadius

    source = workspace / "in.docx"
    source.write_bytes(b"x")
    free = workspace / "converted.txt"

    args = {"path": str(source), "output_path": str(free)}

    assert resolve("document.transform", args) is BlastRadius.REVERSIBLE_LOCAL, (
        "transform escalated even though it is writing to a free "
        "destination; the SOURCE is being treated as the destination"
    )


def test_transform_onto_an_existing_non_source_file_escalates(workspace, resolve):
    from genesis_os.capabilities import BlastRadius

    source = workspace / "in.docx"
    source.write_bytes(b"x")
    clobbered = workspace / "already-there.txt"
    clobbered.write_text("someone else's work")

    args = {"path": str(source), "output_path": str(clobbered)}

    assert resolve("document.transform", args) is BlastRadius.IRREVERSIBLE_OR_OUTWARD


# --------------------------------------------------------------------------
# Structural guards
# --------------------------------------------------------------------------

def test_the_source_equals_destination_refusal_is_untouched():
    """The manager-side guard must survive: not both, but both layers."""
    from genesis_os.document_intelligence import DocumentIntelligence

    src = os.path.join(os.sep, "tmp", "genesis_15a_src.txt")
    with open(src, "w") as fh:
        fh.write("x")

    try:
        di = DocumentIntelligence()
        with pytest.raises(ValueError, match="must not overwrite the source"):
            di._resolve_output(src, src, ".txt")
    finally:
        os.unlink(src)


@pytest.mark.parametrize(
    "operation,expected",
    [
        ("document.transform", "output_path"),
        ("document.create_txt", "path"),
        ("document.create_csv", "path"),
        ("document.create_json", "path"),
        ("document.create_markdown", "path"),
        ("document.create_pdf", "path"),
        ("document.create_docx", "path"),
    ],
)
def test_each_operation_declares_its_destination_key(operation, expected):
    from genesis_os.blast_radius import _OVERWRITE_DESTINATION_KEYS

    keys = _OVERWRITE_DESTINATION_KEYS.get(operation)

    assert keys is not None, f"{operation} declares no destination key"
    assert keys[0] == expected, (
        f"{operation} declares {keys!r}; the executor forwards "
        f"{expected!r} to the manager, so the first key must be that"
    )


def test_transform_never_declares_path_as_its_destination():
    from genesis_os.blast_radius import _OVERWRITE_DESTINATION_KEYS

    assert "path" not in _OVERWRITE_DESTINATION_KEYS["document.transform"], (
        "transform's `path` is the SOURCE; declaring it would make every "
        "transform look like a self-overwrite"
    )


def test_every_registered_overwrite_operation_declares_a_destination_key():
    """A registered evaluator that cannot resolve a destination is dead."""
    from genesis_os.blast_radius import (
        _OVERWRITE_DESTINATION_KEYS,
        _RENAME_OPERATIONS,
        has_dynamic_evaluator,
    )

    dead = []
    for capability_id in (
        "file.move", "file.rename", "folder.move", "folder.rename",
        "file.copy", "file.create", "document.create_docx",
        *ALL_SIX,
    ):
        if not has_dynamic_evaluator(capability_id):
            continue
        keys = _OVERWRITE_DESTINATION_KEYS.get(capability_id)
        if not keys:
            dead.append(capability_id)

    assert not dead, (
        f"overwrite evaluator(s) registered with no destination key, so "
        f"they can never fire: {dead}"
    )


# --------------------------------------------------------------------------
# file.create must keep its deliberate exception
# --------------------------------------------------------------------------

def test_file_create_without_overwrite_flag_stays_reversible(workspace, resolve):
    """Not a bug: the manager refuses, so nothing is destroyed."""
    from genesis_os.capabilities import BlastRadius

    target = workspace / "notes.txt"
    target.write_text("existing")

    radius = resolve("file.create", {"path": str(target)})

    assert radius is BlastRadius.REVERSIBLE_LOCAL, (
        "file.create without overwrite=True escalated. That guard is "
        "deliberate: the manager refuses the call, so no data is lost."
    )


def test_file_create_with_overwrite_flag_escalates(workspace, resolve):
    from genesis_os.capabilities import BlastRadius

    target = workspace / "notes.txt"
    target.write_text("existing")

    radius = resolve(
        "file.create", {"path": str(target), "overwrite": True}
    )

    assert radius is BlastRadius.IRREVERSIBLE_OR_OUTWARD


# --------------------------------------------------------------------------
# End to end: the bytes really are destroyed, which is why this matters
# --------------------------------------------------------------------------

def test_create_txt_really_does_truncate_an_existing_file(workspace):
    """Ground truth for the test above: the write is destructive."""
    from genesis_os.document_intelligence import DocumentIntelligence

    target = workspace / "notes.txt"
    target.write_text("PRECIOUS")

    result = DocumentIntelligence().create_txt(str(target), "new content")

    assert result.success is True, result
    assert target.read_text() == "new content"
    assert "PRECIOUS" not in target.read_text(), (
        "create_txt no longer truncates; if that ever becomes true the "
        "escalation is over-strict and should be revisited"
    )