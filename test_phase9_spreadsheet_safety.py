"""Phase 9 regression: mutating spreadsheet operations must never
destroy the original file by default, and xlsx read must work.

Covers two fixed defects:
1. ``dest = output or path`` — sort/filter/calculate/rank/group_by/
   add_column/update_cell overwrote the source file when no output
   path was given.
2. ``SpreadsheetIntelligence.read`` crashed on every .xlsx with
   ``TypeError: 'NoneType' object is not callable`` because the
   ``range`` parameter shadowed the builtin used at
   ``range(len(headers))``.
"""
import os

import pytest

from genesis_os.os_manager import OSManager
from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence
from genesis_os.verification_helpers import (
    verify_sheet_add_column,
    verify_sheet_update_cell,
    verify_sheet_create_from_dicts,
)

pytestmark = pytest.mark.skipif(
    pytest.importorskip("openpyxl", reason="openpyxl required") is None,
    reason="openpyxl required",
)


def _make_xlsx(path, rows=None):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "People"
    ws.append(["Name", "Age", "Score"])
    for row in rows or [["Alice", 30, 88], ["Bob", 25, 95], ["Carol", 40, 70]]:
        ws.append(row)
    wb.save(path)
    wb.close()
    return path


def _make_csv(path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("Name,Age,Score\nAlice,30,88\nBob,25,95\nCarol,40,70\n")
    return path


def _snapshot(path):
    with open(path, "rb") as f:
        return f.read()


def _assert_preserved(path, before):
    with open(path, "rb") as f:
        assert f.read() == before, "original file was modified"


class TestNoOverwriteByDefault:
    def test_sort_xlsx_preserves_original(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_xlsx(str(tmp_path / "data.xlsx"))
        before = _snapshot(src)
        result = si.sort(src, "Score", descending=True)
        assert result.success is True
        assert result.path != src
        assert result.path.endswith("_sorted.xlsx")
        assert os.path.exists(result.path)
        _assert_preserved(src, before)
        # Output really is sorted.
        check = si.read(result.path)
        assert check.success is True
        scores = [r["Score"] for r in check.data["rows"]]
        assert scores == sorted(scores, reverse=True)

    def test_filter_xlsx_preserves_original(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_xlsx(str(tmp_path / "data.xlsx"))
        before = _snapshot(src)
        result = si.filter_rows(src, None, "Score", "gt", 80)
        assert result.success is True
        assert result.path != src
        assert result.path.endswith("_filtered.xlsx")
        _assert_preserved(src, before)
        check = si.read(result.path)
        assert check.success is True
        assert all(r["Score"] > 80 for r in check.data["rows"])
        assert len(check.data["rows"]) == 2

    def test_calculate_xlsx_preserves_original(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_xlsx(str(tmp_path / "data.xlsx"))
        before = _snapshot(src)
        result = si.calculate(src, None, "Double", "{Score}*2")
        assert result.success is True
        assert result.path != src
        _assert_preserved(src, before)
        check = si.read(result.path)
        assert check.success is True
        assert "Double" in check.data["headers"]

    def test_rank_group_by_add_column_update_cell_preserve_original(self, tmp_path):
        si = SpreadsheetIntelligence()
        cases = [
            (lambda s: si.rank(s, None, "Score"), "_ranked"),
            (lambda s: si.group_by(s, None, "Age", "Score", "sum"), "_grouped"),
            (lambda s: si.add_column(s, None, "Note", ["a", "b", "c"]), "_extended"),
            (lambda s: si.update_cell(s, None, 2, "Age", 31), "_updated"),
        ]
        for i, (call, suffix) in enumerate(cases):
            src = _make_xlsx(str(tmp_path / f"case{i}.xlsx"))
            before = _snapshot(src)
            result = call(src)
            assert result.success is True, f"{suffix}: {result.error}"
            assert result.path != src
            assert result.path.endswith(f"{suffix}.xlsx"), result.path
            _assert_preserved(src, before)

    def test_sort_csv_preserves_original(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_csv(str(tmp_path / "data.csv"))
        before = _snapshot(src)
        result = si.sort(src, "Score", descending=True)
        assert result.success is True
        assert result.path != src
        assert result.path.endswith("_sorted.csv")
        _assert_preserved(src, before)

    def test_update_cell_csv_preserves_original(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_csv(str(tmp_path / "data.csv"))
        before = _snapshot(src)
        result = si.update_cell(src, None, 2, "Age", 31)
        assert result.success is True
        assert result.path != src
        _assert_preserved(src, before)
        check = si.read(result.path)
        assert check.success is True
        age_idx = check.data["headers"].index("Age")
        assert check.data["rows"][0][age_idx] == "31"

    def test_default_output_collision_numbered(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_xlsx(str(tmp_path / "data.xlsx"))
        before = _snapshot(src)
        first = si.sort(src, "Score")
        assert first.success is True
        second = si.sort(src, "Score")
        assert second.success is True
        assert second.path != first.path
        assert second.path.endswith("_sorted_1.xlsx")
        _assert_preserved(src, before)


class TestKnownLatentBugs:
    """Each test names one exact past defect so a reintroduction
    fails with a message pointing at the right cause."""

    def test_csv_sort_indexes_rows_as_lists_not_dicts(self, tmp_path):
        # Was: rows.sort(key=lambda r: ... r.get(idx, "")) crashed with
        # "'list' object has no attribute 'get'" because _read_csv
        # returns rows as lists, not dicts.
        si = SpreadsheetIntelligence()
        src = _make_csv(str(tmp_path / "data.csv"))
        result = si.sort(src, "Score", descending=True)
        assert result.success is True, (
            "CSV sort regressed to dict-style row access "
            f"(r.get on list rows): {result.error}"
        )
        check = si.read(result.path)
        assert check.success is True
        score_idx = check.data["headers"].index("Score")
        scores = [row[score_idx] for row in check.data["rows"]]
        assert scores == ["95", "88", "70"], (
            f"CSV rows not actually sorted desc by Score: {scores}"
        )

    def test_xlsx_update_cell_matches_header_values_not_cells(self, tmp_path):
        # Was: headers built as [str(h) ... for h in ws[1]] compared
        # Cell objects against the column name, so every call failed
        # with ColumnNotFound. Must use cell .value.
        si = SpreadsheetIntelligence()
        src = _make_xlsx(str(tmp_path / "data.xlsx"))
        before = _snapshot(src)
        result = si.update_cell(src, None, 2, "Age", 31)
        assert result.success is True, (
            "xlsx update_cell regressed to comparing Cell objects "
            f"instead of header values: {result.error}"
        )
        assert result.path != src
        _assert_preserved(src, before)
        check = si.read(result.path)
        assert check.success is True
        assert check.data["rows"][0]["Age"] == 31, (
            "cell (row 2, 'Age') was not actually updated to 31"
        )


class TestExplicitOutputStillWorks:
    def test_sort_xlsx_explicit_output(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_xlsx(str(tmp_path / "data.xlsx"))
        before = _snapshot(src)
        out = str(tmp_path / "custom_out.xlsx")
        result = si.sort(src, "Score", descending=True, output=out)
        assert result.success is True
        assert result.path == out
        assert os.path.exists(out)
        _assert_preserved(src, before)
        check = si.read(out)
        assert check.success is True
        scores = [r["Score"] for r in check.data["rows"]]
        assert scores == sorted(scores, reverse=True)

    def test_calculate_csv_explicit_output(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_csv(str(tmp_path / "data.csv"))
        before = _snapshot(src)
        out = str(tmp_path / "calc.csv")
        result = si.calculate(src, None, "Double", "{Score}*2", output=out)
        assert result.success is True
        assert result.path == out
        _assert_preserved(src, before)


class TestXlsxReadFixed:
    def test_read_xlsx_no_nonetype_crash(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_xlsx(str(tmp_path / "data.xlsx"))
        result = si.read(src)
        assert result.success is True, f"read failed: {result.error}"
        assert result.data["headers"] == ["Name", "Age", "Score"]
        assert len(result.data["rows"]) == 3
        assert result.data["rows"][0] == {"Name": "Alice", "Age": 30, "Score": 88}

    def test_read_as_dicts_xlsx(self, tmp_path):
        si = SpreadsheetIntelligence()
        src = _make_xlsx(str(tmp_path / "data.xlsx"))
        result = si.read_as_dicts(src, "People")
        assert result.success is True, f"read_as_dicts failed: {result.error}"
        assert len(result.data) == 3


class TestMutationReadbackVerification:
    def test_add_column_rejects_wrong_values(self, tmp_path):
        output = tmp_path / "wrong.csv"
        output.write_text("Name,Note\nAlice,unexpected\nBob,other\n", encoding="utf-8")

        result = verify_sheet_add_column(
            True,
            str(output),
            {"output": str(output), "column": "Note", "values": ["expected", "other"]},
        )

        assert result["verified"] is False

    def test_update_cell_rejects_wrong_value(self, tmp_path):
        output = tmp_path / "wrong.csv"
        output.write_text("Name,Age\nAlice,30\n", encoding="utf-8")

        result = verify_sheet_update_cell(
            True,
            str(output),
            {"output": str(output), "row": 2, "column": "Age", "value": 31},
        )

        assert result["verified"] is False

    def test_create_from_dicts_rejects_wrong_rows(self, tmp_path):
        output = tmp_path / "wrong.csv"
        output.write_text("Name,Age\nAlice,30\n", encoding="utf-8")

        result = verify_sheet_create_from_dicts(
            True,
            str(output),
            {
                "headers": ["Name", "Age"],
                "rows": [["Bob", 31]],
            },
        )

        assert result["verified"] is False

    def test_osmanager_filter_wrapper_reports_filter_operation(self, tmp_path):
        osm = OSManager.__new__(OSManager)
        osm.sheet_intel = SpreadsheetIntelligence()
        source = _make_csv(str(tmp_path / "filter.csv"))

        result = osm.sheet_filter(source, None, "Score", "gt", 80)

        assert result["operation"] == "spreadsheet.filter"
        assert result["success"] is True
        assert result["verified"] is True
        assert result["output_matches"] is True
