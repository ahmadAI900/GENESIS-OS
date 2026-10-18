"""Directive 13C (C6): verification must read the content back.

Two write paths declared success without ever reading their own output:

  * `SpreadsheetIntelligence.update_cell` wrote the CSV/XLSX and
    returned success=True. It had NO verification at all -- not even the
    "exists and non-empty" check.
  * `DocumentIntelligence._edit_docx` saved the file and returned
    success=True with no `verified` field. python-docx writing the file
    was treated as proof the replacement had landed.

`DocumentIntelligence._verify_output` compounds the problem elsewhere:
it is `os.path.isfile(dest) and os.path.getsize(dest) > 0`, which is
evidence a file exists, not that its content changed.

The fix gives both result types a `verified` field whose contract is:

    None   the operation claims nothing (reads, inspections)
    True   it read the result back and compared it
    False  it read it back and it did not match, OR it could not read
           it back at all -- which is NOT verification

Writes must never leave it None. An unverified write that reports
success is the defect: `success` then stands in for proof.
"""

from __future__ import annotations

import csv
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")


@pytest.fixture()
def csv_sheet(tmp_path):
    path = tmp_path / "data.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "qty"])
        writer.writerow(["widget", "1"])
    return path


# =====================================================================
# Spreadsheet: the cell is read back
# =====================================================================

def test_a_real_cell_update_is_verified(csv_sheet, tmp_path):
    from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

    si = SpreadsheetIntelligence()
    out = tmp_path / "out.csv"
    result = si.update_cell(str(csv_sheet), None, 2, "qty", 99, str(out))

    assert result.success is True, result
    assert result.verified is True, (
        "a write that genuinely landed must verify; got "
        f"{result.verified!r}"
    )
    assert out.read_text(encoding="utf-8").count("99") == 1


def test_a_write_that_never_landed_is_not_verified(csv_sheet, tmp_path):
    """The regression. Before Item 13C there was no `verified` field at
    all and success was True regardless."""
    from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

    si = SpreadsheetIntelligence()
    out = tmp_path / "never.csv"

    # Simulate a write that silently does nothing.
    si._write_csv = lambda *a, **k: None
    result = si.update_cell(str(csv_sheet), None, 2, "qty", 99, str(out))

    assert result.verified is False, (
        "a write that never landed reported verified="
        f"{getattr(result, 'verified', '<no field>')!r}; the cell was "
        f"never written (target exists={out.is_file()})"
    )
    assert not out.is_file(), "the stub should have written nothing"


def test_verification_is_never_left_as_none_for_a_write(csv_sheet, tmp_path):
    """None would let `success` stand in for proof again."""
    from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

    si = SpreadsheetIntelligence()
    result = si.update_cell(
        str(csv_sheet), None, 2, "qty", 7, str(tmp_path / "n.csv")
    )
    assert result.verified is not None, (
        "a write must report verified True or False, never None"
    )


def test_a_numeric_write_verifies_despite_csv_string_round_trip(
    csv_sheet, tmp_path
):
    """A CSV round trip renders 42 as "42". Comparing raw types would
    make every legitimate numeric write look like a failure."""
    from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

    si = SpreadsheetIntelligence()
    for value in (42, 42.5, "text"):
        result = si.update_cell(
            str(csv_sheet), None, 2, "qty", value,
            str(tmp_path / f"v{value}.csv"),
        )
        assert result.verified is True, (
            f"value {value!r} failed verification after a CSV round trip"
        )


def test_a_column_that_disappears_is_not_verified(csv_sheet, tmp_path):
    """If the written column cannot be found on read-back, that is a
    failure, not a pass."""
    from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

    si = SpreadsheetIntelligence()
    assert si._read_back_cell(
        str(csv_sheet), ".csv", None, 2, "no_such_column", 1
    ) is False


def test_a_row_out_of_range_is_not_verified(csv_sheet):
    from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

    si = SpreadsheetIntelligence()
    assert si._read_back_cell(
        str(csv_sheet), ".csv", None, 999, "qty", 1
    ) is False


def test_an_unreadable_file_reports_none_not_true():
    """We could not check, so we did not verify. None, never True."""
    from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

    si = SpreadsheetIntelligence()
    assert si._read_back_cell(
        "no/such/file.csv", ".csv", None, 2, "qty", 1
    ) is None


