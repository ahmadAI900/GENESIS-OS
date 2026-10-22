"""Genesis OS — deterministic spreadsheet operations."""
from __future__ import annotations
import csv
from pathlib import Path
from typing import Any
from .file_intelligence.path_security import PathSecurity


class SpreadsheetManager:
    VERSION = "3.8.0"

    def sort(self, path: Any, column: str, *, descending=True, output=None) -> dict:
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
        return {"success": dst.is_file(), "operation": "spreadsheet.sort", "source": str(src), "destination": str(dst),
                "column": column, "descending": descending, "rows": len(rows), "executed": True, "verified": dst.is_file()}

    # Macro-enabled workbook formats. openpyxl DROPS xl/vbaProject.bin
    # unless keep_vba=True is passed to load_workbook, so saving an .xlsm
    # without it silently strips every macro while reporting success.
    _MACRO_ENABLED_SUFFIXES = frozenset({".xlsm", ".xltm"})

    def _sort_xlsx(self, src, dst, column, descending):
        try:
            from openpyxl import load_workbook
        except ImportError:
            return {"success": False, "operation": "spreadsheet.sort", "error": "XLSX support requires openpyxl."}
        suffix = Path(src).suffix.lower()
        macro_enabled = suffix in self._MACRO_ENABLED_SUFFIXES
        wb = load_workbook(src, keep_vba=macro_enabled)
        # Item 24B (C30): every path out of the mutation block releases
        # the workbook -- the column-not-found return, the macro check,
        # the success return, and any exception unwinding through
        # sort()'s handler. openpyxl holds the source zip archive open,
        # and a leaked handle blocks renames/deletes of the source on
        # Windows for the life of the process.
        try:
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
        finally:
            wb.close()

        # Fail closed on macro loss rather than reporting a successful
        # sort of a workbook that has silently been stripped of its VBA.
        if macro_enabled and not self._vba_part_present(dst):
            return {
                "success": False,
                "operation": "spreadsheet.sort",
                "error": (
                    "Refusing to report success: this is a macro-enabled "
                    "workbook but the saved file no longer contains its "
                    "VBA project. Saving it would destroy the user's "
                    "macros. The source file was not modified."
                ),
                "executed": False,
                "verified": False,
                "macro_preserved": False,
                "destination": str(dst),
            }

        # Item 24B (C30): existence is not verification. Reopen the
        # saved workbook and compare its stored rows against the rows
        # this sort produced. A destination that still holds the
        # unsorted source, a corrupt blob, or a partial write all read
        # back differently -- or raise, which fails closed inside
        # _verify_sorted_workbook. The readback mirrors the sort's own
        # load contract (same keep_vba for the same suffix): a macro
        # artifact is verified by loading it exactly as it was written.
        if not self._verify_sorted_workbook(dst, data, macro_enabled):
            return {
                "success": False,
                "operation": "spreadsheet.sort",
                "source": str(src),
                "destination": str(dst),
                "column": column,
                "descending": descending,
                "rows": len(data),
                "error": "The saved workbook could not be read back with the sorted rows.",
                "executed": True,
                "verified": False,
            }

        return {"success": True, "operation": "spreadsheet.sort", "source": str(src), "destination": str(dst),
                "column": column, "descending": descending, "rows": len(data), "executed": True,
                "verified": True,
                "verification_type": "workbook_rows_readback",
                **({"macro_preserved": True} if macro_enabled else {})}

    @staticmethod
    def _verify_sorted_workbook(path, expected_rows, keep_vba=False) -> bool:
        """Reopen the saved workbook and compare its data rows against
        the rows the sort produced. Fails closed on any read error.

        ``keep_vba`` mirrors the flag the sort itself loaded with, so
        a macro-enabled artifact is reopened under the same contract
        it was written under (and a plain workbook never is).
        """
        try:
            from openpyxl import load_workbook

            wb = load_workbook(path, read_only=True, keep_vba=keep_vba)
            try:
                ws = wb.active
                rows = list(ws.iter_rows(min_row=2, values_only=True))
            finally:
                wb.close()
            return rows == list(expected_rows)
        except Exception:
            return False

    @staticmethod
    def _vba_part_present(path) -> bool:
        """Whether the saved workbook still carries xl/vbaProject.bin."""
        try:
            import zipfile

            with zipfile.ZipFile(path) as archive:
                return "xl/vbaProject.bin" in archive.namelist()
        except (OSError, zipfile.BadZipFile):
            return False

    @staticmethod
    def _value(value):
        try:
            return float(str(value).replace("%", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return str(value or "").casefold()
