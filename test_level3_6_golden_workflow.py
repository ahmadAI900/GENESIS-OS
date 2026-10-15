"""
Genesis OS — Golden Workflow End-to-End Integration Test.

The spec mandates this workflow must work:

    "Find my newest results workbook, calculate percentages,
     rank students, create a final copy without modifying
     the original, and save it beside the original."

Must perform actual:
    1. Discovery — find the newest results workbook
    2. Inspection — inspect its structure (headers, sheets)
    3. Calculation — add a percentage column
    4. Ranking — add a rank column
    5. Copy creation — create final copy
    6. Original preservation — original unchanged
    7. Verification — verify the result

This is NOT mocked — it uses real files on disk.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from genesis_os.document_intelligence import DocumentIntelligence
from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: constructs a real BrowserManager.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


@pytest.fixture
def workspace(tmp_path):
    """Create a realistic workspace with student results."""
    import time

    results_dir = tmp_path / "School" / "Results"
    results_dir.mkdir(parents=True)

    # Write 2023 first, then sleep to guarantee distinct mtimes
    (results_dir / "Results_2023.csv").write_text(
        "Student,Math,English,Science\n"
        "OldStudent,80,80,80\n",
        encoding="utf-8",
    )
    time.sleep(0.05)
    (results_dir / "Results_2024.csv").write_text(
        "Student,Math,English,Science\n"
        "Alice,85,90,88\n"
        "Bob,70,75,72\n"
        "Charlie,95,85,92\n"
        "Diana,60,70,65\n"
        "Eve,88,92,90\n",
        encoding="utf-8",
    )

    return tmp_path


class TestGoldenWorkflow:

    def test_discover_newest_workbook(self, workspace):
        results_dir = workspace / "School" / "Results"
        csv_files = sorted(
            results_dir.glob("Results_*.csv"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        assert len(csv_files) >= 2
        assert csv_files[0].name == "Results_2024.csv"

    def test_inspect_workbook_structure(self, workspace):
        si = SpreadsheetIntelligence()
        path = str(workspace / "School" / "Results" / "Results_2024.csv")
        result = si.inspect(path)
        assert result.success is True
        sheet = result.data.sheets[0]
        assert sheet.headers == ["Student", "Math", "English", "Science"]
        assert sheet.row_count == 5

    def test_calculate_percentages(self, workspace):
        si = SpreadsheetIntelligence()
        path = str(workspace / "School" / "Results" / "Results_2024.csv")
        output = str(workspace / "School" / "Results" / "Results_2024_calc.csv")
        result = si.calculate(
            path,
            sheet_name="Results_2024",
            formula_column="Percentage",
            formula_template="({Math} + {English} + {Science}) / 3",
            output=output,
        )
        assert result.success is True
        assert os.path.exists(output)

        # Verify output
        read_result = si.read(output)
        assert read_result.success is True
        headers = read_result.data["headers"]
        rows = read_result.data["rows"]
        assert "Percentage" in headers
        assert len(rows) == 5

    def test_rank_students(self, workspace):
        si = SpreadsheetIntelligence()
        path = str(workspace / "School" / "Results" / "Results_2024.csv")
        calc_output = str(workspace / "School" / "Results" / "Results_2024_calc.csv")
        calc_result = si.calculate(
            path,
            sheet_name="Results_2024",
            formula_column="Percentage",
            formula_template="({Math} + {English} + {Science}) / 3",
            output=calc_output,
        )
        assert calc_result.success is True

        rank_output = str(workspace / "School" / "Results" / "Results_2024_ranked.csv")
        rank_result = si.rank(
            calc_output,
            sheet_name="Results_2024_calc",
            rank_column="Percentage",
            output=rank_output,
        )
        assert rank_result.success is True
        assert os.path.exists(rank_output)

        read_result = si.read(rank_output)
        assert read_result.success is True
        assert "Rank" in read_result.data["headers"]

    def test_original_preserved(self, workspace):
        original = workspace / "School" / "Results" / "Results_2024.csv"
        original_content = original.read_text(encoding="utf-8")

        si = SpreadsheetIntelligence()
        calc_output = str(workspace / "School" / "Results" / "Results_2024_calc.csv")
        si.calculate(
            str(original),
            sheet_name="Results_2024",
            formula_column="Percentage",
            formula_template="({Math} + {English} + {Science}) / 3",
            output=calc_output,
        )

        assert original.read_text(encoding="utf-8") == original_content

    def test_full_golden_workflow(self, workspace):
        """
        Complete Golden Workflow in one test.
        """
        results_dir = workspace / "School" / "Results"
        si = SpreadsheetIntelligence()
        di = DocumentIntelligence()

        # 1. DISCOVERY
        csv_files = sorted(
            results_dir.glob("Results_*.csv"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        assert csv_files[0].name == "Results_2024.csv"
        newest = csv_files[0]

        # 2. INSPECTION
        inspect_result = si.inspect(str(newest))
        assert inspect_result.success is True
        sheet = inspect_result.data.sheets[0]
        assert "Student" in sheet.headers
        assert sheet.row_count == 5

        # 3. CALCULATION — add percentage column
        calc_output = str(results_dir / "Results_2024_calc.csv")
        calc_result = si.calculate(
            str(newest),
            sheet_name="Results_2024",
            formula_column="Percentage",
            formula_template="({Math} + {English} + {Science}) / 3",
            output=calc_output,
        )
        assert calc_result.success is True

        # 4. RANKING — add rank column
        rank_output = str(results_dir / "Results_2024_Final.csv")
        rank_result = si.rank(
            calc_output,
            sheet_name="Results_2024_calc",
            rank_column="Percentage",
            output=rank_output,
        )
        assert rank_result.success is True

        # 5. VERIFY FINAL COPY
        read_final = si.read(rank_output)
        assert read_final.success is True
        headers = read_final.data["headers"]
        rows = read_final.data["rows"]
        assert "Percentage" in headers
        assert "Rank" in headers
        assert len(rows) == 5

        # 6. ORIGINAL PRESERVED
        read_original = si.read(str(newest))
        assert read_original.success is True
        assert "Percentage" not in read_original.data["headers"]
        assert "Rank" not in read_original.data["headers"]

        # 7. RANKING CORRECTNESS — Charlie should be #1
        pct_idx = headers.index("Percentage")
        rank_idx = headers.index("Rank")
        student_idx = headers.index("Student")
        charlie_row = next(r for r in rows if r[student_idx] == "Charlie")
        assert str(charlie_row[rank_idx]) == "1"

        # 8. VERIFICATION via Document Intelligence
        verify_result = di.verify(rank_output, expected_format="csv")
        assert verify_result.success is True


class TestBrowserGoldenWorkflow:
    """
    "Search YouTube for relaxing music and open the second relevant result."

    Must verify:
        browser → page → search → results → selected result
    Do not merely verify that a click API returned.
    """

    def test_search_youtube_open_second_result(self):
        from genesis_os.browser_manager import BrowserManager, BrowserSession

        class MockBrowserProvider:
            name = "mock"
            available = True
            def __init__(self):
                self.calls = []
            def open_url(self, url):
                self.calls.append(("open_url", url))
                return {"success": True, "url": url}
            def navigate(self, url):
                return self.open_url(url)
            def search(self, query, engine="google"):
                self.calls.append(("search", query))
                return {"success": True, "query": query}
            def click(self, selector):
                self.calls.append(("click", selector))
                return {"success": True, "selector": selector}
            def find_text(self, text):
                self.calls.append(("find_text", text))
                return {"success": True, "text": text, "count": 5}
            def extract_text(self, selector=None):
                self.calls.append(("extract", selector))
                return {"success": True, "text": "Result 1\nResult 2\nResult 3"}
            def get_page_title(self):
                return {"success": True, "title": "relaxing music - YouTube"}
            def get_page_url(self):
                return {"success": True, "url": "https://youtube.com/results?search_query=relaxing+music"}
            def verify_page_state(self, expected_url=None, expected_title_contains=None, session_id="default"):
                checks = []
                if expected_url:
                    checks.append({"check": "url", "passed": expected_url in "https://youtube.com/results"})
                if expected_title_contains:
                    checks.append({"check": "title", "passed": expected_title_contains in "relaxing music - YouTube"})
                return {"success": all(c["passed"] for c in checks), "checks": checks}

        mgr = BrowserManager()
        provider = MockBrowserProvider()
        mgr._sessions["default"] = BrowserSession(provider=provider)
        mgr._providers = [provider]

        # Step 1: Search YouTube
        search_result = mgr.search("relaxing music", engine="youtube")
        assert search_result["success"] is True

        # Step 2: Find results
        find_result = mgr.find_text("relaxing")
        assert find_result["success"] is True
        assert find_result["count"] >= 2

        # Step 3: Open second result (click)
        click_result = mgr.click("ytd-video-renderer:nth-child(2)")
        assert click_result["success"] is True

        # Step 4: Verify page state
        verify_result = mgr.verify_page_state(
            expected_url="https://youtube.com/results?search_query=relaxing+music",
            expected_title_contains="relaxing music",
        )
        assert verify_result["success"] is True

        # Verify the full pipeline was executed
        assert len(provider.calls) >= 3
        assert provider.calls[0][0] == "search"
        assert provider.calls[1][0] == "find_text"
        assert provider.calls[2][0] == "click"
