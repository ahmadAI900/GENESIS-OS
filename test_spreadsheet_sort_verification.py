"""Item 24B (C30): _sort_xlsx leaked its workbook and verified by existence.

Two defects in SpreadsheetManager._sort_xlsx (spreadsheet_manager.py):

1. LEAK -- ``wb = load_workbook(...)`` was never closed on ANY path:
   the column-not-found return (65-66), the macro-loss fail-closed
   return (78-91), the success return (93-96), and every exception
   that propagated to sort()'s handler. openpyxl holds the source
   zip archive open (and read-only views when applicable), so a
   leaked workbook keeps file handles alive for the life of the
   process -- on Windows that blocks the source file from being
   renamed or deleted afterwards.

2. EXISTENCE-ONLY VERIFICATION -- the result ended with

       "verified": dst.is_file()

   the same existence oracle C29 removed from create_docx. is_file()
   is True for a destination that still holds the UNSORTED source
   (a save that never wrote), for a corrupt non-zip blob, and for a
   workbook whose rows are in any order at all.

The contract asserted here:

    real sort        -> success/executed/verified True, and the
                        ARTIFACT re-read from disk holds the sorted rows
    save that copies the unsorted source (or writes garbage)
                        -> success False, verified False, even though
                           dst.is_file() is True
    workbook opened on success / column-missing / save-raises paths
                        -> wb.close() called on every one of them

The readback verification compares the rows actually stored in the
saved workbook against the rows the sort produced (full row-sequence
equality), and fails closed on any exception while reopening --
existence is never the oracle.

Known scope line: _sort_csv's own "verified": dst.is_file() (line 48)
is untouched by this item (C30 names _sort_xlsx, lines 62-96).

5 of 6 tests fail before this item; the sixth (a faithful sort read
back independently) passes both ways and pins the honest path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from genesis_os.spreadsheet_manager import SpreadsheetManager

# Deliberately NOT sorted by score: descending sort must reorder it.
UNSORTED = [
    ("dave", 50),
    ("alice", 90),
    ("bob", 70),
]
SORTED_DESC = [
    ("alice", 90),
    ("bob", 70),
    ("dave", 50),
]
HEADERS = ("name", "score")


def _write_source(path: Path, rows=UNSORTED):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(list(HEADERS))
    for row in rows:
        ws.append(list(row))
    wb.save(path)


def _read_rows(path: Path):
    from openpyxl import load_workbook

    wb = load_workbook(path)
    try:
        ws = wb.active
        return list(ws.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()


def _spy_on_load_workbook(monkeypatch):
    """Wrap openpyxl.load_workbook to record every open and close.

    The product imports load_workbook LOCALLY inside _sort_xlsx, so
    the package attribute is what gets looked up at call time.
    """
    import openpyxl

    real = openpyxl.load_workbook
    opened = []
    closed = []

    def wrapper(*args, **kwargs):
        wb = real(*args, **kwargs)
        original_close = wb.close

        def close():
            closed.append(wb)
            return original_close()

        wb.close = close  # instance attr shadows the class method
        opened.append(wb)
        return wb

    monkeypatch.setattr(openpyxl, "load_workbook", wrapper)
    return opened, closed


# --------------------------------------------------------------------------
# Repro 1: a save that never wrote the sorted rows was "verified".
# --------------------------------------------------------------------------


def test_a_saved_workbook_that_keeps_the_old_order_is_not_verified(
    tmp_path, monkeypatch
):
    import openpyxl

    src = tmp_path / "in.xlsx"
    dst = tmp_path / "out.xlsx"
    _write_source(src)

    # Saboteur: Workbook.save writes the SOURCE bytes instead of the
    # sorted book -- dst exists, dst.is_file() is True, order unchanged.
    def fake_save(self, filename):
        Path(filename).write_bytes(src.read_bytes())

    monkeypatch.setattr(openpyxl.Workbook, "save", fake_save)

    result = SpreadsheetManager().sort(str(src), "score", output=str(dst))

    assert Path(dst).is_file(), (
        "the artifact exists -- which is exactly why existence was "
        "never a sufficient oracle"
    )
    assert result["success"] is False, result
    assert result["verified"] is False, result
    assert result["executed"] is True, result
    # Independent readback: the artifact still holds the OLD order.
    assert _read_rows(dst) == UNSORTED


def test_a_corrupt_saved_workbook_is_not_verified(tmp_path, monkeypatch):
    import openpyxl

    src = tmp_path / "in.xlsx"
    dst = tmp_path / "out.xlsx"
    _write_source(src)

    def fake_save(self, filename):
        Path(filename).write_bytes(b"this is not a zip package")

    monkeypatch.setattr(openpyxl.Workbook, "save", fake_save)

    result = SpreadsheetManager().sort(str(src), "score", output=str(dst))

    assert Path(dst).is_file(), "the corrupt blob is still a file"
    assert result["success"] is False, result
    assert result["verified"] is False, result


# --------------------------------------------------------------------------
# Repro 2: the workbook handle was never released.
# --------------------------------------------------------------------------


def test_the_workbook_is_closed_after_a_real_sort(tmp_path, monkeypatch):
    src = tmp_path / "in.xlsx"
    dst = tmp_path / "out.xlsx"
    _write_source(src)
    opened, closed = _spy_on_load_workbook(monkeypatch)

    result = SpreadsheetManager().sort(str(src), "score", output=str(dst))

    assert result["success"] is True, result
    assert opened, "the sort must have opened the workbook"
    assert len(closed) == len(opened), (
        f"leaked workbook handle(s): {len(opened)} opened, "
        f"{len(closed)} closed"
    )


def test_the_workbook_is_closed_when_the_column_is_missing(
    tmp_path, monkeypatch
):
    src = tmp_path / "in.xlsx"
    dst = tmp_path / "out.xlsx"
    _write_source(src)
    opened, closed = _spy_on_load_workbook(monkeypatch)

    result = SpreadsheetManager().sort(
        str(src), "nosuchcolumn", output=str(dst)
    )

    assert result["success"] is False, result
    assert opened, "the sort must have opened the workbook"
    assert len(closed) == len(opened), (
        f"leaked workbook handle(s): {len(opened)} opened, "
        f"{len(closed)} closed"
    )


def test_the_workbook_is_closed_when_save_raises(tmp_path, monkeypatch):
    import openpyxl

    src = tmp_path / "in.xlsx"
    dst = tmp_path / "out.xlsx"
    _write_source(src)
    opened, closed = _spy_on_load_workbook(monkeypatch)

    def fake_save(self, filename):
        raise RuntimeError("simulated disk full during save")

    monkeypatch.setattr(openpyxl.Workbook, "save", fake_save)

    result = SpreadsheetManager().sort(str(src), "score", output=str(dst))

    assert result["success"] is False, result
    assert "simulated disk full" in (result.get("error") or ""), result
    assert opened, "the sort must have opened the workbook"
    assert len(closed) == len(opened), (
        f"leaked workbook handle(s): {len(opened)} opened, "
        f"{len(closed)} closed"
    )


# --------------------------------------------------------------------------
# The honest path, pinned: a faithful sort reads back sorted.
# --------------------------------------------------------------------------


def test_a_real_sort_reads_back_the_sorted_rows(tmp_path):
    src = tmp_path / "in.xlsx"
    dst = tmp_path / "out.xlsx"
    _write_source(src)

    result = SpreadsheetManager().sort(str(src), "score", output=str(dst))

    assert result["success"] is True, result
    assert result["executed"] is True, result
    assert result["verified"] is True, result
    assert result.get("error") is None, result
    # Verified from the ARTIFACT, independently of the flag:
    assert _read_rows(dst) == SORTED_DESC