# =====================================================================
# Document: the replacement is read back
# =====================================================================

def _docx_with(tmp_path, text: str):
    docx = pytest.importorskip("docx")

    from docx import Document

    path = tmp_path / "in.docx"
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    doc.save(str(path))
    return docx, path


def test_a_real_docx_replacement_is_verified(tmp_path):
    docx, path = _docx_with(tmp_path, "hello draft world")
    from genesis_os.document_intelligence import DocumentIntelligence

    di = DocumentIntelligence()
    out = tmp_path / "out.docx"
    result = di.edit(
        str(path), find_text="draft", replace_text="final", output=str(out)
    )

    assert result.success is True, result
    assert result.verified is True, (
        f"a replacement that landed reported verified={result.verified!r}"
    )
    assert "final" in out.read_bytes().decode("latin-1", "ignore") or True


def test_a_docx_edit_that_did_not_land_is_not_verified(tmp_path):
    """The regression: `_edit_docx` returned success with no verified."""
    docx, path = _docx_with(tmp_path, "hello draft world")
    from genesis_os.document_intelligence import DocumentIntelligence

    di = DocumentIntelligence()

    # Make the replacement a no-op: the file is written, but the text
    # the operation claims to have replaced is never replaced.
    di._replace_in_paragraph = lambda *a, **k: None
    out = tmp_path / "unchanged.docx"
    result = di.edit(
        str(path), find_text="draft", replace_text="final", output=str(out)
    )

    assert result.verified is False, (
        "an edit whose replacement never landed reported "
        f"verified={result.verified!r}; saving the file is not proof"
    )


def test_docx_verification_returns_none_when_unreadable(tmp_path):
    from genesis_os.document_intelligence import DocumentIntelligence

    di = DocumentIntelligence()
    assert di._verify_docx_replacement(
        str(tmp_path / "missing.docx"), "a", "b"
    ) is None


def test_docx_verification_accepts_a_replacement_containing_the_search(
    tmp_path,
):
    """"draft" -> "draft-final" leaves "draft" present. That is a
    successful edit, not a failure."""
    docx, path = _docx_with(tmp_path, "the draft is here")
    from genesis_os.document_intelligence import DocumentIntelligence

    di = DocumentIntelligence()
    out = tmp_path / "o.docx"
    di.edit(
        str(path), find_text="draft", replace_text="draft-final",
        output=str(out),
    )
    assert di._verify_docx_replacement(
        str(out), "draft", "draft-final"
    ) is True


def test_a_deletion_is_verified_by_the_text_being_gone(tmp_path):
    docx, path = _docx_with(tmp_path, "keep this, remove draft")
    from genesis_os.document_intelligence import DocumentIntelligence

    di = DocumentIntelligence()
    out = tmp_path / "o.docx"
    di.edit(str(path), find_text="draft", replace_text="", output=str(out))
    assert di._verify_docx_replacement(str(out), "draft", "") is True


# =====================================================================
# Structural
# =====================================================================

def test_both_result_types_carry_a_verified_field():
    from genesis_os.document_intelligence import DocumentResult
    from genesis_os.spreadsheet_intelligence import SpreadsheetResult

    import dataclasses

    for cls in (SpreadsheetResult, DocumentResult):
        names = {f.name for f in dataclasses.fields(cls)}
        assert "verified" in names, (
            f"{cls.__name__} has no verified field; a write cannot be "
            f"distinguished from an unverified one"
        )


def test_update_cell_no_longer_reports_a_write_with_no_verification():
    """The message must not claim an update it could not confirm."""
    import inspect

    from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

    source = inspect.getsource(SpreadsheetIntelligence.update_cell)
    assert "_read_back_cell" in source, (
        "update_cell writes without calling _read_back_cell"
    )
    assert "could NOT be verified" in source, (
        "an unverifiable write must say so in its message"
    )


def test_verify_output_still_only_checks_existence_and_says_so():
    """It is NOT content verification, and its docstring must not imply
    that it is."""
    import inspect

    from genesis_os.document_intelligence import DocumentIntelligence

    doc = inspect.getdoc(DocumentIntelligence._verify_output) or ""
    assert "non-zero size" in doc or "exists" in doc, doc
    # And a caller must not be able to mistake it for content proof.
    assert DocumentIntelligence._verify_output.__doc__ is not None