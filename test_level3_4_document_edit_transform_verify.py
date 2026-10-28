"""
Genesis OS — Level 3 Document Edit / Transform / Verify Tests.

Tests the newly added document intelligence operations.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from genesis_os.document_intelligence import DocumentIntelligence, DocumentFormat


# =========================================================
# FIXTURES
# =========================================================


@pytest.fixture
def doc_intel():
    return DocumentIntelligence()


@pytest.fixture
def sample_txt(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("Hello World\nThis is a test document.\nGoodbye World\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_csv(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("Name,Age\nAlice,30\nBob,25\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_json(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"key": "value", "number": 42}), encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_md(tmp_path):
    path = tmp_path / "readme.md"
    path.write_text("# Title\n\nSome content here.\n\n## Section\n\nMore text.\n", encoding="utf-8")
    return str(path)


# =========================================================
# EDIT TESTS
# =========================================================


class TestDocumentEdit:
    def test_edit_txt_replace(self, doc_intel, sample_txt):
        before = open(sample_txt, encoding="utf-8").read()
        result = doc_intel.edit(sample_txt, "Hello", "Hi")
        assert result.success is True
        assert result.operation == "edit"
        assert "1 occurrence" in result.message
        assert result.path != os.path.abspath(sample_txt)

        # Original preserved; replacement landed in the sibling output.
        assert open(sample_txt, encoding="utf-8").read() == before
        content = open(result.path, encoding="utf-8").read()
        assert "Hi World" in content
        assert "Hello World" not in content

    def test_edit_multiple_occurrences(self, doc_intel, sample_txt):
        before = open(sample_txt, encoding="utf-8").read()
        result = doc_intel.edit(sample_txt, "World", "Planet")
        assert result.success is True
        assert "2 occurrence" in result.message

        assert open(sample_txt, encoding="utf-8").read() == before
        content = open(result.path, encoding="utf-8").read()
        assert "Hello Planet" in content
        assert "Goodbye Planet" in content

    def test_edit_text_not_found(self, doc_intel, sample_txt):
        result = doc_intel.edit(sample_txt, "NONEXISTENT", "replacement")
        assert result.success is False
        assert result.error == "TextNotFound"

    def test_edit_file_not_found(self, doc_intel, tmp_path):
        result = doc_intel.edit(str(tmp_path / "missing.txt"), "a", "b")
        assert result.success is False
        assert result.error == "FileNotFoundError"

    def test_edit_csv(self, doc_intel, sample_csv):
        before = open(sample_csv, encoding="utf-8").read()
        result = doc_intel.edit(sample_csv, "Alice", "Alicia")
        assert result.success is True
        assert open(sample_csv, encoding="utf-8").read() == before
        content = open(result.path, encoding="utf-8").read()
        assert "Alicia" in content

    def test_edit_json(self, doc_intel, sample_json):
        before = open(sample_json, encoding="utf-8").read()
        result = doc_intel.edit(sample_json, "value", "new_value")
        assert result.success is True
        assert open(sample_json, encoding="utf-8").read() == before
        content = open(result.path, encoding="utf-8").read()
        assert "new_value" in content

    def test_edit_markdown(self, doc_intel, sample_md):
        before = open(sample_md, encoding="utf-8").read()
        result = doc_intel.edit(sample_md, "Title", "My Document")
        assert result.success is True
        assert open(sample_md, encoding="utf-8").read() == before
        content = open(result.path, encoding="utf-8").read()
        assert "My Document" in content


# =========================================================
# TRANSFORM TESTS
# =========================================================


class TestDocumentTransform:
    def test_transform_txt_to_html(self, doc_intel, sample_txt, tmp_path):
        output = str(tmp_path / "output.html")
        result = doc_intel.transform(sample_txt, output, "html")
        assert result.success is True
        assert result.operation == "transform"
        assert os.path.exists(output)
        content = open(output, encoding="utf-8").read()
        assert "<html>" in content

    def test_transform_txt_to_json(self, doc_intel, sample_txt, tmp_path):
        output = str(tmp_path / "output.json")
        result = doc_intel.transform(sample_txt, output, "json")
        assert result.success is True
        assert os.path.exists(output)
        data = json.loads(open(output, encoding="utf-8").read())
        assert "content" in data

    def test_transform_txt_to_markdown(self, doc_intel, sample_txt, tmp_path):
        output = str(tmp_path / "output.md")
        result = doc_intel.transform(sample_txt, output, "markdown")
        assert result.success is True
        assert os.path.exists(output)

    def test_transform_csv_to_txt(self, doc_intel, sample_csv, tmp_path):
        output = str(tmp_path / "output.txt")
        result = doc_intel.transform(sample_csv, output, "txt")
        assert result.success is True
        assert os.path.exists(output)

    def test_transform_file_not_found(self, doc_intel, tmp_path):
        result = doc_intel.transform(str(tmp_path / "missing.txt"), str(tmp_path / "out.txt"), "txt")
        assert result.success is False
        assert result.error == "FileNotFoundError"

    def test_transform_creates_output_directory(self, doc_intel, sample_txt, tmp_path):
        output = str(tmp_path / "subdir" / "output.html")
        result = doc_intel.transform(sample_txt, output, "html")
        assert result.success is True
        assert os.path.exists(output)


# =========================================================
# VERIFY TESTS
# =========================================================


class TestDocumentVerify:
    def test_verify_existing_file(self, doc_intel, sample_txt):
        result = doc_intel.verify(sample_txt)
        assert result.success is True
        assert result.operation == "verify"
        assert result.data["all_passed"] is True

    def test_verify_with_expected_format(self, doc_intel, sample_txt):
        result = doc_intel.verify(sample_txt, expected_format="txt")
        assert result.success is True

    def test_verify_with_wrong_format(self, doc_intel, sample_txt):
        result = doc_intel.verify(sample_txt, expected_format="pdf")
        assert result.success is False
        assert any(c["check"] == "format" and not c["passed"] for c in result.data["checks"])

    def test_verify_with_expected_content(self, doc_intel, sample_txt):
        result = doc_intel.verify(sample_txt, expected_content="Hello World")
        assert result.success is True

    def test_verify_with_missing_content(self, doc_intel, sample_txt):
        result = doc_intel.verify(sample_txt, expected_content="NONEXISTENT TEXT")
        assert result.success is False
        assert any(c["check"] == "content" and not c["passed"] for c in result.data["checks"])

    def test_verify_nonexistent_file(self, doc_intel, tmp_path):
        result = doc_intel.verify(str(tmp_path / "missing.txt"))
        assert result.success is False

    def test_verify_all_checks_combined(self, doc_intel, sample_txt):
        result = doc_intel.verify(
            sample_txt,
            expected_content="Hello World",
            expected_format="txt",
        )
        assert result.success is True
        assert len(result.data["checks"]) >= 3  # exists, readable, format, content


# =========================================================
# ACTION EXECUTOR DISPATCH
# =========================================================


class TestActionExecutorDocumentEdit:
    def test_document_edit_dispatched(self, workspace_root):
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_mgr = MagicMock()
        os_mgr.doc_edit.return_value = {"success": True, "operation": "document.edit"}
        executor = ActionExecutor(os_mgr)

        plan = ActionPlan(
            operation="document.edit",
            target=str(workspace_root / "doc.txt"),
            parameters={"find_text": "old", "replace_text": "new", "confirmed": True},
            confidence=0.95,
        )
        result = executor.execute(plan)
        assert result.success is True
        os_mgr.doc_edit.assert_called_once()


class TestActionExecutorDocumentTransform:
    def test_document_transform_dispatched(self, workspace_root):
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        out = workspace_root / "doc.html"
        os_mgr = MagicMock()
        os_mgr.doc_transform.return_value = {"success": True, "operation": "document.transform"}
        executor = ActionExecutor(os_mgr)

        plan = ActionPlan(
            operation="document.transform",
            target=str(workspace_root / "doc.txt"),
            parameters={"output_path": str(out), "output_format": "html", "confirmed": True},
            confidence=0.95,
        )
        result = executor.execute(plan)
        assert result.success is True
        os_mgr.doc_transform.assert_called_once()

    def test_document_transform_outside_the_workspace_requires_a_grant(self, tmp_path, workspace_root):
        """Bucket (b) counterpart for the transform test above.

        Note the plan carries `confirmed: True`. That alone does NOT
        unlock an out-of-workspace write -- that is attack A6, and this
        test keeps it covered on the document path specifically.
        """
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan, attach_authorization
        from genesis_os.approval_store import ApprovalStore
        from genesis_os.authorization_grant import issue_authorization_grant

        src = tmp_path / "doc.txt"
        src.write_text("hello")
        out = tmp_path / "doc.html"

        os_mgr = MagicMock()
        os_mgr.doc_transform.return_value = {
            "success": True, "operation": "document.transform",
        }
        plan = ActionPlan(
            operation="document.transform",
            target=str(src),
            parameters={
                "output_path": str(out), "output_format": "html",
                "confirmed": True,
            },
            confidence=0.95,
        )
        result = ActionExecutor(os_mgr).execute(plan)
        assert result.status == "confirmation_required"
        assert result.executed is False
        os_mgr.doc_transform.assert_not_called()

        # The grant must cover the WHOLE plan: `target` (the source) is also
        # a scanned path for document capabilities, so approving only the
        # output leaves an uncovered path behind.
        args = {"output_path": str(out), "target": str(src)}
        token = ApprovalStore.issue_token("document.transform", args)
        ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
        granted = attach_authorization(
            plan, issue_authorization_grant(
                operation="document.transform", arguments=args, token=token,
            ), arguments=args,
        )
        result2 = ActionExecutor(os_mgr).execute(granted)
        assert result2.status != "confirmation_required"
        os_mgr.doc_transform.assert_called_once()


class TestActionExecutorDocumentVerify:
    def test_document_verify_dispatched(self, workspace_root):
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_mgr = MagicMock()
        os_mgr.doc_verify.return_value = {"success": True, "operation": "document.verify"}
        executor = ActionExecutor(os_mgr)

        plan = ActionPlan(
            operation="document.verify",
            target=str(workspace_root / "doc.txt"),
            parameters={},
            confidence=0.95,
        )
        result = executor.execute(plan)
        assert result.success is True
        os_mgr.doc_verify.assert_called_once()


# Need this import for the dispatch tests
from unittest.mock import MagicMock
