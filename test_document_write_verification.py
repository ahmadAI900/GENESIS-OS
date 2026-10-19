"""Item 16D (C18): document create/edit/transform left `verified` at None.

Same contract Item 13C defined for `SpreadsheetResult`, now applied to
`DocumentResult`:

    verified=None  the operation claims nothing about verification
    verified=True  the written content was read back and matched
    verified=False read back and did NOT match, or could not be read
                  back -- which is NOT verification

Measured against the committed original:

    create_txt        success=True  verified=None
    create_csv        success=True  verified=None
    create_json       success=True  verified=None
    create_markdown   success=True  verified=None
    edit (text fmts)  success=True  verified=None
    transform         success=True  verified=None

THIS IS NOT COSMETIC. `success` on these paths means "the write call
returned without raising". On a full disk, a locked file or a silently
failed save, that is not evidence the content arrived.

create_pdf is deliberately excluded by the directive: verifying a PDF
means checking rendered content rather than bytes, and a byte
comparison against the generator would be theatre. It continues to
report no claim rather than gain one that looks meaningful and is not.

The docx edit path already verified, from Item 13C, and is pinned here
too so it cannot regress.
"""
from __future__ import annotations

import json
import os

import pytest

from genesis_os.document_intelligence import DocumentIntelligence


@pytest.fixture
def di():
    return DocumentIntelligence()


def _out(tmp_path, name):
    return str(tmp_path / name)


SOURCE = "hello world"


