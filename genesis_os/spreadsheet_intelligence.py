"""
Level 3 Spreadsheet Intelligence Service

Inspects actual spreadsheet structure rather than assuming fixed column names.
Genesis must discover headers, infer data types, and adapt calculations dynamically.
"""

from __future__ import annotations

import csv
import os
import re
import ast
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.utils import get_column_letter

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


class SpreadsheetFormat(Enum):
    """Supported spreadsheet formats."""

    CSV = "csv"
    XLSX = "xlsx"


@dataclass(frozen=True)
class SheetInfo:
    """Inspection result for a single worksheet."""

    name: str
    headers: list[str]
    row_count: int
    column_count: int
    sample_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class WorkbookInfo:
    """Full inspection result for a workbook."""

    path: str
    format: SpreadsheetFormat
    sheets: list[SheetInfo]
    created: Optional[datetime]
    modified: Optional[datetime]
    size: int


@dataclass(frozen=True)
class SpreadsheetResult:
    """Standard result contract for spreadsheet operations."""

    success: bool
    operation: str
    path: Optional[str]
    message: str
    data: Any
    error: Optional[str]


class SpreadsheetIntelligence:
    """
    Main spreadsheet intelligence service.

    Inspects actual structure rather than assuming fixed column names.
    Supports CSV (always) and XLSX (when openpyxl is installed).
    """

    def __init__(self) -> None:
        """Initialize the service."""
        if not HAS_OPENPYXL:
            print("[SpreadsheetIntelligence] openpyxl not installed; XLSX support disabled")

    def inspect(self, path: str) -> SpreadsheetResult:
        """Inspect an entire workbook, returning headers, row counts, and samples for every sheet."""
        try:
            if not os.path.exists(path):
                return SpreadsheetResult(False, "inspect", None, f"File not found: {path}", None, "FileNotFoundError")

            ext = os.path.splitext(path)[1].lower()
            stat = os.stat(path)
            created = datetime.fromtimestamp(stat.st_ctime)
            modified = datetime.fromtimestamp(stat.st_mtime)

            if ext == ".csv":
                fmt = SpreadsheetFormat.CSV
                headers, rows = self._read_csv(path)
                sample = rows[:5] if rows else []
                sheet = SheetInfo(
                    name=os.path.splitext(os.path.basename(path))[0],
                    headers=headers,
                    row_count=len(rows),
                    column_count=len(headers),
                    sample_rows=sample,
                )
                info = WorkbookInfo(path=path, format=fmt, sheets=[sheet], created=created, modified=modified, size=stat.st_size)
                return SpreadsheetResult(True, "inspect", path, "Workbook inspected", info, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "inspect", None, "openpyxl not installed; cannot read xlsx", None, "ImportError")
                sheets = self._read_xlsx(path)
                info = WorkbookInfo(path=path, format=SpreadsheetFormat.XLSX, sheets=sheets, created=created, modified=modified, size=stat.st_size)
                return SpreadsheetResult(True, "inspect", path, "Workbook inspected", info, None)

            return SpreadsheetResult(False, "inspect", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "inspect", None, "Inspection failed", None, str(e))

    def inspect_sheet(self, path: str, sheet_name: str) -> SpreadsheetResult:
        """Inspect a single worksheet by name."""
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                sheet = SheetInfo(
                    name=os.path.splitext(os.path.basename(path))[0],
                    headers=headers,
                    row_count=len(rows),
                    column_count=len(headers),
                    sample_rows=rows[:5],
                )
                return SpreadsheetResult(True, "inspect_sheet", path, "Sheet inspected", sheet, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "inspect_sheet", None, "openpyxl not installed", None, "ImportError")
                sheets = self._read_xlsx(path)
                for s in sheets:
                    if s.name == sheet_name:
                        return SpreadsheetResult(True, "inspect_sheet", path, "Sheet inspected", s, None)
                return SpreadsheetResult(False, "inspect_sheet", path, f"Sheet '{sheet_name}' not found", None, "SheetNotFound")

            return SpreadsheetResult(False, "inspect_sheet", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "inspect_sheet", None, "Sheet inspection failed", None, str(e))

    def _require_inspection(self, path: str, sheet_name: str | None = None) -> Optional[SpreadsheetResult]:
        result = self.inspect_sheet(path, sheet_name) if sheet_name else self.inspect(path)
        return None if result.success else result

    def read(self, path: str, sheet_name: str | None = None, cell_range: str | None = None) -> SpreadsheetResult:
        """Read raw data from a sheet. Returns headers and rows as lists."""
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                return SpreadsheetResult(True, "read", path, "CSV read", {"headers": headers, "rows": rows}, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "read", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path, read_only=True, data_only=True)
                if sheet_name:
                    if sheet_name not in wb.sheetnames:
                        wb.close()
                        return SpreadsheetResult(False, "read", path, f"Sheet '{sheet_name}' not found", None, "SheetNotFound")
                    ws = wb[sheet_name]
                else:
                    ws = wb.active
                rows_data = list(ws.iter_rows(values_only=True))
                wb.close()
                if not rows_data:
                    return SpreadsheetResult(True, "read", path, "Sheet is empty", {"headers": [], "rows": []}, None)
                headers = [str(h) if h is not None else "" for h in rows_data[0]]
                rows = [
                    {headers[i]: (row[i] if i < len(row) else None) for i in range(len(headers))}
                    for row in rows_data[1:]
                ]
                return SpreadsheetResult(True, "read", path, "XLSX read", {"headers": headers, "rows": rows}, None)

            return SpreadsheetResult(False, "read", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "read", None, "Read failed", None, str(e))

    def read_as_dicts(self, path: str, sheet_name: str | None = None) -> SpreadsheetResult:
        """Read data as a list of dicts keyed by header names."""
        result = self.read(path, sheet_name)
        if not result.success:
            return result
        if not isinstance(result.data, dict):
            return SpreadsheetResult(False, "read_as_dicts", path, "Read returned no row payload", None, "InvalidPayload")
        headers = result.data.get("headers", [])
        rows = result.data.get("rows", [])
        normalized = []
        for row in rows:
            if isinstance(row, dict):
                normalized.append(row)
            elif isinstance(row, list):
                normalized.append({
                    headers[index] if index < len(headers) else f"column_{index}": value
                    for index, value in enumerate(row)
                })
        return SpreadsheetResult(True, "read_as_dicts", path, "Read as dicts", normalized, None)

    def sort(
        self,
        path: str,
        column: str,
        descending: bool = False,
        output: str | None = None,
        sheet_name: str | None = None,
    ) -> SpreadsheetResult:
        """Sort rows by a column and write to output (defaults to a sibling '<name>_sorted.<ext>' file; the original is never overwritten)."""
        try:
            inspection_error = self._require_inspection(path, sheet_name)
            if inspection_error is not None:
                return inspection_error
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                if column not in headers:
                    return SpreadsheetResult(False, "sort", path, f"Column '{column}' not found", None, "ColumnNotFound")
                idx = headers.index(column)
                rows.sort(key=lambda r: self._natural_sort_key(r[idx] if idx < len(r) else ""), reverse=descending)
                dest = self._resolve_output(path, output, "sorted")
                self._write_csv(dest, headers, rows)
                return SpreadsheetResult(
                    True,
                    "sort",
                    dest,
                    f"Sorted by '{column}' {'desc' if descending else 'asc'}",
                    {
                        "output": dest,
                        "column": column,
                        "descending": descending,
                    },
                    None,
                )

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "sort", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path)
                ws = wb[sheet_name] if sheet_name else wb.active
                rows_data = list(ws.iter_rows(values_only=True))
                if not rows_data:
                    wb.close()
                    return SpreadsheetResult(True, "sort", path, "Sheet is empty", None, None)
                headers_row = list(rows_data[0])
                if column not in headers_row:
                    wb.close()
                    return SpreadsheetResult(False, "sort", path, f"Column '{column}' not found", None, "ColumnNotFound")
                col_idx = headers_row.index(column)
                data_rows = list(rows_data[1:])
                data_rows.sort(key=lambda r: self._natural_sort_key(r[col_idx] if col_idx < len(r) else ""), reverse=descending)
                for row_idx, row in enumerate(data_rows, start=2):
                    for col_idx_c, val in enumerate(row, start=1):
                        ws.cell(row=row_idx, column=col_idx_c, value=val)
                dest = self._resolve_output(path, output, "sorted")
                wb.save(dest)
                wb.close()
                return SpreadsheetResult(
                    True,
                    "sort",
                    dest,
                    f"Sorted by '{column}' {'desc' if descending else 'asc'}",
                    {
                        "output": dest,
                        "column": column,
                        "descending": descending,
                    },
                    None,
                )

            return SpreadsheetResult(False, "sort", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "sort", None, "Sort failed", None, str(e))

    def filter_rows(
        self,
        path: str,
        sheet_name: str | None,
        column: str,
        condition: str,
        value: Any,
        output: str | None = None,
    ) -> SpreadsheetResult:
        """
        Filter rows where column meets condition.
        Supported conditions: eq, ne, gt, lt, gte, lte, contains, startswith, endswith.
        """
        try:
            inspection_error = self._require_inspection(path, sheet_name)
            if inspection_error is not None:
                return inspection_error
            ext = os.path.splitext(path)[1].lower()
            ops: dict[str, Callable[[Any, Any], bool]] = {
                "eq": lambda a, b: a == b,
                "ne": lambda a, b: a != b,
                "gt": lambda a, b: float(a) > float(b),
                "lt": lambda a, b: float(a) < float(b),
                "gte": lambda a, b: float(a) >= float(b),
                "lte": lambda a, b: float(a) <= float(b),
                "contains": lambda a, b: str(b).lower() in str(a).lower(),
                "startswith": lambda a, b: str(a).lower().startswith(str(b).lower()),
                "endswith": lambda a, b: str(a).lower().endswith(str(b).lower()),
            }
            condition_aliases = {
                "equals": "eq",
                "equal": "eq",
                "not_equals": "ne",
                "greater_than": "gt",
                "less_than": "lt",
                "greater_than_or_equal": "gte",
                "less_than_or_equal": "lte",
            }
            condition = condition_aliases.get(str(condition).lower(), str(condition).lower())
            if condition not in ops:
                return SpreadsheetResult(False, "filter_rows", None, f"Unknown condition: {condition}", None, "InvalidCondition")
            op_func = ops[condition]
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                if column not in headers:
                    return SpreadsheetResult(False, "filter_rows", path, f"Column '{column}' not found", None, "ColumnNotFound")
                col_idx = headers.index(column)
                filtered = [r for r in rows if op_func(r[col_idx] if col_idx < len(r) else "", value)]
                dest = self._resolve_output(path, output, "filtered")
                self._write_csv(dest, headers, filtered)
                return SpreadsheetResult(True, "filter_rows", dest, f"Filtered {len(filtered)} rows", {"filtered_count": len(filtered), "kept_count": len(filtered), "source": path, "output": dest, "column": column, "condition": condition, "value": value}, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "filter_rows", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path)
                ws = wb[sheet_name] if sheet_name else wb.active
                rows_data = list(ws.iter_rows(values_only=True))
                if not rows_data:
                    wb.close()
                    return SpreadsheetResult(True, "filter_rows", path, "Sheet is empty", None, None)
                headers_row = list(rows_data[0])
                if column not in headers_row:
                    wb.close()
                    return SpreadsheetResult(False, "filter_rows", path, f"Column '{column}' not found", None, "ColumnNotFound")
                col_idx = headers_row.index(column)
                filtered = [r for r in rows_data[1:] if op_func(r[col_idx] if col_idx < len(r) else "", value)]
                for row_idx, row in enumerate(filtered, start=2):
                    for c_idx, val in enumerate(row, start=1):
                        ws.cell(row=row_idx, column=c_idx, value=val)
                ws.delete_rows(len(filtered) + 2, ws.max_row)
                dest = self._resolve_output(path, output, "filtered")
                wb.save(dest)
                wb.close()
                return SpreadsheetResult(True, "filter_rows", dest, f"Filtered {len(filtered)} rows", {"filtered_count": len(filtered), "kept_count": len(filtered), "source": path, "output": dest, "column": column, "condition": condition, "value": value}, None)

            return SpreadsheetResult(False, "filter_rows", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "filter_rows", None, "Filter failed", None, str(e))

    def calculate(
        self,
        path: str,
        sheet_name: str | None,
        formula_column: str,
        formula_template: str,
        output: str | None = None,
    ) -> SpreadsheetResult:
        """
        Add a calculated column using a Python format template.
        Template can reference any existing header via {HeaderName}.
        Example: formula_template="{Marks}/{Total}*100" or formula_template="{Marks}/{Total}*100:.2f}"

        If the formatted result looks like a math expression (contains only
        digits, operators, parentheses, dots, and whitespace), it is
        evaluated to produce a numeric result.
        """
        try:
            inspection_error = self._require_inspection(path, sheet_name)
            if inspection_error is not None:
                return inspection_error
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                new_headers = list(headers) + [formula_column]
                new_rows = []
                for row in rows:
                    try:
                        values = {}
                        for i, h in enumerate(headers):
                            v = row[i] if i < len(row) else 0
                            try:
                                values[h] = float(v)
                            except (ValueError, TypeError):
                                values[h] = 0.0
                        result_val = formula_template.format(**values)
                        # Attempt numeric evaluation of the result
                        result_val = self._try_eval_numeric(result_val)
                        new_rows.append(list(row) + [result_val])
                    except Exception:
                        new_rows.append(list(row) + [""])
                if not new_rows or not any(row[-1] not in ("", None) for row in new_rows):
                    return SpreadsheetResult(False, "calculate", path, "No calculated values were produced", None, "CalculationFailed")
                dest = self._resolve_output(path, output, "calculated")
                self._write_csv(dest, new_headers, new_rows)
                return SpreadsheetResult(
                    True,
                    "calculate",
                    dest,
                    f"Calculated column '{formula_column}' added",
                    {
                        "output": dest,
                        "calculated_column": formula_column,
                        "calculated_values": [row[-1] for row in new_rows],
                    },
                    None,
                )

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "calculate", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path)
                ws = wb[sheet_name] if sheet_name else wb.active
                rows_data = list(ws.iter_rows(values_only=True))
                if not rows_data:
                    wb.close()
                    return SpreadsheetResult(True, "calculate", path, "Sheet is empty", None, None)
                headers_row = [str(h) if h is not None else "" for h in rows_data[0]]
                new_col = ws.max_column + 1
                calculated_values = []
                ws.cell(row=1, column=new_col, value=formula_column)
                for row_idx, row in enumerate(rows_data[1:], start=2):
                    values = {}
                    for i, h in enumerate(headers_row):
                        val = row[i] if i < len(row) else 0
                        try:
                            values[h] = float(val) if val is not None else 0.0
                        except (ValueError, TypeError):
                            values[h] = 0.0
                    try:
                        result_val = formula_template.format(**values)
                        result_val = self._try_eval_numeric(result_val)
                        ws.cell(row=row_idx, column=new_col, value=result_val)
                        calculated_values.append(result_val)
                    except Exception:
                        ws.cell(row=row_idx, column=new_col, value="")
                        calculated_values.append("")
                if not calculated_values or not any(value not in ("", None) for value in calculated_values):
                    wb.close()
                    return SpreadsheetResult(False, "calculate", path, "No calculated values were produced", None, "CalculationFailed")
                dest = self._resolve_output(path, output, "calculated")
                wb.save(dest)
                wb.close()
                return SpreadsheetResult(
                    True,
                    "calculate",
                    dest,
                    f"Calculated column '{formula_column}' added",
                    {
                        "output": dest,
                        "calculated_column": formula_column,
                        "calculated_values": calculated_values,
                    },
                    None,
                )

            return SpreadsheetResult(False, "calculate", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "calculate", None, "Calculate failed", None, str(e))

    def rank(
        self,
        path: str,
        sheet_name: str | None,
        rank_column: str,
        descending: bool = True,
        output: str | None = None,
    ) -> SpreadsheetResult:
        """Add a 'Rank' column based on values in rank_column. Descending=True means highest value gets rank 1."""
        try:
            inspection_error = self._require_inspection(path, sheet_name)
            if inspection_error is not None:
                return inspection_error
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                if rank_column not in headers:
                    return SpreadsheetResult(False, "rank", path, f"Column '{rank_column}' not found", None, "ColumnNotFound")
                col_idx = headers.index(rank_column)
                indexed = list(enumerate(rows))
                indexed.sort(key=lambda x: self._natural_sort_key(x[1][col_idx] if col_idx < len(x[1]) else ""), reverse=descending)
                ranked = [""] * len(rows)
                for rank_val, (orig_idx, _) in enumerate(indexed, start=1):
                    ranked[orig_idx] = rank_val
                new_headers = list(headers) + ["Rank"]
                new_rows = [list(row) + [ranked[i]] for i, row in enumerate(rows)]
                dest = self._resolve_output(path, output, "ranked")
                self._write_csv(dest, new_headers, new_rows)
                return SpreadsheetResult(True, "rank", dest, f"Ranked by '{rank_column}'", {"output": dest, "rank_column": rank_column, "descending": descending, "row_count": len(new_rows)}, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "rank", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path)
                ws = wb[sheet_name] if sheet_name else wb.active
                rows_data = list(ws.iter_rows(values_only=True))
                if not rows_data:
                    wb.close()
                    return SpreadsheetResult(True, "rank", path, "Sheet is empty", None, None)
                headers_row = [str(h) if h is not None else "" for h in rows_data[0]]
                if rank_column not in headers_row:
                    wb.close()
                    return SpreadsheetResult(False, "rank", path, f"Column '{rank_column}' not found", None, "ColumnNotFound")
                col_idx = headers_row.index(rank_column)
                indexed = list(enumerate(list(rows_data[1:])))
                indexed.sort(key=lambda x: self._natural_sort_key(x[1][col_idx] if col_idx < len(x[1]) else ""), reverse=descending)
                rank_map = {}
                for rank_val, (orig_idx, _) in enumerate(indexed, start=1):
                    rank_map[orig_idx] = rank_val
                new_col = ws.max_column + 1
                ws.cell(row=1, column=new_col, value="Rank")
                for row_idx in range(2, len(rows_data) + 1):
                    ws.cell(row=row_idx, column=new_col, value=rank_map.get(row_idx - 2, ""))
                dest = self._resolve_output(path, output, "ranked")
                wb.save(dest)
                wb.close()
                return SpreadsheetResult(True, "rank", dest, f"Ranked by '{rank_column}'", {"output": dest, "rank_column": rank_column, "descending": descending, "row_count": len(rows_data) - 1}, None)

            return SpreadsheetResult(False, "rank", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "rank", None, "Rank failed", None, str(e))

    def group_by(
        self,
        path: str,
        sheet_name: str | None,
        column: str,
        agg_column: str,
        operation: str = "sum",
        output: str | None = None,
    ) -> SpreadsheetResult:
        """Group rows by column and aggregate agg_column. Operations: sum, avg, min, max, count."""
        try:
            inspection_error = self._require_inspection(path, sheet_name)
            if inspection_error is not None:
                return inspection_error
            agg_ops: dict[str, Callable[[list], Any]] = {
                "sum": sum,
                "avg": lambda x: sum(x) / len(x) if x else 0,
                "min": min,
                "max": max,
                "count": len,
            }
            if operation not in agg_ops:
                return SpreadsheetResult(False, "group_by", None, f"Unknown operation: {operation}", None, "InvalidOperation")

            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                if column not in headers:
                    return SpreadsheetResult(False, "group_by", path, f"Column '{column}' not found", None, "ColumnNotFound")
                if agg_column not in headers:
                    return SpreadsheetResult(False, "group_by", path, f"Column '{agg_column}' not found", None, "ColumnNotFound")
                group_idx = headers.index(column)
                agg_idx = headers.index(agg_column)
                groups: dict[Any, list] = {}
                for row in rows:
                    key = row[group_idx] if group_idx < len(row) else ""
                    val = row[agg_idx] if agg_idx < len(row) else 0
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        val = 0
                    groups.setdefault(key, []).append(val)
                result_rows = [[k, agg_ops[operation](v)] for k, v in groups.items()]
                result_headers = [column, f"{operation}({agg_column})"]
                dest = self._resolve_output(path, output, "grouped")
                self._write_csv(dest, result_headers, result_rows)
                return SpreadsheetResult(True, "group_by", dest, f"Grouped by '{column}', aggregated '{agg_column}'", {"output": dest, "groups": result_rows}, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "group_by", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path)
                ws = wb[sheet_name] if sheet_name else wb.active
                rows_data = list(ws.iter_rows(values_only=True))
                if not rows_data:
                    wb.close()
                    return SpreadsheetResult(True, "group_by", path, "Sheet is empty", None, None)
                headers_row = [str(h) if h is not None else "" for h in rows_data[0]]
                if column not in headers_row:
                    wb.close()
                    return SpreadsheetResult(False, "group_by", path, f"Column '{column}' not found", None, "ColumnNotFound")
                if agg_column not in headers_row:
                    wb.close()
                    return SpreadsheetResult(False, "group_by", path, f"Column '{agg_column}' not found", None, "ColumnNotFound")
                group_idx = headers_row.index(column)
                agg_idx = headers_row.index(agg_column)
                groups_map: dict[Any, list] = {}
                for row in rows_data[1:]:
                    key = row[group_idx] if group_idx < len(row) else ""
                    val = row[agg_idx] if agg_idx < len(row) else 0
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        val = 0
                    groups_map.setdefault(key, []).append(val)
                new_ws = wb.create_sheet(title="Grouped")
                new_ws.cell(row=1, column=1, value=column)
                new_ws.cell(row=1, column=2, value=f"{operation}({agg_column})")
                for r_idx, (k, v) in enumerate(groups_map.items(), start=2):
                    new_ws.cell(row=r_idx, column=1, value=k)
                    new_ws.cell(row=r_idx, column=2, value=agg_ops[operation](v))
                dest = self._resolve_output(path, output, "grouped")
                wb.save(dest)
                wb.close()
                return SpreadsheetResult(True, "group_by", dest, f"Grouped by '{column}', aggregated '{agg_column}'", {"output": dest, "groups": [{"key": key, "value": agg_ops[operation](values)} for key, values in groups_map.items()]}, None)

            return SpreadsheetResult(False, "group_by", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "group_by", None, "Group by failed", None, str(e))

    def aggregate(
        self,
        path: str,
        sheet_name: str | None,
        columns: list[str],
        operation: str = "sum",
        output: str | None = None,
    ) -> SpreadsheetResult:
        """Aggregate multiple columns across all rows. Operations: sum, avg, min, max, count."""
        try:
            inspection_error = self._require_inspection(path, sheet_name)
            if inspection_error is not None:
                return inspection_error
            agg_ops: dict[str, Callable[[list], Any]] = {
                "sum": sum,
                "avg": lambda x: sum(x) / len(x) if x else 0,
                "min": min,
                "max": max,
                "count": len,
            }
            if operation not in agg_ops:
                return SpreadsheetResult(False, "aggregate", None, f"Unknown operation: {operation}", None, "InvalidOperation")

            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                missing = [c for c in columns if c not in headers]
                if missing:
                    return SpreadsheetResult(False, "aggregate", path, f"Columns not found: {missing}", None, "ColumnNotFound")
                result = {}
                for col in columns:
                    col_idx = headers.index(col)
                    vals = []
                    for row in rows:
                        try:
                            vals.append(float(row[col_idx] if col_idx < len(row) else 0))
                        except (ValueError, TypeError):
                            vals.append(0)
                    result[f"{operation}({col})"] = agg_ops[operation](vals)
                dest = self._resolve_output(path, output, "aggregated")
                self._write_csv(dest, list(result.keys()), [list(result.values())])
                return SpreadsheetResult(
                    True,
                    "aggregate",
                    dest,
                    "Aggregated",
                    {
                        "output": dest,
                        "aggregates": result,
                        "results": result,
                    },
                    None,
                )

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "aggregate", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path)
                ws = wb[sheet_name] if sheet_name else wb.active
                rows_data = list(ws.iter_rows(values_only=True))
                if not rows_data:
                    wb.close()
                    return SpreadsheetResult(True, "aggregate", path, "Sheet is empty", None, None)
                headers_row = [str(h) if h is not None else "" for h in rows_data[0]]
                missing = [c for c in columns if c not in headers_row]
                if missing:
                    wb.close()
                    return SpreadsheetResult(False, "aggregate", path, f"Columns not found: {missing}", None, "ColumnNotFound")
                result = {}
                for col in columns:
                    col_idx = headers_row.index(col)
                    vals = []
                    for row in rows_data[1:]:
                        try:
                            vals.append(float(row[col_idx]) if col_idx < len(row) else 0)
                        except (ValueError, TypeError):
                            vals.append(0)
                    result[f"{operation}({col})"] = agg_ops[operation](vals)
                wb.close()
                dest = self._resolve_output(path, output, "aggregated")
                new_wb = Workbook()
                new_ws = new_wb.active
                new_ws.append(list(result.keys()))
                new_ws.append(list(result.values()))
                new_wb.save(dest)
                new_wb.close()
                return SpreadsheetResult(
                    True,
                    "aggregate",
                    dest,
                    "Aggregated",
                    {
                        "output": dest,
                        "aggregates": result,
                        "results": result,
                    },
                    None,
                )

            return SpreadsheetResult(False, "aggregate", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "aggregate", None, "Aggregate failed", None, str(e))

    def compare_sheets(
        self,
        path1: str,
        sheet1: str | None,
        path2: str,
        sheet2: str | None,
    ) -> SpreadsheetResult:
        """Compare two sheets row-by-row and return differences."""
        try:
            r1 = self.read(path1, sheet1)
            r2 = self.read(path2, sheet2)
            if not r1.success:
                return r1
            if not r2.success:
                return r2
            d1 = r1.data
            d2 = r2.data
            differences = []
            max_rows = max(len(d1["rows"]), len(d2["rows"]))
            for i in range(max_rows):
                row1 = d1["rows"][i] if i < len(d1["rows"]) else {}
                row2 = d2["rows"][i] if i < len(d2["rows"]) else {}
                all_keys = set(list(row1.keys()) + list(row2.keys()))
                for key in all_keys:
                    v1 = row1.get(key)
                    v2 = row2.get(key)
                    if v1 != v2:
                        differences.append({"row": i + 2, "column": key, "sheet1": v1, "sheet2": v2})
            summary = {
                "total_differences": len(differences),
                "differences": differences[:50],
                "headers1": d1["headers"],
                "headers2": d2["headers"],
                "row_count1": len(d1["rows"]),
                "row_count2": len(d2["rows"]),
            }
            return SpreadsheetResult(True, "compare_sheets", None, f"Found {len(differences)} differences", summary, None)
        except Exception as e:
            return SpreadsheetResult(False, "compare_sheets", None, "Comparison failed", None, str(e))

    def add_column(
        self,
        path: str,
        sheet_name: str | None,
        column_name: str,
        values: list[Any],
        output: str | None = None,
    ) -> SpreadsheetResult:
        """Add a new column with provided values (padded with empty if shorter than rows)."""
        try:
            inspection_error = self._require_inspection(path, sheet_name)
            if inspection_error is not None:
                return inspection_error
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                if column_name in headers:
                    return SpreadsheetResult(False, "add_column", path, f"Column '{column_name}' already exists", None, "ColumnExists")
                new_headers = list(headers) + [column_name]
                for i, row in enumerate(rows):
                    row.append(values[i] if i < len(values) else "")
                dest = self._resolve_output(path, output, "extended")
                self._write_csv(dest, new_headers, rows)
                return SpreadsheetResult(True, "add_column", dest, f"Column '{column_name}' added", {"output": dest, "column": column_name, "values": list(values), "row_count": len(rows)}, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "add_column", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path)
                ws = wb[sheet_name] if sheet_name else wb.active
                new_col = ws.max_column + 1
                ws.cell(row=1, column=new_col, value=column_name)
                for r_idx in range(2, ws.max_row + 1):
                    val = values[r_idx - 2] if r_idx - 2 < len(values) else ""
                    ws.cell(row=r_idx, column=new_col, value=val)
                dest = self._resolve_output(path, output, "extended")
                row_count = ws.max_row - 1
                wb.save(dest)
                wb.close()
                return SpreadsheetResult(True, "add_column", dest, f"Column '{column_name}' added", {"output": dest, "column": column_name, "values": list(values), "row_count": row_count}, None)

            return SpreadsheetResult(False, "add_column", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "add_column", None, "Add column failed", None, str(e))

    def update_cell(
        self,
        path: str,
        sheet_name: str | None,
        row: int,
        column: str,
        value: Any,
        output: str | None = None,
    ) -> SpreadsheetResult:
        """Update a single cell identified by row number (1-indexed, header row = 1) and column name."""
        try:
            inspection_error = self._require_inspection(path, sheet_name)
            if inspection_error is not None:
                return inspection_error
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                headers, rows = self._read_csv(path)
                if column not in headers:
                    return SpreadsheetResult(False, "update_cell", path, f"Column '{column}' not found", None, "ColumnNotFound")
                col_idx = headers.index(column)
                data_row_idx = row - 2
                if data_row_idx < 0 or data_row_idx >= len(rows):
                    return SpreadsheetResult(False, "update_cell", path, f"Row {row} out of range", None, "RowOutOfRange")
                rows[data_row_idx][col_idx] = value
                dest = self._resolve_output(path, output, "updated")
                self._write_csv(dest, headers, rows)
                return SpreadsheetResult(True, "update_cell", dest, f"Cell ({row}, '{column}') updated", {"output": dest, "row": row, "column": column, "value": value}, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "update_cell", None, "openpyxl not installed", None, "ImportError")
                wb = load_workbook(path)
                ws = wb[sheet_name] if sheet_name else wb.active
                headers_row = [str(c.value) if c.value is not None else "" for c in ws[1]]
                if column not in headers_row:
                    wb.close()
                    return SpreadsheetResult(False, "update_cell", path, f"Column '{column}' not found", None, "ColumnNotFound")
                col_idx = headers_row.index(column) + 1
                ws.cell(row=row, column=col_idx, value=value)
                dest = self._resolve_output(path, output, "updated")
                wb.save(dest)
                wb.close()
                return SpreadsheetResult(True, "update_cell", dest, f"Cell ({row}, '{column}') updated", {"output": dest, "row": row, "column": column, "value": value}, None)

            return SpreadsheetResult(False, "update_cell", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "update_cell", None, "Update cell failed", None, str(e))

    def create_from_dicts(
        self,
        path: str,
        data: list[dict[str, Any]],
        sheet_name: str = "Sheet1",
    ) -> SpreadsheetResult:
        """Create a new spreadsheet from a list of dicts. Keys become headers."""
        try:
            if not data:
                return SpreadsheetResult(False, "create_from_dicts", None, "No data provided", None, "NoData")

            ext = os.path.splitext(path)[1].lower()
            headers = list(data[0].keys())
            rows = [[d.get(h, "") for h in headers] for d in data]

            if ext == ".csv":
                self._write_csv(path, headers, rows)
                return SpreadsheetResult(True, "create_from_dicts", path, f"Created CSV with {len(rows)} rows", {"output": path, "headers": headers, "rows": rows}, None)

            if ext == ".xlsx":
                if not HAS_OPENPYXL:
                    return SpreadsheetResult(False, "create_from_dicts", None, "openpyxl not installed", None, "ImportError")
                wb = Workbook()
                ws = wb.active
                ws.title = sheet_name
                ws.append(headers)
                for row in rows:
                    ws.append(row)
                wb.save(path)
                wb.close()
                return SpreadsheetResult(True, "create_from_dicts", path, f"Created XLSX with {len(rows)} rows", {"output": path, "headers": headers, "rows": rows}, None)

            return SpreadsheetResult(False, "create_from_dicts", None, f"Unsupported format: {ext}", None, "UnsupportedFormat")
        except Exception as e:
            return SpreadsheetResult(False, "create_from_dicts", None, "Create failed", None, str(e))

    # ── Private helpers ────────────────────────────────────────────────

    @staticmethod
    def _default_output_path(path: str, suffix: str) -> str:
        """Derive a sibling output path so mutating operations never
        overwrite the source file by default.

        ``data.xlsx`` + ``"sorted"`` → ``data_sorted.xlsx`` (with a
        numeric counter if the sibling already exists).
        """
        base, ext = os.path.splitext(path)
        candidate = f"{base}_{suffix}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter = 1
        while True:
            numbered = f"{base}_{suffix}_{counter}{ext}"
            if not os.path.exists(numbered):
                return numbered
            counter += 1

    def _resolve_output(self, path: str, output: str | None, suffix: str) -> str:
        if output:
            from .file_intelligence.path_security import PathSecurity
            validation = PathSecurity.validate(output)
            if not validation["allowed"]:
                raise ValueError(validation["reason"])
            source = os.path.abspath(path)
            destination = os.path.abspath(validation["path"])
            if source == destination:
                raise ValueError("Output must not overwrite the source artifact.")
            return destination
        return self._default_output_path(path, suffix)

    def _read_csv(self, path: str) -> tuple[list[str], list[list[str]]]:
        """Read a CSV file and return (headers, rows as list of lists)."""
        headers: list[str] = []
        rows: list[list[str]] = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    headers = row
                else:
                    rows.append(row)
        return headers, rows

    def _read_xlsx(self, path: str) -> list[SheetInfo]:
        """Read an XLSX file and return a list of SheetInfo for each worksheet."""
        if not HAS_OPENPYXL:
            return []
        wb = load_workbook(path, read_only=True, data_only=True)
        sheets: list[SheetInfo] = []
        for name in wb.sheetnames:
            ws = wb[name]
            rows_data = list(ws.iter_rows(values_only=True))
            if not rows_data:
                sheets.append(SheetInfo(name=name, headers=[], row_count=0, column_count=0, sample_rows=[]))
                continue
            headers = [str(h) if h is not None else "" for h in rows_data[0]]
            total_rows = len(rows_data) - 1
            sample = [
                {headers[j]: (rows_data[i + 1][j] if j < len(rows_data[i + 1]) else None) for j in range(len(headers))}
                for i in range(min(5, total_rows))
            ]
            sheets.append(SheetInfo(name=name, headers=headers, row_count=total_rows, column_count=len(headers), sample_rows=sample))
        wb.close()
        return sheets

    def _write_csv(self, path: str, headers: list[str], rows: list[list[str]]) -> bool:
        """Write data to a CSV file."""
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            return True
        except Exception as error:
            raise OSError(f"CSV write failed: {error}") from error

    def _write_xlsx(self, path: str, sheets_data: dict[str, tuple[list[str], list[list[Any]]]]) -> bool:
        """Write data to an XLSX file. sheets_data maps sheet_name -> (headers, rows)."""
        if not HAS_OPENPYXL:
            return False
        try:
            wb = Workbook()
            first = True
            for name, (headers, rows) in sheets_data.items():
                if first:
                    ws = wb.active
                    ws.title = name
                    first = False
                else:
                    ws = wb.create_sheet(title=name)
                ws.append(headers)
                for row in rows:
                    ws.append(row)
            wb.save(path)
            wb.close()
            return True
        except Exception:
            return False

    @staticmethod
    def _try_eval_numeric(expr: str):
        cleaned = str(expr).strip()
        if not re.fullmatch(r'[\d\.\+\-\*\/\(\)\s]+', cleaned):
            return expr
        try:
            tree = ast.parse(cleaned, mode="eval")
            result = SpreadsheetIntelligence._evaluate_ast_node(tree.body)
            if isinstance(result, float) and result == int(result):
                return int(result)
            return round(result, 4)
        except Exception:
            return expr

    @staticmethod
    def _evaluate_ast_node(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp):
            value = SpreadsheetIntelligence._evaluate_ast_node(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +value
            if isinstance(node.op, ast.USub):
                return -value
        if isinstance(node, ast.BinOp):
            left = SpreadsheetIntelligence._evaluate_ast_node(node.left)
            right = SpreadsheetIntelligence._evaluate_ast_node(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                if abs(right) > 32:
                    raise ValueError("Exponent is too large.")
                return left ** right
        raise ValueError("Unsupported arithmetic expression.")

    @staticmethod
    def _validate_safe_ast(node):
        """Recursively verify an AST node contains only safe arithmetic operations."""
        allowed_types = (
            ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div,
            ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.FloorDiv
        )
        if not isinstance(node, allowed_types):
            raise ValueError(f"Unsafe AST node type: {type(node).__name__}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError(f"Unsafe AST Constant value type: {type(node.value).__name__}")
        for child in ast.iter_child_nodes(node):
            SpreadsheetIntelligence._validate_safe_ast(child)

    @staticmethod
    def _natural_sort_key(value: Any) -> tuple:
        """Generate a sort key that handles numeric strings naturally (e.g., 2 < 10)."""
        if value is None:
            return (0, "")
        s = str(value)
        parts: list[tuple[int, str]] = []
        for segment in re.split(r"(\d+)", s):
            if segment.isdigit():
                parts.append((1, int(segment)))
            else:
                parts.append((0, segment.lower()))
        return tuple(parts)
