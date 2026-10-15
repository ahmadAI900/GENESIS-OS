"""Genesis OS — deterministic spreadsheet operations."""
from __future__ import annotations
import csv
from pathlib import Path
from typing import Any
from .file_intelligence.path_security import PathSecurity


class SpreadsheetManager:
    VERSION = "3.8.0"

    def sort(self, path: Any, column: str, *, descending=True, output=None, confirmed=False) -> dict:
        v = PathSecurity.validate(path, require_existing=True, require_file=True)
        if not v["allowed"]:
            return {"success": False, "operation": "spreadsheet.sort", "error": v["reason"]}
        src = Path(v["path"])
        if output:
            output_validation = PathSecurity.validate(output)
            if not output_validation["allowed"]:
                return {"success": False, "operation": "spreadsheet.sort", "error": output_validation["reason"]}
            destination = Path(output_validation["path"])
        else:
            destination = src.with_name(f"{src.stem}_sorted{src.suffix}")
        if destination.resolve() == src.resolve():
            return {"success": False, "operation": "spreadsheet.sort", "error": "Output must not overwrite the source artifact."}
        try:
            if src.suffix.lower() == ".csv":
                return self._sort_csv(src, destination, column, descending)
            if src.suffix.lower() in {".xlsx", ".xlsm"}:
                return self._sort_xlsx(src, destination, column, descending)
            return {"success": False, "operation": "spreadsheet.sort", "error": "Only CSV/XLSX/XLSM sorting is currently supported."}
        except Exception as exc:
            return {"success": False, "operation": "spreadsheet.sort", "error": str(exc), "executed": False, "verified": False}

    def _sort_csv(self, src, dst, column, descending):
        with src.open("r", newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
            fieldnames = rows[0].keys() if rows else []
            fieldnames = list(fieldnames)
        if column not in fieldnames:
            return {"success": False, "operation": "spreadsheet.sort", "error": f"Column '{column}' was not found."}
        rows.sort(key=lambda r: self._value(r.get(column, "")), reverse=descending)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader(); writer.writerows(rows)
        return {"success": True, "operation": "spreadsheet.sort", "source": str(src), "destination": str(dst),
                "column": column, "descending": descending, "rows": len(rows), "executed": True, "verified": dst.is_file()}

    def _sort_xlsx(self, src, dst, column, descending):
        try:
            from openpyxl import load_workbook
        except ImportError:
            return {"success": False, "operation": "spreadsheet.sort", "error": "XLSX support requires openpyxl."}
        wb = load_workbook(src)
        ws = wb.active
        headers = [c.value for c in ws[1]]
        if column not in headers:
            return {"success": False, "operation": "spreadsheet.sort", "error": f"Column '{column}' was not found."}
        idx = headers.index(column) + 1
        data = list(ws.iter_rows(min_row=2, values_only=True))
        data.sort(key=lambda row: self._value(row[idx - 1]), reverse=descending)
        for r, values in enumerate(data, start=2):
            for c, value in enumerate(values, start=1):
                ws.cell(r, c).value = value
        wb.save(dst)
        return {"success": True, "operation": "spreadsheet.sort", "source": str(src), "destination": str(dst),
                "column": column, "descending": descending, "rows": len(data), "executed": True, "verified": dst.is_file()}

    @staticmethod
    def _value(value):
        try:
            return float(str(value).replace("%", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return str(value or "").casefold()