@pytest.fixture
def source_txt(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text(SOURCE)
    return str(path)


# --------------------------------------------------------------------------
# The contract: a successful write is verified, never None
# --------------------------------------------------------------------------

def test_create_txt_verifies(di, tmp_path):
    result = di.create_txt(_out(tmp_path, "a.txt"), "body text")

    assert result.success is True, result.message
    assert result.verified is True


def test_create_csv_verifies(di, tmp_path):
    result = di.create_csv(
        _out(tmp_path, "a.csv"), ["h1", "h2"], [[1, 2], ["x", "y"]]
    )

    assert result.success is True, result.message
    assert result.verified is True


def test_create_json_verifies(di, tmp_path):
    result = di.create_json(_out(tmp_path, "a.json"), {"k": ["v", 2]})

    assert result.success is True, result.message
    assert result.verified is True


def test_create_markdown_verifies(di, tmp_path):
    result = di.create_markdown(_out(tmp_path, "a.md"), "# Title")

    assert result.success is True, result.message
    assert result.verified is True


def test_edit_text_file_verifies(di, source_txt, tmp_path):
    result = di.edit(source_txt, "world", "there")

    assert result.success is True, result.message
    assert result.verified is True, (
        "the text-format edit path was still unclaimed after Item 13C "
        "verified the docx path"
    )


def test_edit_reports_the_occurrence_count(di, source_txt):
    result = di.edit(source_txt, "l", "L")
    assert result.data["occurrences"] == 3
    assert result.verified is True
    assert "heLLo" in open(result.path, encoding="utf-8").read()


def test_transform_to_txt_verifies(di, source_txt, tmp_path):
    result = di.transform(source_txt, _out(tmp_path, "t.txt"), "txt")

    assert result.success is True, result.message
    assert result.verified is True


# --------------------------------------------------------------------------
# The write really did happen -- verified=True is earned, not defaulted
# --------------------------------------------------------------------------

def test_create_txt_artifact_holds_the_content(di, tmp_path):
    result = di.create_txt(_out(tmp_path, "a.txt"), "exact body")

    assert result.verified is True
    assert open(result.path, encoding="utf-8").read() == "exact body"


def test_edit_artifact_holds_the_replacement(di, source_txt, tmp_path):
    result = di.edit(source_txt, "world", "there")

    assert result.verified is True
    assert "hello there" in open(result.path, encoding="utf-8").read()


def test_transform_artifact_holds_the_content(di, source_txt, tmp_path):
    result = di.transform(source_txt, _out(tmp_path, "t.txt"), "txt")

    # transform returns the SOURCE path in .path; the output it wrote
    # is in data["output_path"].
    assert result.verified is True
    assert open(result.data["output_path"], encoding="utf-8").read() == SOURCE


# --------------------------------------------------------------------------
# Per-format transform expectations
# --------------------------------------------------------------------------

def test_transform_html_expectation_includes_the_wrapper(di, source_txt, tmp_path):
    result = di.transform(source_txt, _out(tmp_path, "t.html"), "html")

    assert result.verified is True, (
        "the HTML branch wraps text in a template; verifying against "
        "the raw text alone would have reported False here"
    )
    assert open(result.data["output_path"], encoding="utf-8").read() == (
        "<html><body><pre>hello world</pre></body></html>"
    )


def test_transform_json_expectation_is_the_envelope(di, source_txt, tmp_path):
    result = di.transform(source_txt, _out(tmp_path, "t.json"), "json")

    assert result.verified is True, (
        "the JSON branch writes {'content': text}; a raw-text "
        "comparison would have reported False here"
    )
    assert json.load(open(result.data["output_path"], encoding="utf-8")) == {
        "content": SOURCE
    }


def test_transform_docx_expectation_is_one_paragraph_per_line(
    di, source_txt, tmp_path
):
    pytest.importorskip("docx")
    result = di.transform(source_txt, _out(tmp_path, "t.docx"), "docx")

    assert result.success is True, result.message
    assert result.verified is True, (
        "the DOCX branch writes one paragraph per source line"
    )


def test_transform_csv_round_trips(di, source_txt, tmp_path):
    result = di.transform(source_txt, _out(tmp_path, "t2.csv"), "csv")

    assert result.success is True, result.message
    assert result.verified is True
    assert open(
        result.data["output_path"], encoding="utf-8"
    ).read() == SOURCE


# --------------------------------------------------------------------------
# Unreadable/unmatchable artifacts are NOT verified
# --------------------------------------------------------------------------

def test_an_unreadable_artifact_is_not_verified(di, tmp_path):
    assert di._verify_written_text(
        str(tmp_path / "does-not-exist.txt"), "x"
    ) is False, "could not check is not checked"


def test_verify_written_json_reports_false_on_invalid_json(di, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert di._verify_written_json(str(bad), {"a": 1}) is False


def test_verify_written_csv_reports_false_on_a_row_mismatch(di, tmp_path):
    """Headers match; one row's value differs. Real content mismatch."""
    p = tmp_path / "m.csv"
    p.write_text("h1,h2\n1,2\n")
    assert di._verify_written_csv(str(p), ["h1", "h2"], [[1, 3]]) is False


def test_verify_written_csv_tolerates_quoting_differences(di, tmp_path):
    """Writer quoted 'x,y'; the reader sees one cell either way."""
    p = tmp_path / "q.csv"
    p.write_text('"h1"\n"x"\n')
    assert di._verify_written_csv(str(p), ["h1"], [["x"]]) is True


def test_verify_written_csv_strips_cells_before_comparing(di, tmp_path):
    """A cell whose value carries surrounding whitespace still matches."""
    p = tmp_path / "s.csv"
    p.write_text('h1\n" x "\n')
    assert di._verify_written_csv(str(p), ["h1"], [["x"]]) is True


def test_verify_written_csv_sees_padding_as_a_difference(di, tmp_path):
    """Stripping must not swallow a real value difference."""
    p = tmp_path / "s2.csv"
    p.write_text("h1\n x \n")
    assert di._verify_written_csv(str(p), ["h1"], [["xy"]]) is False


# --------------------------------------------------------------------------
# A write that silently no-ops must report False, not True
# --------------------------------------------------------------------------

def test_a_transform_that_writes_the_wrong_thing_is_not_verified(
    di, source_txt, tmp_path, monkeypatch
):
    """The key honesty property.

    Corrupt the artifact after the real write, then let the REAL
    verifier judge it. Faking `return False` here would only prove the
    caller passes a bool through; corrupting first proves the
    comparison itself rejects content that is not what was intended.
    """
    real = di._verify_transform_output

    def _corrupt_then_verify(path, fmt, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("THE OLD CONTENT")
        return real(path, fmt, text)

    monkeypatch.setattr(di, "_verify_transform_output", _corrupt_then_verify)

    result = di.transform(source_txt, _out(tmp_path, "t.txt"), "txt")

    assert result.success is True
    assert result.verified is False, (
        "the output holds other content, yet the transform claimed it "
        "was verified"
    )


def test_edit_dest_holding_stale_content_is_not_verified(
    di, source_txt, tmp_path, monkeypatch
):
    """Same shape as above: corrupt, then run the REAL comparison."""
    real = DocumentIntelligence._verify_written_text

    def _corrupt_then_verify(path, expected):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("THE OLD CONTENT")
        return real(path, expected)

    monkeypatch.setattr(di, "_verify_written_text", _corrupt_then_verify)

    result = di.edit(source_txt, "world", "there")

    assert result.success is True, "the call itself returned without raising"
    assert result.verified is False, (
        "the artifact holds other content, yet the edit claimed it was "
        "verified"
    )


# --------------------------------------------------------------------------
# create_pdf stays excluded, on purpose
# --------------------------------------------------------------------------

def test_create_pdf_keeps_its_no_claim(di, tmp_path):
    pytest.importorskip("reportlab")
    result = di.create_pdf(_out(tmp_path, "a.pdf"), "T", "body")

    assert result.success is True, result.message
    assert result.verified is None, (
        "create_pdf is excluded by the directive; it must not fake a "
        "claim it cannot make -- and must not regress to one either"
    )


# --------------------------------------------------------------------------
# edit(docx) keeps the Item 13C behaviour
# --------------------------------------------------------------------------

def test_edit_docx_still_verifies(di, tmp_path):
    pytest.importorskip("docx")
    from genesis_os.document_intelligence import DocxDocument

    path = _out(tmp_path, "in.docx")
    document = DocxDocument()
    document.add_paragraph("draft body")
    document.save(path)

    result = di.edit(path, "draft", "final")

    assert result.success is True, result.message
    assert result.verified is True, (
        "edit(docx) lost the Item 13C read-back verification"
    )


# --------------------------------------------------------------------------
# Structural guard: no create/edit/transform return leaves verified unclaimed
# --------------------------------------------------------------------------

def test_no_write_return_leaves_verified_unclaimed():
    """AST sweep over DocumentResult the write ops construct."""
    import ast
    import pathlib

    tree = ast.parse(
        (pathlib.Path("genesis_os") / "document_intelligence.py")
        .read_text(encoding="utf-8")
    )

    for name in (
        "create_txt", "create_csv", "create_json", "create_markdown",
        "edit", "transform",
    ):
        fn = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == name),
            None,
        )
        assert fn is not None, f"{name} vanished"

        if name == "edit":
            has_readback = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in (
                    "_verify_written_text", "_verify_docx_replacement",
                )
                for n in ast.walk(fn)
            )
        else:
            has_readback = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in (
                    "_verify_written_text", "_verify_written_json",
                    "_verify_written_csv", "_verify_transform_output",
                )
                for n in ast.walk(fn)
            )
        assert has_readback, f"{name}: no read-back wired in"

        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "DocumentResult"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value is not True:
                continue
            named = any(kw.arg == "verified" for kw in node.keywords)
            if not named:
                entries = ast.unparse(node)
                raise AssertionError(
                    f"{name}:{node.lineno}: success=True without "
                    f"verified= -- {entries[:120]}"
                )
