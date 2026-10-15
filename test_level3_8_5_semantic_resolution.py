"""
Genesis OS — Level 3.8.5
Real-World Filesystem Resolution Integration Tests.

These tests create ACTUAL files on disk and verify that:
1. SemanticQueryParser correctly extracts preferences from natural language
2. FileTargetProvider resolves semantic references to real filesystem objects
3. Recency-first sorting works for "newest"/"latest" queries
4. Location hints narrow search correctly
5. Extension filtering works end-to-end
6. Multi-step references resolve correctly

NO mocking of filesystem operations.
NO fake execution.
"""

import time
from pathlib import Path

import pytest

from genesis_os.semantic_query_parser import SemanticQueryParser, ParsedSemanticQuery
from genesis_os.file_target_provider import FileTargetProvider
from genesis_os.target_models import TargetQuery


# =========================================================
# FIXTURES: Real filesystem setup
# =========================================================


@pytest.fixture
def real_fs(tmp_path):
    """Create a realistic filesystem structure for testing."""
    downloads = tmp_path / "Downloads"
    documents = tmp_path / "Documents"
    desktop = tmp_path / "Desktop"
    workspace = tmp_path / "workspace"

    for d in (downloads, documents, desktop, workspace):
        d.mkdir(parents=True, exist_ok=True)

    # Create files with known modification times
    files = {}

    # Downloads: various files
    files["report_jan"] = downloads / "report_january.xlsx"
    files["report_jan"].write_text("January report", encoding="utf-8")

    files["report_feb"] = downloads / "report_february.xlsx"
    files["report_feb"].write_text("February report", encoding="utf-8")

    files["report_mar"] = downloads / "report_march.xlsx"
    files["report_mar"].write_text("March report", encoding="utf-8")

    files["latest_csv"] = downloads / "latest_data.csv"
    files["latest_csv"].write_text("a,b,c", encoding="utf-8")

    files["old_pdf"] = downloads / "old_manual.pdf"
    files["old_pdf"].write_text("manual content", encoding="utf-8")

    files["new_pdf"] = downloads / "new_guide.pdf"
    files["new_pdf"].write_text("guide content", encoding="utf-8")

    files["photo"] = downloads / "photo.jpg"
    files["photo"].write_text("jpeg data", encoding="utf-8")

    files["presentation"] = downloads / "quarterly_review.pptx"
    files["presentation"].write_text("pptx data", encoding="utf-8")

    # Documents folder
    files["doc_report"] = documents / "annual_report.docx"
    files["doc_report"].write_text("annual report content", encoding="utf-8")

    files["doc_notes"] = documents / "meeting_notes.txt"
    files["doc_notes"].write_text("meeting notes", encoding="utf-8")

    # Desktop
    files["shortcut"] = desktop / "important_link.txt"
    files["shortcut"].write_text("link data", encoding="utf-8")

    # Workspace
    files["script"] = workspace / "analysis.py"
    files["script"].write_text("print('hello')", encoding="utf-8")

    # Set specific mtimes to control recency ordering
    # report_jan: 10 days ago
    # report_feb: 5 days ago
    # report_mar: 1 day ago (newest)
    now = time.time()
    files["report_jan"].touch()
    files["report_feb"].touch()
    files["report_mar"].touch()
    files["latest_csv"].touch()
    files["old_pdf"].touch()
    files["new_pdf"].touch()

    import os
    os.utime(str(files["report_jan"]), (now - 10 * 86400, now - 10 * 86400))
    os.utime(str(files["report_feb"]), (now - 5 * 86400, now - 5 * 86400))
    os.utime(str(files["report_mar"]), (now - 1 * 86400, now - 1 * 86400))
    os.utime(str(files["latest_csv"]), (now - 2 * 3600, now - 2 * 3600))  # 2 hours ago
    os.utime(str(files["old_pdf"]), (now - 90 * 86400, now - 90 * 86400))  # 90 days ago
    os.utime(str(files["new_pdf"]), (now - 3 * 3600, now - 3 * 3600))  # 3 hours ago

    return {
        "tmp_path": tmp_path,
        "downloads": downloads,
        "documents": documents,
        "desktop": desktop,
        "workspace": workspace,
        "files": files,
    }


# =========================================================
# 1. SEMANTIC QUERY PARSER TESTS
# =========================================================


