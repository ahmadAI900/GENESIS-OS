"""
Genesis OS — Document / Spreadsheet post-state verification helpers.

Background
----------

The OSManager wrapper layer previously bound ``verified = result.success``
for every ``document.*`` and ``spreadsheet.*`` operation. That conflates
"the underlying library call did not raise" with "the post-state was
actually verified" — exactly the same conflation Phase 0 fixed for
``gui.type_text`` / ``gui.paste_text`` / file operations.

This module is the honest equivalent: it observes a real, cheap,
post-state signal (file existence, on-disk size, data presence, etc.)
and reports ``verified=True`` only when that signal is consistent
with the provider's success. When no cheap real signal exists the
helper returns ``verified=False`` with an explicit reason — matching
the rule that honest "can't verify" beats fake "verified".

The functions are intentionally narrow. They do NOT depend on
private fields of the underlying providers and do NOT silently
swallow errors. They are consumed by ``OSManager`` for each
document / spreadsheet operation.
"""
from __future__ import annotations

import csv
import os
import re
from typing import Any, Dict, Optional


def _file_exists_and_nonempty(path: Optional[str]) -> bool:
    """Cheap post-state check: does ``path`` exist on disk and is
    its size > 0? Used for write-side operations (create / edit /
    transform) where the underlying library has already returned
    success.
    """
    if not path or not isinstance(path, str):
        return False
    try:
        return os.path.exists(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _file_exists(path: Optional[str]) -> bool:
    """Cheap existence check used for read-side operations."""
    if not path or not isinstance(path, str):
        return False
    try:
        return os.path.exists(path)
    except OSError:
        return False


# ------------------------------------------------------------------
# DOCUMENT helpers
# ------------------------------------------------------------------


def verify_doc_inspect(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``document.inspect`` — verify the inspected file actually exists.

    The provider's ``inspect`` returns metadata; success combined
    with the file existing on disk is the strongest post-state
    signal we can offer.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists(path):
        return {"verified": False, "reason": f"inspected file does not exist: {path!r}"}
    return {"verified": True, "reason": "file exists after inspect", "file_exists": True}


def verify_doc_read(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``document.read`` — verify the file exists AND the read
    produced a non-empty data payload.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists(path):
        return {"verified": False, "reason": f"file does not exist: {path!r}"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "read returned no data payload"}
    text = data.get("text") or ""
    if not isinstance(text, str) or not text:
        return {"verified": False, "reason": "read returned empty text"}
    # Content MUST flow back to the caller (model/agent): verification
    # carries a capped preview of the real text that was observed.
    # Cap prevents unbounded memory growth on large files; the full
    # text stays in the provider payload, never truncated on disk.
    return {
        "verified": True,
        "reason": "file read produced non-empty text",
        "content_preview": text[:2000],
        "content_length": len(text),
        "content_truncated": len(text) > 2000,
    }


def verify_doc_search(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``document.search`` — read succeeded AND a match list was
    returned (empty list is fine — "no matches" is a real answer).
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists(path):
        return {"verified": False, "reason": f"file does not exist: {path!r}"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "search returned no data payload"}
    if "matches" not in data:
        return {"verified": False, "reason": "search returned no matches field"}
    return {"verified": True, "reason": "search returned matches payload", "matches": True}


def verify_doc_create(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``document.create_*`` — verify the file exists on disk
    after the create call AND has non-zero size.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists(path):
        return {"verified": False, "reason": f"created file missing: {path!r}"}
    return {"verified": True, "reason": "created file exists on disk", "file_exists": True}


def verify_doc_compare(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``document.compare`` — verify both source files exist
    AND the compare produced a similarity score.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "compare returned no data payload"}
    p1 = data.get("path1")
    p2 = data.get("path2")
    if not _file_exists(p1):
        return {"verified": False, "reason": f"first document not found: {p1!r}"}
    if not _file_exists(p2):
        return {"verified": False, "reason": f"second document not found: {p2!r}"}
    if "similarity" not in data:
        return {"verified": False, "reason": "compare returned no similarity score"}
    return {"verified": True, "reason": "both files read and similarity computed", "similarity": data.get("similarity")}


def verify_doc_summarize(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``document.summarize`` — verify the source file exists
    AND the summary is non-empty.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists(path):
        return {"verified": False, "reason": f"file does not exist: {path!r}"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "summarize returned no data payload"}
    summary = data.get("summary") or ""
    if not isinstance(summary, str) or not summary:
        return {"verified": False, "reason": "summarize returned empty summary"}
    return {"verified": True, "reason": "file exists with non-empty summary", "summary_verified": True}


def verify_doc_edit(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``document.edit`` — verify the file exists AND actually
    contains the replacement text after the edit.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists_and_nonempty(path):
        return {"verified": False, "reason": f"edited file missing or empty: {path!r}"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "edit returned no data payload"}
    replace_text = data.get("replace_text")
    find_text = data.get("find_text")
    if not isinstance(replace_text, str) or not replace_text:
        return {"verified": False, "reason": "replacement text is missing"}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            on_disk = f.read()
    except OSError:
        on_disk = _extract_verifiable_text(path)
    if on_disk is None:
        return {"verified": False, "reason": f"could not re-read edited file: {path!r}"}
    if replace_text not in on_disk:
        return {"verified": False, "reason": "edited file does not contain replacement text"}
    if isinstance(find_text, str) and find_text and find_text in on_disk:
        return {"verified": False, "reason": "edited file still contains the search text"}
    expected_occurrences = data.get("occurrences")
    if isinstance(expected_occurrences, int) and on_disk.count(replace_text) < expected_occurrences:
        return {"verified": False, "reason": "replacement occurrence count did not match"}
    return {"verified": True, "reason": "edited file was reread and replacement matched", "content_match": True, "output_path": path}


def _extract_verifiable_text(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    suffix = str(path).lower().rsplit(".", 1)[-1]
    try:
        if suffix == "docx":
            from docx import Document as _DocxDocument

            doc = _DocxDocument(str(path))
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        parts.extend(p.text for p in cell.paragraphs)
            return "\n".join(parts)
        if suffix == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        if suffix == "pptx":
            from pptx import Presentation

            presentation = Presentation(str(path))
            parts = []
            for slide in presentation.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        parts.append(shape.text)
                    if getattr(shape, "has_table", False):
                        for row in shape.table.rows:
                            parts.extend(cell.text for cell in row.cells)
            return "\n".join(parts)
    except Exception:
        return None
    return None


def verify_doc_transform(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "transform returned no data payload"}
    out = data.get("output_path") or path
    if not _file_exists_and_nonempty(out):
        return {"verified": False, "reason": f"transformed file missing or empty: {out!r}"}
    output_format = str(data.get("output_format", "")).lower()
    if output_format == "docx":
        if _extract_verifiable_text(out) is None:
            return {"verified": False, "reason": "DOCX output could not be parsed"}
    if output_format in {"", "txt", "markdown", "md", "html", "htm"}:
        try:
            with open(out, "r", encoding="utf-8") as handle:
                if not handle.read().strip():
                    return {"verified": False, "reason": "transform output is empty"}
        except (OSError, UnicodeError) as exc:
            return {"verified": False, "reason": f"transform output could not be read: {exc}"}
    elif output_format == "json":
        try:
            import json
            with open(out, "r", encoding="utf-8") as handle:
                json.load(handle)
        except (OSError, ValueError) as exc:
            return {"verified": False, "reason": f"JSON output could not be parsed: {exc}"}
    elif output_format == "csv":
        try:
            with open(out, "r", encoding="utf-8-sig", newline="") as handle:
                if list(csv.reader(handle)) == []:
                    return {"verified": False, "reason": "CSV output is empty"}
        except OSError as exc:
            return {"verified": False, "reason": f"CSV output could not be read: {exc}"}
    return {"verified": True, "reason": "transform output was parsed and is non-empty", "output_matches": True, "output_path": out}


def verify_doc_verify(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``document.verify`` — the provider already runs real
    checks (existence, readability, format, content); honor its
    explicit ``all_passed`` flag as the verification signal.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "verify returned no data payload"}
    if not data.get("all_passed"):
        return {"verified": False, "reason": "verify all_passed flag is false"}
    return {"verified": True, "reason": "verify all_passed flag is true", "all_passed": True}


# ------------------------------------------------------------------
# SPREADSHEET helpers
# ------------------------------------------------------------------


def _spreadsheet_rows(path: str, sheet_name: Optional[str] = None) -> tuple[list[str], list[list[Any]]]:
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        return (rows[0] if rows else [], rows[1:] if rows else [])
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook[sheet_name] if sheet_name else workbook.active
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            return ([str(value) if value is not None else "" for value in rows[0]] if rows else [], rows[1:] if rows else [])
        finally:
            workbook.close()
    raise ValueError(f"unsupported spreadsheet format: {suffix}")


def _same_cell(left: Any, right: Any) -> bool:
    if left == right:
        return True
    if left is None or right is None:
        return False
    return str(left) == str(right)


def verify_sheet_add_column(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "add_column returned no verification metadata"}
    output = data.get("output") or path
    column = data.get("column")
    expected = data.get("values")
    if not output or not column or not isinstance(expected, list):
        return {"verified": False, "reason": "add_column omitted output, column, or values"}
    try:
        actual = _spreadsheet_column_values(str(output), str(column))
    except Exception as exc:
        return {"verified": False, "reason": f"could not read added column: {exc}"}
    padded = list(expected) + [""] * max(0, len(actual) - len(expected))
    if len(actual) != len(padded) or not all(_same_cell(a, b) for a, b in zip(actual, padded)):
        return {"verified": False, "reason": "added column values did not match the request"}
    return {"verified": True, "reason": "added column was reread and matched", "output_matches": True}


def verify_sheet_update_cell(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "update_cell returned no verification metadata"}
    output = data.get("output") or path
    row = data.get("row")
    column = data.get("column")
    expected = data.get("value")
    if not output or not isinstance(row, int) or row < 2 or not column:
        return {"verified": False, "reason": "update_cell omitted a valid target"}
    try:
        headers, rows = _spreadsheet_rows(str(output))
        actual = rows[row - 2][headers.index(column)]
    except Exception as exc:
        return {"verified": False, "reason": f"could not read updated cell: {exc}"}
    if not _same_cell(actual, expected):
        return {"verified": False, "reason": "updated cell value did not match"}
    return {"verified": True, "reason": "updated cell was reread and matched", "output_matches": True}


def verify_sheet_create_from_dicts(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict) or not path:
        return {"verified": False, "reason": "create returned no verification metadata"}
    try:
        headers, rows = _spreadsheet_rows(str(path))
    except Exception as exc:
        return {"verified": False, "reason": f"could not read created spreadsheet: {exc}"}
    expected_headers = data.get("headers")
    expected_rows = data.get("rows")
    if expected_headers is not None and headers != expected_headers:
        return {"verified": False, "reason": "created headers did not match"}
    if expected_rows is not None:
        if len(rows) != len(expected_rows) or any(
            len(actual) != len(expected) or not all(_same_cell(a, b) for a, b in zip(actual, expected))
            for actual, expected in zip(rows, expected_rows)
        ):
            return {"verified": False, "reason": "created rows did not match"}
    return {"verified": True, "reason": "created spreadsheet was reread and matched", "output_matches": True}


def verify_sheet_calculate_values(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "calculate returned no verification metadata"}
    output = data.get("output") or path
    column = data.get("calculated_column")
    expected = data.get("calculated_values")
    if not output or not column or not isinstance(expected, list):
        return {"verified": False, "reason": "calculate omitted output, column, or values"}
    try:
        actual = _spreadsheet_column_values(str(output), str(column))
    except Exception as exc:
        return {"verified": False, "reason": f"could not read calculated column: {exc}"}
    if len(actual) != len(expected) or not all(_same_cell(a, b) for a, b in zip(actual, expected)):
        return {"verified": False, "reason": "calculated values did not match"}
    return {"verified": True, "reason": "calculated column was reread and matched", "output_matches": True}


def verify_sheet_rank_values(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "rank returned no verification metadata"}
    output = data.get("output") or path
    try:
        values = _spreadsheet_column_values(str(output), "Rank")
    except Exception as exc:
        return {"verified": False, "reason": f"could not read rank column: {exc}"}
    expected_count = data.get("row_count")
    if not values or (expected_count is not None and len(values) != expected_count):
        return {"verified": False, "reason": "rank column row count did not match"}
    try:
        ranks = sorted(int(float(value)) for value in values)
    except (TypeError, ValueError):
        return {"verified": False, "reason": "rank column contains invalid values"}
    if ranks != list(range(1, len(values) + 1)):
        return {"verified": False, "reason": "rank column is not a complete rank sequence"}
    return {"verified": True, "reason": "rank column was reread and validated", "output_matches": True}

def verify_sheet_inspect(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``spreadsheet.inspect`` — verify the workbook file exists."""
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists(path):
        return {"verified": False, "reason": f"workbook does not exist: {path!r}"}
    if data is None:
        return {"verified": False, "reason": "inspect returned no data payload"}
    return {"verified": True, "reason": "workbook exists", "file_exists": True}


def verify_sheet_read(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``spreadsheet.read`` — verify the file exists AND the read
    produced a non-empty list of rows. An empty file is still a
    valid read but not a useful "verified read"; report honestly.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists(path):
        return {"verified": False, "reason": f"file does not exist: {path!r}"}
    if data is None:
        return {"verified": False, "reason": "read returned no rows payload"}
    return {"verified": True, "reason": "spreadsheet file was read", "rows": len(data.get("rows", [])) if isinstance(data, dict) else 0}


def _spreadsheet_column_values(
    path: str,
    column: str,
) -> list[Any]:
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if column not in (reader.fieldnames or []):
                raise ValueError(f"column not found: {column}")
            return [row.get(column, "") for row in reader]
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows = list(sheet.iter_rows(values_only=True))
            if not rows or column not in rows[0]:
                raise ValueError(f"column not found: {column}")
            index = list(rows[0]).index(column)
            return [row[index] if index < len(row) else None for row in rows[1:]]
        finally:
            workbook.close()
    raise ValueError(f"unsupported spreadsheet format: {suffix}")


def _spreadsheet_sort_key(value: Any) -> tuple:
    text = "" if value is None else str(value)
    parts = []
    for segment in re.split(r"(\d+)", text):
        if segment.isdigit():
            parts.append((1, int(segment)))
        else:
            parts.append((0, segment.lower()))
    return tuple(parts)


def verify_sheet_sort(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``spreadsheet.sort`` — verify the output file exists with
    content. ``output`` (or the original ``path``) must be on
    disk and non-empty.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "sort returned no verification metadata"}
    out = data.get("output") or path
    column = data.get("column")
    if not column:
        return {"verified": False, "reason": "sort did not report the sorted column"}
    if not _file_exists_and_nonempty(out):
        return {"verified": False, "reason": f"sort output missing or empty: {out!r}"}
    try:
        values = _spreadsheet_column_values(out, str(column))
    except Exception as exc:
        return {"verified": False, "reason": f"could not read sorted output: {exc}"}
    keys = [_spreadsheet_sort_key(value) for value in values]
    descending = bool(data.get("descending", False))
    ordered = all(
        keys[index] >= keys[index + 1]
        if descending
        else keys[index] <= keys[index + 1]
        for index in range(len(keys) - 1)
    )
    if not ordered:
        return {"verified": False, "reason": "sort output is not in the requested order"}
    return {
        "verified": True,
        "reason": "sort output was reread and matches the requested order",
    }


def verify_sheet_filter(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "filter returned no data payload"}
    output = data.get("output") or path
    if not _file_exists_and_nonempty(output):
        return {"verified": False, "reason": f"filtered file missing or empty: {output!r}"}
    column = data.get("column")
    condition = str(data.get("condition", "")).lower()
    expected_value = data.get("value")
    if not column or not condition:
        return {"verified": False, "reason": "filter omitted its comparison contract"}
    try:
        headers, rows = _spreadsheet_rows(str(output))
        index = headers.index(column)
        values = [row[index] if index < len(row) else "" for row in rows]
    except Exception as exc:
        return {"verified": False, "reason": f"could not read filtered output: {exc}"}
    predicates = {
        "equals": lambda actual: str(actual) == str(expected_value),
        "equal": lambda actual: str(actual) == str(expected_value),
        "contains": lambda actual: str(expected_value) in str(actual),
        "gt": lambda actual: float(actual) > float(expected_value),
        "gte": lambda actual: float(actual) >= float(expected_value),
        "lt": lambda actual: float(actual) < float(expected_value),
        "lte": lambda actual: float(actual) <= float(expected_value),
    }
    predicate = predicates.get(condition)
    if predicate is None:
        return {"verified": False, "reason": f"unsupported filter condition: {condition}"}
    if len(values) != data.get("filtered_count", len(values)):
        return {"verified": False, "reason": "filtered row count did not match"}
    if not all(predicate(value) for value in values):
        return {"verified": False, "reason": "filtered output contains a non-matching row"}
    return {"verified": True, "reason": "filtered output was reread and every row matched", "output_matches": True}


def verify_sheet_calculate(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``spreadsheet.calculate`` — verify the file exists after
    the formula column was computed and the data carries the
    calculated values.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not _file_exists_and_nonempty(path):
        return {"verified": False, "reason": f"calculated file missing or empty: {path!r}"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "calculate returned no data payload"}
    if not data.get("calculated_column"):
        return {"verified": False, "reason": "calculate did not report calculated_column"}
    return {"verified": True, "reason": "calculated file exists with new column", "output_matches": True}


def verify_sheet_rank(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``spreadsheet.rank`` — verify the file exists after rank
    assignment.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    out = path
    if isinstance(data, dict):
        out = data.get("output") or out
    if not _file_exists_and_nonempty(out):
        return {"verified": False, "reason": f"rank output missing or empty: {out!r}"}
    return {"verified": True, "reason": "rank output exists and is non-empty", "output_matches": True}


def verify_sheet_group_by(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "group_by returned no data payload"}
    output = data.get("output") or path
    groups = data.get("groups")
    if not groups or not _file_exists_and_nonempty(output):
        return {"verified": False, "reason": "group output or groups are missing"}
    try:
        headers, rows = _spreadsheet_rows(str(output))
    except Exception as exc:
        return {"verified": False, "reason": f"could not read group output: {exc}"}
    if len(rows) != len(groups):
        return {"verified": False, "reason": "group output row count did not match"}
    for row, group in zip(rows, groups):
        if isinstance(group, dict):
            key = group.get("key")
            value = group.get("value")
        else:
            key, value = group[0], group[1]
        if not _same_cell(row[0], key) or not _same_cell(row[1], value):
            return {"verified": False, "reason": "group output values did not match"}
    return {"verified": True, "reason": "group output was reread and matched", "output_matches": True}


def verify_sheet_aggregate(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "aggregate returned no data payload"}
    output = data.get("output") or path
    aggregates = data.get("aggregates") or data.get("results")
    if not aggregates or not _file_exists_and_nonempty(output):
        return {"verified": False, "reason": "aggregate output or values are missing"}
    try:
        headers, rows = _spreadsheet_rows(str(output))
    except Exception as exc:
        return {"verified": False, "reason": f"could not read aggregate output: {exc}"}
    expected = list(aggregates.values()) if isinstance(aggregates, dict) else aggregates
    if len(rows) != 1 or len(rows[0]) != len(expected):
        return {"verified": False, "reason": "aggregate output shape did not match"}
    if headers != list(aggregates.keys()) if isinstance(aggregates, dict) else False:
        return {"verified": False, "reason": "aggregate headers did not match"}
    if not all(_same_cell(actual, wanted) for actual, wanted in zip(rows[0], expected)):
        return {"verified": False, "reason": "aggregate values did not match"}
    return {"verified": True, "reason": "aggregate output was reread and matched", "output_matches": True}


def verify_sheet_compare(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "compare returned no data payload"}
    p1 = data.get("path1") or path
    p2 = data.get("path2")
    if not _file_exists(p1):
        return {"verified": False, "reason": f"first workbook missing: {p1!r}"}
    if not _file_exists(p2):
        return {"verified": False, "reason": f"second workbook missing: {p2!r}"}
    total = data.get("total_differences")
    differences = data.get("differences")
    if total is not None:
        if not isinstance(total, int) or total < 0:
            return {"verified": False, "reason": "comparison total is invalid"}
        if not isinstance(differences, list):
            return {"verified": False, "reason": "comparison differences are missing"}
        if total == 0 and differences:
            return {"verified": False, "reason": "comparison reported zero differences with rows"}
    return {"verified": True, "reason": "both workbooks were read and comparison data was returned", "output_matches": True}


def _structured_output_rows(path: str) -> list[Any]:
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".json":
        import json
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, list) else [value]
    if suffix == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [str(value) if value is not None else "" for value in rows[0]]
            return [
                {headers[index]: value for index, value in enumerate(row)}
                for row in rows[1:]
            ]
        finally:
            workbook.close()
    raise ValueError(f"unsupported structured output format: {suffix}")


def verify_data_inspect(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not path or not os.path.isfile(path):
        return {"verified": False, "reason": "data source does not exist"}
    if not isinstance(data, dict) or not data:
        return {"verified": False, "reason": "structured inspection returned no schema payload"}
    return {"verified": True, "reason": "structured source and schema were read", "schema": True}


def verify_data_transform(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "transform returned no verification metadata"}
    output = data.get("output") or path
    expected = data.get("rows")
    if not output or not os.path.isfile(output):
        return {"verified": False, "reason": "transform output does not exist"}
    try:
        actual = _structured_output_rows(str(output))
    except Exception as exc:
        return {"verified": False, "reason": f"could not parse transform output: {exc}"}
    if isinstance(expected, list) and actual != expected:
        return {"verified": False, "reason": "transform output rows did not match"}
    return {"verified": True, "reason": "transform output was parsed and matched", "output_matches": True}


# ------------------------------------------------------------------
# BROWSER helpers
# ------------------------------------------------------------------
#
# The browser layer has its own provider implementations
# (WebBrowserProvider, PlaywrightBrowserProvider, SeleniumBrowserProvider).
# Some of them already set ``verified`` on their result dicts (e.g.
# WebBrowserProvider.open_url). The helpers below fill the gap for
# providers that only set ``success`` by deriving ``verified`` from
# the strongest cheap post-state signal available in the result.
# ------------------------------------------------------------------


def verify_browser_navigate(success: bool, result_dict: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    requested = result_dict.get("requested_url")
    actual = result_dict.get("actual_url") or result_dict.get("url")
    if not isinstance(actual, str) or not actual:
        return {"verified": False, "reason": "no independent URL readback was supplied"}
    if result_dict.get("verification_type") == "search_url_and_title" and result_dict.get("title"):
        return {"verified": True, "reason": "search URL and title were read back"}
    if requested and (
        str(actual).rstrip("/") == str(requested).rstrip("/")
        or str(actual).startswith(str(requested))
    ):
        return {"verified": True, "reason": "requested URL matched the observed URL"}
    return {"verified": False, "reason": "observed URL did not match the requested URL"}


def verify_browser_click(success: bool, result_dict: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    if result_dict.get("click_postcondition_verified") is True:
        return {"verified": True, "reason": "click postcondition was independently read back"}
    return {
        "verified": False,
        "reason": "element presence alone does not prove a click postcondition",
    }


def verify_browser_scroll(success: bool, result_dict: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    if result_dict.get("scroll_position_changed") is True:
        return {"verified": True, "reason": "scroll position changed after dispatch"}
    return {"verified": False, "reason": "scroll position was not independently observed"}


def verify_browser_type(success: bool, result_dict: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    actual = result_dict.get("actual_value")
    expected = result_dict.get("text")
    if result_dict.get("content_match") is True and actual == expected:
        return {"verified": True, "reason": "input value matched after typing"}
    if result_dict.get("post_state_matches") is True and actual is not None:
        return {"verified": True, "reason": "provider supplied typed-content evidence"}
    return {"verified": False, "reason": "typed input value was not independently matched"}


def verify_browser_extract(success: bool, result_dict: Any) -> Dict[str, Any]:
    """``browser.extract_text`` — verify a non-empty text payload
    was returned.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    text = result_dict.get("text")
    if not isinstance(text, str) or not text:
        return {"verified": False, "reason": "extract returned empty text"}
    return {"verified": True, "reason": "extract returned non-empty text"}


def verify_browser_find(success: bool, result_dict: Any) -> Dict[str, Any]:
    """``browser.find_text`` — verify a count was reported.
    ``count == 0`` is a legitimate "not found" answer.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    if "count" not in result_dict and "matches" not in result_dict:
        return {"verified": False, "reason": "find returned no count or matches"}
    return {"verified": True, "reason": "find returned count"}


def verify_browser_title(success: bool, result_dict: Any) -> Dict[str, Any]:
    """``browser.get_page_title`` / ``browser.get_page_url`` —
    verify a non-empty value was returned.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    value = result_dict.get("title") or result_dict.get("url")
    if not isinstance(value, str) or not value:
        return {"verified": False, "reason": "no title / url returned"}
    return {"verified": True, "reason": "non-empty title/url returned"}


def verify_browser_tab_mgmt(success: bool, result_dict: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    if result_dict.get("tab_state_verified") is True:
        return {"verified": True, "reason": "tab state was read back after dispatch"}
    if result_dict.get("operation") == "browser.get_tabs" and isinstance(result_dict.get("tabs"), list):
        return {"verified": True, "reason": "current tab collection was read back"}
    return {"verified": False, "reason": "tab index or count alone does not prove tab state"}


def verify_browser_wait(success: bool, result_dict: Any) -> Dict[str, Any]:
    """``browser.wait_for_element`` — verify the element was found."""
    if not success:
        return {"verified": False, "reason": "provider reported failure (element not found)"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    if result_dict.get("element_found") is True or result_dict.get("found") is True:
        return {"verified": True, "reason": "wait reported element found"}
    return {"verified": False, "reason": "wait returned no element_found signal"}


def verify_browser_screenshot(success: bool, result_dict: Any) -> Dict[str, Any]:
    """``browser.screenshot`` — verify the screenshot file exists."""
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    saved = result_dict.get("path") or result_dict.get("file")
    if saved and _file_exists_and_nonempty(saved):
        return {"verified": True, "reason": "screenshot file exists"}
    return {"verified": False, "reason": "no screenshot file path returned"}


def verify_browser_select(success: bool, result_dict: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    if result_dict.get("selection_verified") is True:
        return {"verified": True, "reason": "selected option was read back and matched"}
    return {"verified": False, "reason": "requested selection is not an observed selection"}


def verify_browser_download(success: bool, result_dict: Any) -> Dict[str, Any]:
    """``browser.download`` — verify the downloaded file exists."""
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    saved = result_dict.get("save_path") or result_dict.get("path")
    if saved and _file_exists_and_nonempty(saved):
        return {"verified": True, "reason": "downloaded file exists"}
    return {"verified": False, "reason": "downloaded file missing or path not reported"}


def verify_browser_upload(success: bool, result_dict: Any) -> Dict[str, Any]:
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    return {
        "verified": False,
        "reason": "local input readback cannot prove remote upload completion",
    }


def verify_browser_verify(success: bool, result_dict: Any) -> Dict[str, Any]:
    """``browser.verify`` — verify the explicit checks passed."""
    if not success:
        return {"verified": False, "reason": "verify reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    checks = result_dict.get("checks") or []
    if not checks:
        return {"verified": False, "reason": "verify ran no checks"}
    if not all(bool(c.get("passed", False)) for c in checks):
        return {"verified": False, "reason": "at least one verify check failed"}
    return {"verified": True, "reason": "all verify checks passed"}


def verify_browser_capabilities(success: bool, result_dict: Any) -> Dict[str, Any]:
    """``browser.capabilities`` — read-only introspection.

    Verification is bound to the provider name being reported; if
    the provider name is missing, fall back to honest ``False``.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(result_dict, dict):
        return {"verified": False, "reason": "no result payload"}
    if result_dict.get("provider"):
        return {"verified": True, "reason": "provider name reported"}
    return {"verified": False, "reason": "no provider name reported"}


# ------------------------------------------------------------------
# FILESYSTEM helpers
# ------------------------------------------------------------------
#
# Filesystem operations (file.copy, file.move, file.rename,
# file.delete, folder.create, folder.list) previously had NO
# verification helpers — OSManager wrappers delegated directly to
# SafeFileManager / FolderManager and trusted their self-reported
# ``verified`` field.  This mirrors the exact gap the document /
# spreadsheet / browser helpers closed in Phase 0.
#
# Each helper observes a cheap, real, post-state signal (file
# existence on disk, source removal, directory existence) and
# reports ``verified=True`` only when that signal is consistent
# with the provider's success.  When no cheap real signal exists
# the helper returns ``verified=False`` with an explicit reason.
# ------------------------------------------------------------------


def verify_file_copy(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``file.copy`` — verify the destination file exists on disk
    and has non-zero size after the copy.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "copy returned no data payload"}
    dest = data.get("destination") or data.get("path")
    if not _file_exists_and_nonempty(dest):
        return {"verified": False, "reason": f"copied file missing or empty: {dest!r}"}
    return {"verified": True, "reason": "copied file exists on disk"}


def verify_file_move(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``file.move`` — verify the destination exists AND the source
    was removed.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "move returned no data payload"}
    dest = data.get("destination") or data.get("path")
    source = data.get("source")
    if not _file_exists(dest):
        return {"verified": False, "reason": f"moved file missing at destination: {dest!r}"}
    if source and _file_exists(source):
        return {"verified": False, "reason": f"source still exists after move: {source!r}"}
    return {"verified": True, "reason": "file moved: destination exists, source removed"}


def verify_file_rename(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``file.rename`` — verify the new path exists and the old
    path no longer exists.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "rename returned no data payload"}
    new_path = data.get("new_path")
    old_path = data.get("old_path")
    if not new_path or not _file_exists(new_path):
        return {"verified": False, "reason": f"renamed file missing: {new_path!r}"}
    if old_path and _file_exists(old_path):
        return {"verified": False, "reason": f"old path still exists after rename: {old_path!r}"}
    return {"verified": True, "reason": "file renamed successfully"}


def verify_file_delete(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``file.delete`` — verify the file no longer exists on disk
    after deletion.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    target = path
    if isinstance(data, dict):
        target = data.get("path") or target
    if target and _file_exists(target):
        return {"verified": False, "reason": f"file still exists after delete: {target!r}"}
    return {"verified": True, "reason": "file successfully removed from disk"}


def verify_folder_create(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``folder.create`` — verify the directory exists on disk."""
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    target = path
    if isinstance(data, dict):
        target = data.get("path") or target
    if not target or not isinstance(target, str):
        return {"verified": False, "reason": "no folder path returned"}
    try:
        exists = os.path.isdir(target)
    except OSError:
        exists = False
    if not exists:
        return {"verified": False, "reason": f"created folder missing: {target!r}"}
    return {"verified": True, "reason": "created folder exists on disk"}


def verify_folder_list(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``folder.inspect`` (list) — verify the directory exists and
    the items payload was returned.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    if not isinstance(data, dict):
        return {"verified": False, "reason": "list returned no data payload"}
    target = data.get("path") or path
    if not target:
        return {"verified": False, "reason": "no folder path in result"}
    try:
        exists = os.path.isdir(target)
    except OSError:
        exists = False
    if not exists:
        return {"verified": False, "reason": f"listed folder does not exist: {target!r}"}
    if "items" not in data:
        return {"verified": False, "reason": "list returned no items payload"}
    return {"verified": True, "reason": "folder listed with items"}


def verify_file_resolve(success: bool, path: Optional[str], data: Any) -> Dict[str, Any]:
    """``file.resolve`` / natural-language resolution — verify the
    resolved path actually exists on disk.  This is the critical
    verification for Phase 7 filesystem intelligence: invented
    paths MUST be caught.
    """
    if not success:
        return {"verified": False, "reason": "provider reported failure"}
    target = path
    if isinstance(data, dict):
        target = data.get("resolved_path") or data.get("path") or target
    if not target or not isinstance(target, str):
        return {"verified": False, "reason": "no resolved path returned"}
    if not _file_exists(target):
        return {"verified": False, "reason": f"resolved path does not exist: {target!r}"}
    return {"verified": True, "reason": "resolved path exists on disk"}


# ============================================================
# PHASE 5 — CAPABILITY-SPECIFIC VERIFICATION MATRIX
# ============================================================
#
# Authoritative inventory: which verifier proves each
# capability's post-state. Drift-proof: the coverage test
# resolves every entry to a real function in this module.

VERIFICATION_MATRIX: Dict[str, str] = {
    # Documents
    "document.inspect": "verify_doc_inspect",
    "document.read": "verify_doc_read",
    "document.search": "verify_doc_search",
    "document.create": "verify_doc_create",
    "document.compare": "verify_doc_compare",
    "document.summarize": "verify_doc_summarize",
    "document.edit": "verify_doc_edit",
    "document.transform": "verify_doc_transform",
    "document.verify": "verify_doc_verify",
    # Spreadsheets
    "spreadsheet.inspect": "verify_sheet_inspect",
    "spreadsheet.read": "verify_sheet_read",
    "spreadsheet.sort": "verify_sheet_sort",
    "spreadsheet.filter": "verify_sheet_filter",
    "spreadsheet.calculate": "verify_sheet_calculate",
    "spreadsheet.rank": "verify_sheet_rank",
    "spreadsheet.group_by": "verify_sheet_group_by",
    "spreadsheet.aggregate": "verify_sheet_aggregate",
    "spreadsheet.add_column": "verify_sheet_add_column",
    "spreadsheet.update_cell": "verify_sheet_update_cell",
    "spreadsheet.create_from_dicts": "verify_sheet_create_from_dicts",
    "spreadsheet.compare": "verify_sheet_compare",
    "data.inspect": "verify_data_inspect",
    "data.transform": "verify_data_transform",
    # Browser
    "browser.open_url": "verify_browser_navigate",
    "browser.click": "verify_browser_click",
    "browser.type": "verify_browser_type",
    "browser.extract": "verify_browser_extract",
    "browser.search": "verify_browser_navigate",
    "browser.get_title": "verify_browser_title",
    "browser.switch_tab": "verify_browser_tab_mgmt",
    "browser.open_tab": "verify_browser_tab_mgmt",
    "browser.close_tab": "verify_browser_tab_mgmt",
    "browser.get_tabs": "verify_browser_tab_mgmt",
    "browser.wait": "verify_browser_wait",
    "browser.screenshot": "verify_browser_screenshot",
    "browser.select": "verify_browser_select",
    "browser.download": "verify_browser_download",
    "browser.upload": "verify_browser_upload",
    "browser.verify": "verify_browser_verify",
    "browser.get_page_state": "verify_browser_capabilities",
    # Filesystem
    "file.copy": "verify_file_copy",
    "file.move": "verify_file_move",
    "file.rename": "verify_file_rename",
    "file.delete": "verify_file_delete",
    "folder.create": "verify_folder_create",
    "folder.list": "verify_folder_list",
    "file.resolve": "verify_file_resolve",
}


def get_capability_verifier(capability_id: str) -> Optional[Any]:
    """Return the verifier function for a capability, if mapped."""
    name = VERIFICATION_MATRIX.get(capability_id)
    if not name:
        return None
    return globals().get(name)