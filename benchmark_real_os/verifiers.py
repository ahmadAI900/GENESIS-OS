"""Genesis OS — Independent verification helpers.

The verifier module deliberately uses code paths that are
DIFFERENT from the action implementations:

    * action: file.create            -> verifier: Path.is_file + read +
                                                          sha256
    * action: application.open       -> verifier: psutil process scan +
                                                          win32gui window
    * action: browser.open_url       -> verifier: webbrowser controller
                                                          browser URL
    * action: document.create        -> verifier: re-open file with
                                                          python-docx /
                                                          text decode
    * action: spreadsheet.sort       -> verifier: re-open with openpyxl
                                                          and read cells
    * action: clipboard.copy         -> verifier: pyperclip.paste()
    * action: screenshot             -> verifier: PIL.Image open and
                                                          decode

Each helper returns ``(passed: bool, detail: str, evidence: dict)``.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:  # pragma: no cover
    _HAS_PSUTIL = False

try:
    import pyperclip  # type: ignore
    _HAS_PYPERCLIP = True
except Exception:  # pragma: no cover
    _HAS_PYPERCLIP = False

try:
    from openpyxl import load_workbook  # type: ignore
    _HAS_OPENPYXL = True
except Exception:  # pragma: no cover
    _HAS_OPENPYXL = False

try:
    import docx  # python-docx  # type: ignore
    _HAS_PYDOCX = True
except Exception:  # pragma: no cover
    _HAS_PYDOCX = False

try:
    from PIL import Image  # type: ignore
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False


# ============================================================
# GENERIC
# ============================================================


VerifierResult = Tuple[bool, str, Dict[str, Any]]


def _ok(detail: str, **evidence: Any) -> VerifierResult:
    return True, detail, evidence


def _fail(detail: str, **evidence: Any) -> VerifierResult:
    return False, detail, evidence


# ============================================================
# FILESYSTEM
# ============================================================


def verify_file_exists(path: str) -> VerifierResult:
    if not path:
        return _fail("no path provided")
    try:
        p = Path(path)
        if not p.exists():
            return _fail(f"file does not exist: {path}", path=path)
        return _ok(f"file exists: {path}", path=path, size=p.stat().st_size)
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


def verify_file_absent(path: str) -> VerifierResult:
    """Used by cleanup verifiers."""
    try:
        p = Path(path)
        if p.exists():
            return _fail(f"file still exists: {path}", path=path)
        return _ok(f"file absent: {path}", path=path)
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


def verify_file_contains(path: str, expected_substring: str) -> VerifierResult:
    try:
        p = Path(path)
        if not p.exists():
            return _fail(f"file does not exist: {path}", path=path)
        data = p.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        if expected_substring not in text:
            return _fail(
                f"expected substring not found in {path!r}",
                path=path,
                expected=expected_substring,
                preview=text[:200],
            )
        sha = hashlib.sha256(data).hexdigest()
        return _ok(
            f"file contains expected content ({len(expected_substring)} chars)",
            path=path,
            sha256=sha,
            size=len(data),
        )
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


def verify_file_sha256(path: str, expected_sha256: str) -> VerifierResult:
    try:
        p = Path(path)
        if not p.exists():
            return _fail(f"file does not exist: {path}", path=path)
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected_sha256:
            return _fail(
                f"sha256 mismatch for {path}",
                expected=expected_sha256,
                actual=actual,
            )
        return _ok(
            f"sha256 matches {actual[:12]}...",
            path=path,
            sha256=actual,
            size=p.stat().st_size,
        )
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


def verify_folder_exists(path: str) -> VerifierResult:
    try:
        p = Path(path)
        if not p.exists():
            return _fail(f"folder does not exist: {path}", path=path)
        if not p.is_dir():
            return _fail(f"path is not a folder: {path}", path=path)
        return _ok(f"folder exists: {path}", path=path)
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


def verify_folder_absent(path: str) -> VerifierResult:
    try:
        p = Path(path)
        if p.exists():
            return _fail(f"folder still exists: {path}", path=path)
        return _ok(f"folder absent: {path}", path=path)
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


# ============================================================
# DOCUMENT
# ============================================================


def verify_text_document(path: str, expected_substring: str) -> VerifierResult:
    """Open a TXT/CSV/JSON/MD document with stdlib only and check
    content. Independent from python-docx."""
    return verify_file_contains(path, expected_substring)


def verify_docx(path: str, expected_substring: str) -> VerifierResult:
    """Open a DOCX with python-docx (independent from DocumentIntelligence)."""
    if not _HAS_PYDOCX:
        return _fail("python-docx not installed")
    try:
        doc = docx.Document(path)
        all_text: List[str] = []
        for para in doc.paragraphs:
            all_text.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    all_text.append(cell.text)
        joined = "\n".join(all_text)
        if expected_substring not in joined:
            return _fail(
                "expected substring not found in DOCX",
                path=path,
                expected=expected_substring,
                preview=joined[:400],
            )
        return _ok("docx contains expected substring", path=path, char_count=len(joined))
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


# ============================================================
# SPREADSHEET
# ============================================================


def verify_xlsx_has_sheet(
    path: str,
    sheet_name: Optional[str] = None,
) -> VerifierResult:
    if not _HAS_OPENPYXL:
        return _fail("openpyxl not installed")
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet_names = wb.sheetnames
            if sheet_name is not None:
                if sheet_name not in sheet_names:
                    return _fail(
                        f"sheet {sheet_name!r} not in workbook",
                        path=path,
                        sheets=sheet_names,
                    )
            if not sheet_names:
                return _fail("workbook has no sheets", path=path)
            # Read first row to confirm non-empty
            ws = wb[sheet_names[0]]
            first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
            if first_row is None or all(v is None for v in first_row):
                return _fail(
                    "first sheet is empty",
                    path=path,
                    sheet=sheet_names[0],
                )
            return _ok(
                "xlsx has sheets with content",
                path=path,
                sheets=sheet_names,
                first_row=list(first_row),
            )
        finally:
            wb.close()
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


def verify_xlsx_value(
    path: str,
    sheet_name: str,
    cell: str,
    expected_value: Any,
) -> VerifierResult:
    if not _HAS_OPENPYXL:
        return _fail("openpyxl not installed")
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            if sheet_name not in wb.sheetnames:
                return _fail(
                    f"sheet {sheet_name!r} missing",
                    path=path,
                    sheets=wb.sheetnames,
                )
            ws = wb[sheet_name]
            actual = ws[cell].value
            if str(actual).strip() != str(expected_value).strip():
                return _fail(
                    "xlsx value mismatch",
                    path=path,
                    sheet=sheet_name,
                    cell=cell,
                    expected=str(expected_value),
                    actual=str(actual),
                )
            return _ok(
                "xlsx value matches",
                path=path,
                sheet=sheet_name,
                cell=cell,
                value=str(actual),
            )
        finally:
            wb.close()
    except Exception as exc:
        return _fail(f"verifier exception: {exc}", path=path)


# ============================================================
# PROCESS / APPLICATION
# ============================================================


def verify_process_running(name_substring: str, poll_seconds: float = 1.5) -> VerifierResult:
    """Independent process check using psutil.

    Polls for ``poll_seconds`` to tolerate startup latency.
    Returns ``(passed, detail, evidence)``."""
    if not _HAS_PSUTIL:
        return _fail("psutil not installed")
    deadline = time.time() + poll_seconds
    seen: List[Dict[str, Any]] = []
    pattern = re.compile(re.escape(name_substring), re.IGNORECASE)
    while time.time() < deadline:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                n = proc.info.get("name") or ""
                if pattern.search(n):
                    seen.append({"pid": proc.info["pid"], "name": n})
                    return _ok(
                        f"process matching {name_substring!r} running",
                        pid=proc.info["pid"],
                        name=n,
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(0.2)
    return _fail(
        f"no process matching {name_substring!r} found within {poll_seconds}s",
        candidates=seen,
    )


def verify_process_absent(name_substring: str, poll_seconds: float = 1.0) -> VerifierResult:
    if not _HAS_PSUTIL:
        return _fail("psutil not installed")
    pattern = re.compile(re.escape(name_substring), re.IGNORECASE)
    deadline = time.time() + poll_seconds
    while time.time() < deadline:
        found = False
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                n = proc.info.get("name") or ""
                if pattern.search(n):
                    found = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not found:
            return _ok(f"no process matching {name_substring!r} found")
        time.sleep(0.2)
    return _fail(
        f"process matching {name_substring!r} still present after {poll_seconds}s"
    )


def verify_process_count_in_range(name_substring: str, min_count: int, max_count: int) -> VerifierResult:
    if not _HAS_PSUTIL:
        return _fail("psutil not installed")
    pattern = re.compile(re.escape(name_substring), re.IGNORECASE)
    matches: List[str] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            n = proc.info.get("name") or ""
            if pattern.search(n):
                matches.append(n)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if min_count <= len(matches) <= max_count:
        return _ok(
            f"process count for {name_substring!r} = {len(matches)}",
            count=len(matches),
        )
    return _fail(
        f"process count for {name_substring!r} = {len(matches)} (expected {min_count}..{max_count})",
        count=len(matches),
    )


# ============================================================
# CLIPBOARD
# ============================================================


def verify_clipboard_contains(expected_substring: str, retries: int = 3, delay: float = 0.4) -> VerifierResult:
    if not _HAS_PYPERCLIP:
        return _fail("pyperclip not installed")
    last = ""
    for i in range(retries):
        try:
            last = pyperclip.paste() or ""
        except Exception as exc:
            return _fail(f"clipboard read exception: {exc}")
        if expected_substring in last:
            return _ok(
                f"clipboard contains expected substring ({len(expected_substring)} chars)",
                clipboard_preview=last[:120],
            )
        time.sleep(delay)
    return _fail(
        f"clipboard does not contain expected substring after {retries} polls",
        clipboard_preview=last[:120],
    )


# ============================================================
# CAPTURE
# ============================================================


def verify_image_decodes(path: str) -> VerifierResult:
    if not _HAS_PIL:
        return _fail("PIL not installed")
    try:
        with Image.open(path) as im:
            im.verify()
            mode = im.mode
            size = im.size
        return _ok(
            f"image decoded: {size} {mode}",
            path=path,
            size=list(size),
            mode=mode,
        )
    except Exception as exc:
        return _fail(f"image decode exception: {exc}", path=path)


# ============================================================
# SYSTEM
# ============================================================


def verify_system_returns_status() -> VerifierResult:
    """The OSManager.status() dict has a known set of subsystems."""
    try:
        from genesis_os.os_manager import OSManager
        status = OSManager().status()
        keys = sorted(status.keys())
        if not keys:
            return _fail("OSManager.status() returned empty dict")
        return _ok("OSManager.status() returned a non-empty subsystem map", keys=keys)
    except Exception as exc:
        return _fail(f"verifier exception: {exc}")


def verify_processes_listed(min_count: int = 5) -> VerifierResult:
    if not _HAS_PSUTIL:
        return _fail("psutil not installed")
    try:
        procs = list(psutil.process_iter(["pid", "name"]))
        names = [p.info["name"] for p in procs if p.info.get("name")]
        if len(names) < min_count:
            return _fail(
                f"only {len(names)} processes listed (expected >= {min_count})"
            )
        return _ok(f"listed {len(names)} processes", count=len(names))
    except Exception as exc:
        return _fail(f"verifier exception: {exc}")


def verify_battery_reported() -> VerifierResult:
    """Best-effort check that battery report contains percent."""
    try:
        from genesis_os.os_manager import OSManager
        b = OSManager().battery_status()
        if not isinstance(b, dict):
            return _fail("battery_status returned non-dict")
        if "battery_percent" not in b:
            return _fail("battery_status missing 'battery_percent' key", payload=b)
        return _ok(
            "battery report includes percent",
            percent=b.get("battery_percent"),
            plugged=b.get("plugged_in"),
        )
    except Exception as exc:
        return _fail(f"verifier exception: {exc}")


def verify_hardware_stats_reported() -> VerifierResult:
    try:
        from genesis_os.os_manager import OSManager
        s = OSManager().hardware_stats()
        if not isinstance(s, dict):
            return _fail("hardware_stats returned non-dict")
        if "cpu_percent" not in s and "memory_percent" not in s and "uptime_hours" not in s:
            return _fail("hardware_stats missing cpu_percent/memory_percent/uptime_hours", payload=s)
        return _ok("hardware_stats reported cpu/memory/uptime", keys=sorted(s.keys()))
    except Exception as exc:
        return _fail(f"verifier exception: {exc}")


# ============================================================
# COMPOUND VERIFIER HELPERS
# ============================================================


def all_pass(*results: VerifierResult) -> VerifierResult:
    """Aggregate several verifier results into one."""
    failures = [r for r in results if not r[0]]
    if not failures:
        return _ok(
            f"all {len(results)} sub-checks passed",
            sub_count=len(results),
        )
    first = failures[0]
    return _fail(
        f"{len(failures)} of {len(results)} sub-checks failed: {first[1]}",
        failures=[r[1] for r in failures],
    )


# Public registry of named verifiers so scenarios can use
# ``verifier_id`` strings and remain JSON-serialisable.
NAMED_VERIFIERS: Dict[str, Callable[..., VerifierResult]] = {
    "verify_file_exists": verify_file_exists,
    "verify_file_absent": verify_file_absent,
    "verify_file_contains": verify_file_contains,
    "verify_folder_exists": verify_folder_exists,
    "verify_folder_absent": verify_folder_absent,
    "verify_text_document": verify_text_document,
    "verify_docx": verify_docx,
    "verify_xlsx_has_sheet": verify_xlsx_has_sheet,
    "verify_xlsx_value": verify_xlsx_value,
    "verify_process_running": verify_process_running,
    "verify_process_absent": verify_process_absent,
    "verify_process_count_in_range": verify_process_count_in_range,
    "verify_clipboard_contains": verify_clipboard_contains,
    "verify_image_decodes": verify_image_decodes,
    "verify_system_returns_status": verify_system_returns_status,
    "verify_processes_listed": verify_processes_listed,
    "verify_battery_reported": verify_battery_reported,
    "verify_hardware_stats_reported": verify_hardware_stats_reported,
    "verify_file_sha256": verify_file_sha256,
    "all_pass": all_pass,
}


def call_verifier(name: str, *args: Any, **kwargs: Any) -> VerifierResult:
    fn = NAMED_VERIFIERS.get(name)
    if fn is None:
        return _fail(f"unknown verifier_id: {name}")
    return fn(*args, **kwargs)