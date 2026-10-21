"""Item 25A (C34): load_workbook opened but never closed -- the
remaining sites after C21/C30.

``load_workbook(read_only=True, ...)`` keeps the .zip archive handle
open until ``wb.close()`` (same class as Item 17D/C21 and 24B/C30).
The directive's audit found the same defect still live at 12 sites in
7 files:

  semantic_parser.py         _parse_excel            closed on NO path
  document_intelligence.py   _read_xlsx              exception path leaks
  document_intelligence.py   _read_xlsx_metadata     exception path leaks
  document_intelligence.py   _extract_xlsx_tables    exception path leaks
  knowledge/knowledge.py     _read_text              exception path leaks
  security_scanner.py        _scan_metadata          exception path leaks
  security_scanner.py        _detect_hidden_content  exception path leaks
  security_scanner.py        _scan_excel             exception path leaks
  nlq_engine.py              _schema                 exception path leaks
  nlq_engine.py              _load                   exception path leaks
  format_converter.py        _convert_excel_to_csv   exception path leaks
  format_converter.py        _convert_excel_to_json  exception path leaks

Sites already in try/finally (verification_helpers' 3 sites,
agents/document_agent, agents/agent_tools) are not part of the defect.

Every leaky site sits inside a broad ``except`` that swallows a read
error AFTER the handle was opened -- the exception path is where the
handle leaks. Each site therefore gets two fake-loader tests: close()
on SUCCESS and close() on EXCEPTION.

A leaked handle also PINS THE FILE on Windows: verified on this box,
``os.remove`` raises PermissionError while a read_only archive lives
and succeeds after close(). The REAL round-trip test drives
``SemanticDocumentParser._parse_excel`` -- the site that never closed
on any path -- over a real workbook and proves the artifact: the file
must be deletable afterwards. It also asserts the parse did not fall
back, so the round-trip really exercised the leaky code.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from genesis_os.document_intelligence import DocumentIntelligence
from genesis_os.format_converter import FormatConverter
from genesis_os.nlq_engine import NLQEngine
from genesis_os.security_scanner import SecurityScanner
from genesis_os.semantic_parser import SemanticDocumentParser
from knowledge.knowledge import Knowledge


# ---------------------------------------------------------------------------
# Fake loader plumbing.
# ---------------------------------------------------------------------------


class _FakeWorksheet:
    def __init__(self, rows=None, fail_on=None, title="Sheet1"):
        self._rows = rows or (("alpha", "beta"), ("1", "2"))
        self._fail_on = fail_on
        self.title = title

    @property
    def sheet_state(self):
        if self._fail_on == "state":
            raise RuntimeError("sheet state unreadable")
        return "visible"

    def iter_rows(self, values_only=True):
        if self._fail_on == "iter":
            raise RuntimeError("read error inside the sheet")
        return iter(self._rows)

    def _dimensions(self):
        if self._fail_on == "dims":
            raise RuntimeError("dimensions unreadable")
        return {}

    column_dimensions = property(_dimensions)
    row_dimensions = property(_dimensions)


class _FakeWorkbook:
    """Workbook returned by the patched loader.

    ``fail_on`` picks the accessor that raises, modelling an exception
    AFTER load_workbook handed back a live handle: "iter", "state",
    "properties", or "sheetnames".
    """

    def __init__(self, fail_on=None):
        self._fail_on = fail_on
        self._worksheets = [_FakeWorksheet(fail_on=fail_on)]
        self.closed = 0

    @property
    def sheetnames(self):
        if self._fail_on == "sheetnames":
            raise RuntimeError("manifest unreadable")
        return [ws.title for ws in self._worksheets]

    @property
    def worksheets(self):
        return list(self._worksheets)

    @property
    def active(self):
        return self._worksheets[0]

    @property
    def properties(self):
        if self._fail_on == "properties":
            raise RuntimeError("properties unreadable")
        return SimpleNamespace(
            creator="Ada",
            created="2020-01-01",
            modified="2020-01-02",
            lastModifiedBy="Ada",
        )

    def __getitem__(self, name):
        for ws in self._worksheets:
            if ws.title == name:
                return ws
        raise KeyError(name)

    def close(self):
        self.closed += 1


def _patch(target, monkeypatch, workbook):
    """Route the site's load_workbook binding to the fake.

    The product mixes two binding styles: ``openpyxl.load_workbook``
    looked up at call time (package attribute -- semantic_parser,
    knowledge, nlq_engine, format_converter) and a module-level
    ``from openpyxl import load_workbook`` (document_intelligence,
    security_scanner -- patching the package would not reach those).
    """
    loader = lambda *args, **kwargs: workbook  # noqa: E731
    if target == "openpyxl":
        import openpyxl

        monkeypatch.setattr(openpyxl, "load_workbook", loader)
    else:
        module = importlib.import_module(target)
        monkeypatch.setattr(module, "load_workbook", loader)


# ---------------------------------------------------------------------------
# The 12 leaky sites: how to call each one.
# ---------------------------------------------------------------------------

_SITES = {
    "semantic_parser._parse_excel": dict(
        target="openpyxl",
        fail_on="iter",
        swallow=True,
        invoke=lambda tmp: SemanticDocumentParser()._parse_excel(
            str(tmp / "probe.xlsx")
        ),
    ),
    "document_intelligence._read_xlsx": dict(
        target="genesis_os.document_intelligence",
        fail_on="iter",
        swallow=False,
        invoke=lambda tmp: DocumentIntelligence()._read_xlsx(
            str(tmp / "probe.xlsx")
        ),
    ),
    "document_intelligence._read_xlsx_metadata": dict(
        target="genesis_os.document_intelligence",
        fail_on="sheetnames",
        swallow=False,
        invoke=lambda tmp: DocumentIntelligence()._read_xlsx_metadata(
            str(tmp / "probe.xlsx")
        ),
    ),
    "document_intelligence._extract_xlsx_tables": dict(
        target="genesis_os.document_intelligence",
        fail_on="iter",
        swallow=False,
        invoke=lambda tmp: DocumentIntelligence()._extract_xlsx_tables(
            str(tmp / "probe.xlsx")
        ),
    ),
    "knowledge._read_text": dict(
        target="openpyxl",
        fail_on="iter",
        swallow=True,
        invoke=lambda tmp: Knowledge()._read_text(tmp / "probe.xlsx"),
    ),
    "security_scanner._scan_metadata": dict(
        target="genesis_os.security_scanner",
        fail_on="properties",
        swallow=True,
        invoke=lambda tmp: SecurityScanner()._scan_metadata(
            str(tmp / "probe.xlsx")
        ),
    ),
    "security_scanner._detect_hidden_content": dict(
        target="genesis_os.security_scanner",
        fail_on="state",
        swallow=True,
        invoke=lambda tmp: SecurityScanner()._detect_hidden_content(
            str(tmp / "probe.xlsx")
        ),
    ),
    "security_scanner._scan_excel": dict(
        target="genesis_os.security_scanner",
        fail_on="iter",
        swallow=True,
        invoke=lambda tmp: SecurityScanner()._scan_excel(
            str(tmp / "probe.xlsx")
        ),
    ),
    "nlq_engine._schema": dict(
        target="openpyxl",
        fail_on="iter",
        swallow=True,
        invoke=lambda tmp: NLQEngine()._schema(str(tmp / "probe.xlsx")),
    ),
    "nlq_engine._load": dict(
        target="openpyxl",
        fail_on="iter",
        swallow=True,
        invoke=lambda tmp: NLQEngine()._load(str(tmp / "probe.xlsx")),
    ),
    "format_converter._convert_excel_to_csv": dict(
        target="openpyxl",
        fail_on="iter",
        swallow=True,
        invoke=lambda tmp: FormatConverter()._convert_excel_to_csv(
            str(tmp / "probe.xlsx"), str(tmp / "out.csv")
        ),
    ),
    "format_converter._convert_excel_to_json": dict(
        target="openpyxl",
        fail_on="iter",
        swallow=True,
        invoke=lambda tmp: FormatConverter()._convert_excel_to_json(
            str(tmp / "probe.xlsx"), str(tmp / "out.json")
        ),
    ),
}


@pytest.mark.parametrize("site_id", sorted(_SITES))
def test_close_on_success(site_id, monkeypatch, tmp_path):
    site = _SITES[site_id]
    fake = _FakeWorkbook(fail_on=None)
    _patch(site["target"], monkeypatch, fake)
    site["invoke"](tmp_path)
    assert fake.closed == 1, (
        f"{site_id} opened a workbook on the success path and did not "
        "close it -- leaked zip handle, pinned file"
    )


@pytest.mark.parametrize("site_id", sorted(_SITES))
def test_close_on_exception(site_id, monkeypatch, tmp_path):
    site = _SITES[site_id]
    fake = _FakeWorkbook(fail_on=site["fail_on"])
    _patch(site["target"], monkeypatch, fake)
    if site["swallow"]:
        site["invoke"](tmp_path)
    else:
        with pytest.raises(RuntimeError):
            site["invoke"](tmp_path)
    assert fake.closed == 1, (
        f"{site_id} leaked the workbook handle when the read raised "
        "after load -- broad except hid it"
    )


def test_real_round_trip_releases_the_handle(tmp_path):
    """The artifact: after parsing a REAL workbook the file must be
    deletable. On Windows a leaked read_only zip handle pins the file
    (os.remove -> PermissionError), so removal IS the proof."""
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "real_round_trip.xlsx"
    creator = openpyxl.Workbook()
    creator.active.append(["alpha", "beta"])
    creator.active.append(["1", "2"])
    creator.save(path)
    creator.close()

    result = SemanticDocumentParser()._parse_excel(str(path))
    assert "fallback" not in (result.metadata or {}), (
        "the parser fell back instead of reading the real workbook -- "
        "this round-trip would prove nothing"
    )

    try:
        os.remove(path)
    except PermissionError:
        pytest.fail(
            "real workbook still locked after parsing: "
            "SemanticDocumentParser._parse_excel never called wb.close()"
        )
    assert not path.exists()
