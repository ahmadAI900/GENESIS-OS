"""Phase 9 regression: document.edit must never destroy the original.

Covers two fixed defects (same pattern as the spreadsheet fix):
1. ``edit()`` wrote results back to the SAME file it read from
   (``open(abs_path, "w")``), silently destroying user data.
2. Editing a .docx flattened it to plain text — headings, bold,
   tables gone; the file was no longer even a valid .docx.

Formats this module cannot edit without destroying structure
(PDF, PPTX, XLSX, HTML) must be refused loudly, never silently
degraded.
"""
import json
import os
import zipfile

import pytest

from genesis_os.document_intelligence import DocumentIntelligence

docx = pytest.importorskip("docx", reason="python-docx required")


def _snapshot(path):
    with open(path, "rb") as f:
        return f.read()


def _assert_preserved(path, before):
    with open(path, "rb") as f:
        assert f.read() == before, "original file was modified"


def _make_docx(path):
    doc = docx.Document()
    doc.add_heading("Quarterly Report", level=1)
    para = doc.add_paragraph()
    run = para.add_run("Revenue was strong")
    run.bold = True
    doc.add_table(rows=2, cols=2).cell(0, 0).text = "Q1"
    doc.save(path)
    return path


class TestEditPreservesOriginalEveryFormat:
    def test_edit_txt(self, tmp_path):
        di = DocumentIntelligence()
        src = str(tmp_path / "notes.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("Hello brave world\n")
        before = _snapshot(src)
        result = di.edit(src, "brave", "genesis")
        assert result.success is True
        assert result.path != os.path.abspath(src)
        assert result.path.endswith("_edited.txt")
        _assert_preserved(src, before)
        assert "genesis" in open(result.path, encoding="utf-8").read()

    def test_edit_csv(self, tmp_path):
        di = DocumentIntelligence()
        src = str(tmp_path / "data.csv")
        with open(src, "w", encoding="utf-8") as f:
            f.write("Name,Age\nAlice,30\n")
        before = _snapshot(src)
        result = di.edit(src, "Alice", "Alicia")
        assert result.success is True
        assert result.path != os.path.abspath(src)
        _assert_preserved(src, before)
        assert "Alicia" in open(result.path, encoding="utf-8").read()

    def test_edit_json(self, tmp_path):
        di = DocumentIntelligence()
        src = str(tmp_path / "data.json")
        with open(src, "w", encoding="utf-8") as f:
            json.dump({"key": "value"}, f)
        before = _snapshot(src)
        result = di.edit(src, "value", "new_value")
        assert result.success is True
        assert result.path != os.path.abspath(src)
        _assert_preserved(src, before)
        assert "new_value" in open(result.path, encoding="utf-8").read()

    def test_edit_markdown(self, tmp_path):
        di = DocumentIntelligence()
        src = str(tmp_path / "readme.md")
        with open(src, "w", encoding="utf-8") as f:
            f.write("# Title\n\nBody.\n")
        before = _snapshot(src)
        result = di.edit(src, "Title", "My Document")
        assert result.success is True
        assert result.path != os.path.abspath(src)
        _assert_preserved(src, before)
        assert "My Document" in open(result.path, encoding="utf-8").read()

    def test_edit_docx_preserves_original_and_structure(self, tmp_path):
        di = DocumentIntelligence()
        src = _make_docx(str(tmp_path / "report.docx"))
        before = _snapshot(src)
        result = di.edit(src, "strong", "record-breaking")
        assert result.success is True, f"docx edit failed: {result.error}"
        assert result.path != os.path.abspath(src)
        assert result.path.endswith("_edited.docx")
        _assert_preserved(src, before)

        # Output is still a REAL .docx with structure intact.
        assert zipfile.is_zipfile(result.path), "edited output is not a valid docx"
        out = docx.Document(result.path)
        styles = [p.style.name if p.style else None for p in out.paragraphs]
        assert "Heading 1" in styles, f"heading style lost: {styles}"
        assert len(out.tables) == 1, "table lost in edited docx"
        bold_runs = [r.text for p in out.paragraphs for r in p.runs if r.bold]
        assert any("record-breaking" in t for t in bold_runs), (
            f"replacement lost its bold run formatting: {bold_runs}"
        )
        assert out.tables[0].cell(0, 0).text == "Q1"

    def test_edit_docx_table_cell(self, tmp_path):
        di = DocumentIntelligence()
        src = _make_docx(str(tmp_path / "report.docx"))
        before = _snapshot(src)
        result = di.edit(src, "Q1", "Q2")
        assert result.success is True, f"docx table edit failed: {result.error}"
        _assert_preserved(src, before)
        out = docx.Document(result.path)
        assert out.tables[0].cell(0, 0).text == "Q2"


class TestExplicitOutputStillHonored:
    def test_edit_txt_explicit_output(self, tmp_path):
        di = DocumentIntelligence()
        src = str(tmp_path / "notes.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("Hello brave world\n")
        before = _snapshot(src)
        out = str(tmp_path / "custom.txt")
        result = di.edit(src, "brave", "genesis", output=out)
        assert result.success is True
        assert result.path == out
        _assert_preserved(src, before)
        assert "genesis" in open(out, encoding="utf-8").read()

    def test_edit_docx_explicit_output(self, tmp_path):
        di = DocumentIntelligence()
        src = _make_docx(str(tmp_path / "report.docx"))
        before = _snapshot(src)
        out = str(tmp_path / "custom.docx")
        result = di.edit(src, "strong", "record-breaking", output=out)
        assert result.success is True
        assert result.path == out
        _assert_preserved(src, before)
        assert zipfile.is_zipfile(out)


class TestDestructiveFormatsRefusedLoudly:
    @pytest.mark.parametrize("name", ["file.pdf", "deck.pptx", "page.html"])
    def test_unsupported_formats_refused_original_untouched(self, tmp_path, name):
        di = DocumentIntelligence()
        src = str(tmp_path / name)
        with open(src, "wb") as f:
            f.write(b"\x00FAKE-" + name.encode() + b"-CONTENT\xff")
        before = _snapshot(src)
        result = di.edit(src, "FAKE", "REAL")
        assert result.success is False, (
            f"{name} edit must be refused, not silently flattened"
        )
        assert result.error == "EditNotSupportedForFormat"
        _assert_preserved(src, before)

    def test_xlsx_refused_original_untouched(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl", reason="openpyxl required")
        di = DocumentIntelligence()
        src = str(tmp_path / "data.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["Name"])
        wb.active.append(["Alice"])
        wb.save(src)
        wb.close()
        before = _snapshot(src)
        result = di.edit(src, "Alice", "Alicia")
        assert result.success is False
        assert result.error == "EditNotSupportedForFormat"
        _assert_preserved(src, before)


class TestTransformContract:
    def test_unknown_output_format_is_refused(self, tmp_path):
        di = DocumentIntelligence()
        src = tmp_path / "source.txt"
        src.write_text("payload", encoding="utf-8")

        result = di.transform(str(src), "", "pdf")

        assert result.success is False
        assert result.error == "UnsupportedFormat"
        assert list(tmp_path.glob("*_transformed.*")) == []

    def test_output_extension_must_match_requested_format(self, tmp_path):
        di = DocumentIntelligence()
        src = tmp_path / "source.txt"
        src.write_text("payload", encoding="utf-8")
        output = tmp_path / "wrong.docx"

        result = di.transform(str(src), str(output), "txt")

        assert result.success is False
        assert result.error == "FormatMismatch"
        assert not output.exists()

    def test_transform_preserves_source_bytes(self, tmp_path):
        di = DocumentIntelligence()
        src = tmp_path / "source.txt"
        src.write_text("payload", encoding="utf-8")
        before = _snapshot(src)

        result = di.transform(str(src), "", "html")

        assert result.success is True
        _assert_preserved(src, before)
        assert result.data["original_preserved"] is True