class TestSemanticQueryParser:
    """Verify SemanticQueryParser extracts structured preferences from NL."""

    def setup_method(self):
        self.parser = SemanticQueryParser()

    def test_parse_empty_string(self):
        result = self.parser.parse("")
        assert result.name_terms == ()
        assert result.extension is None
        assert result.recency is None

    def test_parse_my_latest_pdf(self):
        result = self.parser.parse("my latest PDF")
        assert result.recency == "latest"
        assert result.extension == ".pdf"
        assert result.file_type == "pdf"

    def test_parse_newest_spreadsheet(self):
        result = self.parser.parse("the newest spreadsheet")
        assert result.recency == "newest"
        assert result.extension == ".xlsx"
        assert result.file_type == "spreadsheet"

    def test_parse_most_recent_document(self):
        result = self.parser.parse("the most recent document")
        assert result.recency == "most_recent"
        assert result.extension == ".docx"
        assert result.file_type == "document"

    def test_parse_report_edited_yesterday(self):
        result = self.parser.parse("the report I edited yesterday")
        assert result.recency == "yesterday"
        assert "report" in result.name_terms

    def test_parse_in_downloads(self):
        result = self.parser.parse("my latest PDF in Downloads")
        assert result.recency == "latest"
        assert result.extension == ".pdf"
        assert result.location == "downloads"

    def test_parse_in_documents(self):
        result = self.parser.parse("the newest spreadsheet in Documents")
        assert result.recency == "newest"
        assert result.location == "documents"

    def test_parse_beside_original(self):
        result = self.parser.parse("save beside the original")
        assert result.relative_to == "original"
        assert result.concept == "original"

    def test_parse_next_to_copy(self):
        result = self.parser.parse("save next to the copy")
        assert result.relative_to == "the copy"
        assert result.concept == "copy"

    def test_parse_same_folder_as_report(self):
        result = self.parser.parse("same folder as report.xlsx")
        assert result.relative_to == "report.xlsx"

    def test_parse_the_original(self):
        result = self.parser.parse("open the original")
        assert result.concept == "original"

    def test_parse_the_backup(self):
        result = self.parser.parse("find the backup")
        assert result.concept == "backup"

    def test_parse_oldest_file(self):
        result = self.parser.parse("the oldest file")
        assert result.recency == "oldest"

    def test_parse_first_image(self):
        result = self.parser.parse("the first image")
        assert result.recency == "first"
        assert result.file_type == "image"

    def test_parse_last_week(self):
        result = self.parser.parse("files from last week")
        assert result.recency == "last_week"

    def test_parse_literal_extension(self):
        result = self.parser.parse("the file report.xlsx")
        assert result.extension == ".xlsx"

    def test_parse_to_dict(self):
        result = self.parser.parse("my latest PDF")
        data = result.to_dict()
        assert isinstance(data, dict)
        assert data["recency"] == "latest"
        assert data["extension"] == ".pdf"

    def test_parse_complex_query(self):
        result = self.parser.parse(
            "find the newest spreadsheet in Downloads"
        )
        assert result.recency == "newest"
        assert result.extension == ".xlsx"
        assert result.location == "downloads"
        assert result.file_type == "spreadsheet"

    def test_parse_with_csv_type(self):
        result = self.parser.parse("the latest CSV file")
        assert result.recency == "latest"
        assert result.extension == ".csv"
        assert result.file_type == "spreadsheet"


# =========================================================
# 2. FILE TARGET PROVIDER: RECENCY-ORDERED DISCOVERY
# =========================================================


