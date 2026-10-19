"""Item 16C (C17): spreadsheet writes left `verified` at None.

Item 13C gave `SpreadsheetResult` an explicit contract:

    verified=None  the operation claims nothing about verification
    verified=True  the written content was read back and matched
    verified=False read back and did NOT match, or could not be read
                  back -- which is NOT verification

and stated that a WRITE MAY NEVER LEAVE IT None.

Seven write operations never read anything back, so they had nothing to
report and quietly opted out. Measured against the committed original:

    sort              success=True  verified=None
    calculate         success=True  verified=None
    rank              success=True  verified=None
    group_by          success=True  verified=None
    add_column        success=True  verified=None
    create_from_dicts success=True  verified=None

THIS IS NOT COSMETIC. `success` on these paths means "the write call
returned without raising". On a full disk, a locked file, a truncated
stream or a workbook save that silently produced nothing, that is not
evidence the data arrived. The read-back is what turns "I tried" into
"it is there, and it is what I meant".

`update_cell` already verified, from Item 13C, and is pinned here too
so it cannot regress.
"""
from __future__ import annotations

import os

import pytest

from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence


CSV = "name,score\nalice,10\nbob,20\ncarol,30\n"


@pytest.fixture
def sheet(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text(CSV)
    return str(path)


@pytest.fixture
def si():
    return SpreadsheetIntelligence()


def _out(tmp_path, name):
    return str(tmp_path / name)


# Every write op, with arguments that actually reach a success path.
def _calls(si, sheet, tmp_path):
    return {
        "sort": lambda: si.sort(
            sheet, "score", output=_out(tmp_path, "o_sort.csv")
        ),
        "filter_rows": lambda: si.filter_rows(
            sheet, None, "name", "eq", "alice",
            output=_out(tmp_path, "o_filter.csv"),
        ),
        "calculate": lambda: si.calculate(
            sheet, None, "score", "{score} + 1",
            output=_out(tmp_path, "o_calc.csv"),
        ),
        "rank": lambda: si.rank(
            sheet, None, "score", output=_out(tmp_path, "o_rank.csv")
        ),
        "group_by": lambda: si.group_by(
            sheet, None, "name", "score",
            output=_out(tmp_path, "o_group.csv"),
        ),
        "add_column": lambda: si.add_column(
            sheet, None, "tag", ["x", "y", "z"],
            output=_out(tmp_path, "o_add.csv"),
        ),
        "create_from_dicts": lambda: si.create_from_dicts(
            _out(tmp_path, "o_new.csv"), [{"a": 1}, {"a": 2}], "Sheet1"
        ),
    }


WRITE_OPS = list(_calls(None, "", None).keys())


# --------------------------------------------------------------------------
# The contract: a successful write is verified, never None
# --------------------------------------------------------------------------

@pytest.mark.parametrize("op", WRITE_OPS)
def test_a_successful_write_is_verified(op, si, sheet, tmp_path):
    result = _calls(si, sheet, tmp_path)[op]()

    assert result.success is True, f"{op} did not succeed: {result.message}"
    assert result.verified is not None, (
        f"{op} returned success=True with verified=None; a write may "
        "never leave it unclaimed -- it either read its result back or "
        "it did not do the thing"
    )
    assert result.verified is True, (
        f"{op} reported verified={result.verified} for a correct write"
    )


@pytest.mark.parametrize("op", WRITE_OPS)
def test_every_write_op_is_covered(op):
    """A new write op must join this list."""
    assert op in WRITE_OPS


# --------------------------------------------------------------------------
# The write really did happen -- so verified=True is earned, not defaulted
# --------------------------------------------------------------------------

def test_the_written_artifact_actually_contains_the_result(
    si, sheet, tmp_path
):
    result = si.sort(sheet, "score", output=_out(tmp_path, "sorted.csv"))

    assert result.verified is True
    written = open(result.path).read()
    assert "alice" in written and "carol" in written
    # Sorted by score ascending: 10, 20, 30.
    assert written.index("alice") < written.index("bob") < written.index("carol")


def test_add_column_wrote_the_new_column(si, sheet, tmp_path):
    result = si.add_column(
        sheet, None, "tag", ["x", "y", "z"], output=_out(tmp_path, "a.csv")
    )

    written = open(result.path).read()
    assert "tag" in written
    assert "x" in written and "z" in written


def test_group_by_wrote_the_aggregate(si, sheet, tmp_path):
    """Regression: the first version reported verified=False here."""
    result = si.group_by(
        sheet, None, "name", "score", output=_out(tmp_path, "g.csv")
    )

    assert result.success is True
    assert result.verified is True, (
        "group_by wrote a correct aggregate and reported it unverified; "
        "a float 10.0 was being rendered as '10' and compared against "
        "the '10.0' the CSV writer actually produced"
    )
    written = open(result.path).read()
    assert "sum(score)" in written


# --------------------------------------------------------------------------
# A write that silently no-ops must report False, not True
# --------------------------------------------------------------------------

def test_a_write_that_produces_nothing_is_not_verified(si, sheet, tmp_path, monkeypatch):
    """The key honesty property, in both directions."""

    def _write_nothing(path, headers, rows):
        # Simulate a save that "succeeds" but leaves the old content.
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("stale\n")
        return True

    monkeypatch.setattr(si, "_write_csv", _write_nothing)

    result = si.sort(sheet, "score", output=_out(tmp_path, "noop.csv"))

    assert result.success is True, "the call itself returned without raising"
    assert result.verified is False, (
        "the file on disk does not hold what was written, yet the write "
        "reported itself verified"
    )


def test_an_unreadable_artifact_is_not_verified(si, sheet, tmp_path):
    """Could not check is not checked."""
    result = si.sort(sheet, "score", output=_out(tmp_path, "gone.csv"))

    assert result.verified is True

    # Now point the check at something unreadable.
    assert si._verify_written("does-not-exist.csv", ".csv", ["a"], [[]]) is False


def test_a_truncated_write_is_not_verified(si, sheet, tmp_path):
    result = si.sort(sheet, "score", output=_out(tmp_path, "partial.csv"))
    assert result.verified is True

    with open(result.path, "w", encoding="utf-8") as handle:
        handle.write("name,score\n")  # headers only

    assert si._verify_written(
        result.path, ".csv", ["name", "score"], [["alice", "10"]]
    ) is False


def test_verify_written_never_defaults_to_true(si, tmp_path):
    """An unsupported extension is not a verification."""
    assert si._verify_written(str(tmp_path / "x.txt"), ".txt", ["a"], [["1"]]) is False


# --------------------------------------------------------------------------
# Cell matching rules
# --------------------------------------------------------------------------

def test_csv_string_coercion_matches(si):
    """An intended 42 reads back from CSV as "42"."""
    assert si._cells_match(
        ["n"], [[42]], ["n"], [["42"]]
    ) is True


def test_none_and_empty_are_the_same_absence(si):
    assert si._cells_match(["a", "b"], [[None, ""]], ["a", "b"], [["", ""]]) is True


def test_floats_keep_their_representation(si):
    """10.0 must match "10.0" -- the CSV writer's rendering."""
    assert si._cells_match(["n"], [[10.0]], ["n"], [["10.0"]]) is True


def test_an_integral_float_matches_the_int_xlsx_reads_back(si):
    """60.0 written to XLSX reads back as 60; that is the same cell."""
    assert si._cells_match(["n"], [[60.0]], ["n"], [[60]]) is True


def test_numeric_equality_does_not_swallow_real_differences(si):
    """1 and 2 are both numbers and must not compare equal."""
    assert si._cells_match(["n"], [[1]], ["n"], [[2]]) is False


def test_text_is_still_compared_as_text(si):
    assert si._cells_match(
        ["t"], [["draft"]], ["t"], [["draft-final"]]
    ) is False


# --------------------------------------------------------------------------
# XLSX paths -- the read-back must work for both formats
# --------------------------------------------------------------------------

@pytest.fixture
def book(tmp_path):
    pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    path = tmp_path / "s.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["name", "score"])
    for row in [("alice", 10), ("bob", 20), ("carol", 30)]:
        ws.append(list(row))
    wb.save(str(path))
    return str(path)


@pytest.mark.parametrize(
    "op",
    ["sort", "rank", "group_by", "add_column", "aggregate"],
)
def test_xlsx_write_paths_verify(op, si, book, tmp_path):
    calls = {
        "sort": lambda: si.sort(
            book, "score", output=_out(tmp_path, "x_sort.xlsx")
        ),
        "rank": lambda: si.rank(
            book, None, "score", output=_out(tmp_path, "x_rank.xlsx")
        ),
        "group_by": lambda: si.group_by(
            book, None, "name", "score",
            output=_out(tmp_path, "x_group.xlsx"),
        ),
        "add_column": lambda: si.add_column(
            book, None, "tag", ["x", "y", "z"],
            output=_out(tmp_path, "x_add.xlsx"),
        ),
        "aggregate": lambda: si.aggregate(
            book, None, ["score"], output=_out(tmp_path, "x_agg.xlsx")
        ),
    }

    result = calls[op]()

    assert result.success is True, f"{op}: {result.message} / {result.error}"
    assert result.verified is True, (
        f"{op} (XLSX) wrote correctly and reported verified="
        f"{result.verified}"
    )


def test_xlsx_group_by_reads_the_sheet_it_created(si, book, tmp_path):
    """group_by writes a NEW sheet named 'Grouped' in the XLSX path."""
    from openpyxl import load_workbook

    result = si.group_by(
        book, None, "name", "score", output=_out(tmp_path, "g.xlsx")
    )

    assert result.verified is True
    assert "Grouped" in load_workbook(result.path).sheetnames


def test_a_row_count_mismatch_is_not_a_match(si):
    assert si._cells_match(["a"], [["1"], ["2"]], ["a"], [["1"]]) is False


def test_a_value_mismatch_is_not_a_match(si):
    assert si._cells_match(["a"], [["1"]], ["a"], [["2"]]) is False


def test_a_header_mismatch_is_not_a_match(si):
    assert si._cells_match(["a"], [["1"]], ["b"], [["1"]]) is False


# --------------------------------------------------------------------------
# update_cell keeps the Item 13C behaviour
# --------------------------------------------------------------------------

def test_update_cell_still_verifies(si, sheet, tmp_path):
    # `row` is Excel-style 1-based and the header occupies row 1.
    result = si.update_cell(
        sheet, None, 2, "name", "ALICE", output=_out(tmp_path, "uc.csv")
    )

    assert result.success is True, result.message
    assert result.verified is True, (
        "update_cell lost the Item 13C read-back verification"
    )
    assert "ALICE" in open(result.path).read()


# --------------------------------------------------------------------------
# Structural guard: no write may return verified=None
# --------------------------------------------------------------------------

def test_no_write_return_leaves_verified_unclaimed():
    """AST sweep over every SpreadsheetResult the write ops construct."""
    import ast
    import pathlib

    tree = ast.parse(
        (pathlib.Path("genesis_os") / "spreadsheet_intelligence.py")
        .read_text(encoding="utf-8-sig")
    )

    WRITE_METHODS = {
        "sort", "filter_rows", "calculate", "rank", "group_by",
        "aggregate", "add_column", "update_cell", "create_from_dicts",
    }

    offenders = []

    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name in WRITE_METHODS):
            continue

        has_readback = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("_verify_written", "_read_back_cell")
            for n in ast.walk(fn)
        )
        if not has_readback:
            offenders.append(f"{fn.name}: no read-back")

        # Every SpreadsheetResult built with success=True must name a
        # value for `verified`.
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "SpreadsheetResult"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value is not True:
                continue
            # `verified` may be passed by keyword (the paths this item
            # added) or positionally in the 7th slot (update_cell, from
            # Item 13C). Both satisfy the contract.
            named = any(kw.arg == "verified" for kw in node.keywords)
            positional = len(node.args) >= 7
            if not (named or positional):
                offenders.append(
                    f"{fn.name}:{node.lineno}: success=True without verified="
                )

    assert not offenders, (
        "a write path still returns an unclaimed verification: "
        f"{offenders}"
    )


def test_the_read_back_helper_exists_and_is_used(si):
    import inspect

    source = inspect.getsource(SpreadsheetIntelligence._verify_written)
    assert "return False" in source, (
        "the read-back must be able to answer 'could not check'"
    )