class TestFileTargetProviderRecency:
    """Verify FileTargetProvider resolves recency queries to correct files."""

    def _make_provider(self, real_fs):
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
            real_fs["documents"],
            real_fs["desktop"],
            real_fs["workspace"],
        ])
        return provider

    def test_newest_spreadsheet_resolves_to_march(self, real_fs):
        """'newest spreadsheet' should resolve to report_march.xlsx (most recent)."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(
            text="newest spreadsheet",
            target_type="file",
            recency_preference="newest",
            extension=".xlsx",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        # The newest .xlsx should be report_march.xlsx
        assert "report_march" in candidates[0].display_name

    def test_newest_csv_resolves_to_latest_data(self, real_fs):
        """'newest CSV' should resolve to latest_data.csv."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(
            text="newest CSV",
            target_type="file",
            recency_preference="newest",
            extension=".csv",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        assert "latest_data" in candidates[0].display_name

    def test_oldest_report_resolves_to_january(self, real_fs):
        """'oldest report' should resolve to report_january.xlsx."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(
            text="oldest report",
            target_type="file",
            recency_preference="oldest",
            extension=".xlsx",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        assert "report_january" in candidates[0].display_name

    def test_latest_pdf_resolves_to_new_guide(self, real_fs):
        """'latest PDF' should resolve to new_guide.pdf (most recent)."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(
            text="latest PDF",
            target_type="file",
            recency_preference="latest",
            extension=".pdf",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        assert "new_guide" in candidates[0].display_name

    def test_recency_boost_applied(self, real_fs):
        """Top candidate for recency queries should have recency_boosted flag."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(
            text="newest spreadsheet",
            target_type="file",
            recency_preference="newest",
            extension=".xlsx",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        assert candidates[0].metadata.get("recency_boosted") is True

    def test_extension_filter_works(self, real_fs):
        """Only .xlsx files should appear when extension is .xlsx."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(
            text="report",
            target_type="file",
            extension=".xlsx",
        )
        candidates = provider.discover(query)
        for c in candidates:
            assert c.metadata.get("extension") == ".xlsx"

    def test_name_matching_works(self, real_fs):
        """'report' should match files with 'report' in their name."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(text="report", target_type="file")
        candidates = provider.discover(query)
        assert len(candidates) >= 3  # jan, feb, mar reports
        for c in candidates:
            assert "report" in c.display_name.lower()


# =========================================================
# 3. FILE TARGET PROVIDER: LOCATION-HINT NARROWING
# =========================================================


class TestFileTargetProviderLocation:
    """Verify location hints narrow search correctly."""

    def _make_provider(self, real_fs):
        return FileTargetProvider(search_roots=[
            real_fs["downloads"],
            real_fs["documents"],
            real_fs["desktop"],
            real_fs["workspace"],
        ])

    def test_location_hint_downloads(self, real_fs):
        """Location hint 'downloads' should prioritize Downloads folder."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(
            text="report",
            target_type="file",
            location_hint="downloads",
        )
        candidates = provider.discover(query)
        # All candidates should come from Downloads
        downloads_str = str(real_fs["downloads"].resolve())
        for c in candidates:
            assert c.metadata.get("parent") == downloads_str

    def test_location_hint_documents(self, real_fs):
        """Location hint 'documents' should find docx/txt files in Documents."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(
            text="report",
            target_type="file",
            location_hint="documents",
        )
        candidates = provider.discover(query)
        documents_str = str(real_fs["documents"].resolve())
        for c in candidates:
            assert c.metadata.get("parent") == documents_str

    def test_no_location_hint_searches_all_roots(self, real_fs):
        """Without location hint, all search roots are searched."""
        provider = self._make_provider(real_fs)
        query = TargetQuery(text="report", target_type="file")
        candidates = provider.discover(query)
        parents = {c.metadata.get("parent") for c in candidates}
        downloads_str = str(real_fs["downloads"].resolve())
        assert downloads_str in parents


# =========================================================
# 4. INTEGRATION: SEMANTIC PARSER + FILE PROVIDER
# =========================================================


class TestSemanticParserIntegration:
    """Integration tests combining SemanticQueryParser + FileTargetProvider."""

    def test_natural_language_latest_csv(self, real_fs):
        """'my latest CSV' should resolve to latest_data.csv via semantic parsing."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
            real_fs["documents"],
        ])
        query = TargetQuery(
            text="my latest CSV",
            target_type="file",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        assert "latest_data" in candidates[0].display_name

    def test_natural_language_newest_pdf_in_downloads(self, real_fs):
        """'the newest PDF in Downloads' resolves to new_guide.pdf."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
            real_fs["documents"],
        ])
        query = TargetQuery(
            text="the newest PDF in Downloads",
            target_type="file",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        assert "new_guide" in candidates[0].display_name

    def test_natural_language_oldest_excel(self, real_fs):
        """'the oldest Excel file' resolves to report_january.xlsx."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(
            text="the oldest Excel file",
            target_type="file",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        assert "report_january" in candidates[0].display_name

    def test_string_query_semantic_parsing(self, real_fs):
        """String queries are also parsed through SemanticQueryParser."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        candidates = provider.discover("my latest CSV")
        assert len(candidates) > 0
        assert "latest_data" in candidates[0].display_name


# =========================================================
# 5. REAL FILESYSTEM STATE VERIFICATION
# =========================================================


class TestRealFilesystemVerification:
    """Verify actual filesystem state after resolution."""

    def test_resolved_target_path_exists_on_disk(self, real_fs):
        """The resolved target value must point to a real file on disk."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(
            text="newest spreadsheet",
            target_type="file",
            recency_preference="newest",
            extension=".xlsx",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0

        resolved_path = Path(candidates[0].value)
        assert resolved_path.exists(), f"Resolved path does not exist: {resolved_path}"
        assert resolved_path.is_file(), f"Resolved path is not a file: {resolved_path}"

    def test_resolved_target_matches_expected_name(self, real_fs):
        """The resolved filename should match the expected newest .xlsx."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(
            text="newest spreadsheet",
            target_type="file",
            recency_preference="newest",
            extension=".xlsx",
        )
        candidates = provider.discover(query)
        assert len(candidates) > 0
        assert candidates[0].display_name == "report_march.xlsx"

    def test_resolved_candidate_has_metadata(self, real_fs):
        """Resolved candidates should have extension, parent, and mtime metadata."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(text="report", target_type="file")
        candidates = provider.discover(query)
        assert len(candidates) > 0
        meta = candidates[0].metadata
        assert "extension" in meta
        assert "parent" in meta
        assert "mtime" in meta

    def test_multiple_candidates_ranked_by_recency(self, real_fs):
        """For recency queries, candidates should be ranked newest-first."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(
            text="report xlsx",
            target_type="file",
            recency_preference="newest",
            extension=".xlsx",
        )
        candidates = provider.discover(query)
        assert len(candidates) >= 3
        # Verify ordering: march (1 day) > feb (5 days) > jan (10 days)
        mtimes = [c.metadata.get("mtime", 0) for c in candidates]
        assert mtimes == sorted(mtimes, reverse=True), \
            "Candidates should be sorted newest-first"

    def test_direct_path_resolution(self, real_fs):
        """Direct path to an existing file should resolve with high confidence."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        file_path = str(real_fs["files"]["report_mar"])
        candidates = provider.discover(file_path)
        assert len(candidates) > 0
        assert candidates[0].confidence >= 0.95
        assert candidates[0].source == "direct_path"

    def test_empty_query_returns_nothing(self, real_fs):
        """Empty query should return no candidates."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        candidates = provider.discover("")
        assert len(candidates) == 0

    def test_unmatched_query_returns_nothing(self, real_fs):
        """Query for non-existent file type returns no candidates."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(
            text="nonexistent_unicorn_xyz",
            target_type="file",
        )
        candidates = provider.discover(query)
        # Should return nothing or very low confidence
        for c in candidates:
            assert c.confidence < 0.5 or "nonexistent" in c.display_name.lower()


# =========================================================
# 6. REGRESSION: Existing behavior preserved
# =========================================================


class TestRegressionPreservation:
    """Ensure existing FileTargetProvider behavior is preserved."""

    def test_discover_with_target_query_object(self, real_fs):
        """TargetQuery objects still work as before."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(text="report", target_type="file")
        candidates = provider.discover(query)
        assert isinstance(candidates, tuple)
        assert all(c.target_type == "file" for c in candidates)

    def test_discover_with_string(self, real_fs):
        """String queries still work as before."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        candidates = provider.discover("report")
        assert isinstance(candidates, tuple)

    def test_score_above_threshold(self, real_fs):
        """Files matching query terms should score above 0.40."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(text="report", target_type="file")
        candidates = provider.discover(query)
        assert all(c.confidence > 0.40 for c in candidates)

    def test_confidence_bounded(self, real_fs):
        """Confidence should never exceed 1.0."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(text="report", target_type="file")
        candidates = provider.discover(query)
        assert all(0.0 <= c.confidence <= 1.0 for c in candidates)

    def test_no_duplicate_candidates(self, real_fs):
        """No path should appear twice in candidates."""
        provider = FileTargetProvider(search_roots=[
            real_fs["downloads"],
        ])
        query = TargetQuery(text="report", target_type="file")
        candidates = provider.discover(query)
        paths = [c.value for c in candidates]
        assert len(paths) == len(set(paths))
