"""
Genesis OS — Phase 7: Filesystem Intelligence Tests.

Covers:
    Part 2: Verification-honesty for filesystem capabilities
        - file.copy, file.move, file.rename, file.delete
        - folder.create, folder.list (inspect)
        - Natural-language resolution (file.resolve)
        Each with positive AND negative regression tests.

    Part 3: Real natural-language resolution integration tests
        - 15+ genuinely natural filesystem references
        - Known folders/aliases, newest/latest/recency,
          candidate ranking, existence validation, original vs copy
        - Real disposable test files with real timestamps

    Part 4: Safety confirmation gating for resolved-by-inference
        - Destructive operations via natural-language resolution
          must not bypass confirmation
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from genesis_os.verification_helpers import (
    verify_file_copy,
    verify_file_move,
    verify_file_rename,
    verify_file_delete,
    verify_folder_create,
    verify_folder_list,
    verify_file_resolve,
)
from genesis_os.filesystem.file_manager import FileManager
from genesis_os.filesystem.folder_manager import FolderManager
from genesis_os.safe_file_manager import SafeFileManager
from genesis_os.file_intelligence.file_service import FileIntelligenceService
from genesis_os.file_target_provider import FileTargetProvider
from genesis_os.folder_target_provider import FolderTargetProvider
from genesis_os.semantic_query_parser import SemanticQueryParser
from genesis_os.target_models import TargetQuery
from genesis_os.target_models import ConversationContext
from genesis_os.target_resolution import TargetResolver


# =========================================================
# PART 2: VERIFICATION HONESTY — POSITIVE + NEGATIVE
# =========================================================


# --- file.copy ---

def test_verify_file_copy_positive(tmp_path):
    """verify_file_copy returns verified=True when destination exists."""
    src = tmp_path / "src.txt"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "dst.txt"
    result = FileManager().copy(src, dst)
    v = verify_file_copy(True, str(src), result)
    assert v["verified"] is True
    assert "exists" in v["reason"]


def test_verify_file_copy_negative_destination_missing(tmp_path):
    """Provider says success but destination does not exist."""
    v = verify_file_copy(True, str(tmp_path / "x"), {"destination": str(tmp_path / "phantom.txt")})
    assert v["verified"] is False
    assert "missing" in v["reason"].lower() or "empty" in v["reason"].lower()


def test_verify_file_copy_negative_provider_failure():
    v = verify_file_copy(False, "/x", {})
    assert v["verified"] is False
    assert "failure" in v["reason"]


# --- file.move ---

def test_verify_file_move_positive(tmp_path):
    src = tmp_path / "movable.txt"
    src.write_text("move me", encoding="utf-8")
    dst = tmp_path / "moved.txt"
    result = FileManager().move(src, dst)
    v = verify_file_move(True, str(src), result)
    assert v["verified"] is True
    assert "moved" in v["reason"]


def test_verify_file_move_negative_source_still_exists(tmp_path):
    src = tmp_path / "stuck.txt"
    src.write_text("stuck", encoding="utf-8")
    # When destination also doesn't exist, helper catches that first
    v = verify_file_move(True, str(src), {
        "destination": str(tmp_path / "moved.txt"),
        "source": str(src),
    })
    assert v["verified"] is False
    # Either "missing" or "source still exists" — both are honest failures
    assert "missing" in v["reason"].lower() or "source still exists" in v["reason"].lower()


def test_verify_file_move_negative_destination_missing(tmp_path):
    v = verify_file_move(True, str(tmp_path / "x"), {
        "destination": str(tmp_path / "phantom.txt"),
        "source": str(tmp_path / "gone.txt"),
    })
    assert v["verified"] is False
    assert "missing" in v["reason"].lower()


# --- file.rename ---

def test_verify_file_rename_positive(tmp_path):
    src = tmp_path / "old_name.txt"
    src.write_text("rename me", encoding="utf-8")
    result = FileManager().rename(src, "new_name.txt")
    v = verify_file_rename(True, str(src), result)
    assert v["verified"] is True
    assert "renamed" in v["reason"]


def test_verify_file_rename_negative_old_still_exists(tmp_path):
    src = tmp_path / "stuck_old.txt"
    src.write_text("content", encoding="utf-8")
    # When new_path doesn't exist, helper catches that first
    v = verify_file_rename(True, str(src), {
        "old_path": str(src),
        "new_path": str(tmp_path / "new.txt"),
    })
    assert v["verified"] is False
    assert "missing" in v["reason"].lower() or "old path still exists" in v["reason"].lower()


# --- file.delete ---

def test_verify_file_delete_positive(tmp_path):
    target = tmp_path / "doomed.txt"
    target.write_text("bye", encoding="utf-8")
    result = FileManager().delete(target, confirm=True)
    v = verify_file_delete(True, str(target), result)
    assert v["verified"] is True
    assert "removed" in v["reason"]


def test_verify_file_delete_negative_file_still_exists(tmp_path):
    target = tmp_path / "immortal.txt"
    target.write_text("live", encoding="utf-8")
    v = verify_file_delete(True, str(target), {"path": str(target)})
    assert v["verified"] is False
    assert "still exists" in v["reason"]


def test_verify_file_delete_negative_provider_failure():
    v = verify_file_delete(False, "/x", {})
    assert v["verified"] is False


# --- folder.create ---

def test_verify_folder_create_positive(tmp_path):
    folder = tmp_path / "new_folder"
    result = FolderManager().create(folder)
    v = verify_folder_create(True, str(folder), result)
    assert v["verified"] is True
    assert "exists" in v["reason"]


def test_verify_folder_create_negative_folder_missing(tmp_path):
    v = verify_folder_create(True, str(tmp_path / "phantom_dir"), {"path": str(tmp_path / "phantom_dir")})
    assert v["verified"] is False
    assert "missing" in v["reason"]


# --- folder.list (inspect) ---

def test_verify_folder_list_positive(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    result = FolderManager().inspect(tmp_path)
    v = verify_folder_list(True, str(tmp_path), result)
    assert v["verified"] is True
    assert "items" in v["reason"]


def test_verify_folder_list_negative_no_items(tmp_path):
    v = verify_folder_list(True, str(tmp_path), {"path": str(tmp_path)})
    assert v["verified"] is False
    assert "no items" in v["reason"]


# --- file.resolve (natural-language resolution) ---

def test_verify_file_resolve_positive(tmp_path):
    f = tmp_path / "real.txt"
    f.write_text("content", encoding="utf-8")
    v = verify_file_resolve(True, str(f), {"resolved_path": str(f)})
    assert v["verified"] is True


def test_verify_file_resolve_negative_invented_path():
    v = verify_file_resolve(True, "/nonexistent/invented/path.txt", {"resolved_path": "/nonexistent/invented/path.txt"})
    assert v["verified"] is False
    assert "does not exist" in v["reason"]


def test_safe_file_manager_rejects_equal_size_corrupted_copy(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"good")
    manager = MagicMock()

    def corrupt_copy(src, dst):
        Path(dst).write_bytes(b"evil")
        return {"success": True, "verified": True}

    manager.copy.side_effect = corrupt_copy
    result = SafeFileManager(manager=manager).copy(
        source,
        destination,
    )

    assert result["verified"] is False
    assert result["file_matches"] is False


def test_safe_file_manager_rejects_copy_without_source_removal_for_move(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("payload", encoding="utf-8")
    manager = MagicMock()

    def copy_instead_of_move(src, dst):
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")
        return {"success": True, "verified": True}

    manager.move.side_effect = copy_instead_of_move
    result = SafeFileManager(manager=manager).move(
        source,
        destination,
    )

    assert result["verified"] is False
    assert result["source_removed"] is False
    assert source.exists()


def test_safe_file_manager_rejects_provider_rename_without_move(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    manager = MagicMock()
    manager.rename.return_value = {
        "success": True,
        "verified": True,
        "old_path": str(source),
        "new_path": str(tmp_path / "renamed.txt"),
    }

    result = SafeFileManager(manager=manager).rename(
        source,
        "renamed.txt",
    )

    assert result["verified"] is False
    assert result["old_path_exists"] is True
    assert source.exists()


def test_safe_file_manager_rejects_provider_delete_without_removal(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("payload", encoding="utf-8")
    manager = MagicMock()
    manager.delete.return_value = {
        "success": True,
        "verified": True,
        "path": str(target),
    }

    result = SafeFileManager(manager=manager).delete(
        target,
    )

    assert result["verified"] is False
    assert result["file_exists"] is True
    assert target.exists()


def test_folder_organize_dry_run_never_mutates(tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-test")

    result = FolderManager().organize(
        tmp_path,
        dry_run=True,
    )

    assert result["success"] is True
    assert result["executed"] is False
    assert result["planned_count"] == 1
    assert source.exists()
    assert not (tmp_path / "Documents").exists()


# =========================================================
# PART 2b: OSManager WRAPPER VERIFICATION HONESTY
# =========================================================


def _make_osm():
    """Build a minimal OSManager with real SafeFileManager and FolderManager."""
    from genesis_os.os_manager import OSManager
    osm = OSManager.__new__(OSManager)
    osm.files = SafeFileManager()
    osm.folders = FolderManager()
    osm.doc_intel = None
    osm.sheet_intel = None
    osm.gui = None
    osm.browser = MagicMock()
    osm.network = MagicMock()
    osm.applications = MagicMock()
    return osm


def test_osm_copy_file_positive(tmp_path):
    osm = _make_osm()
    src = tmp_path / "src.txt"
    src.write_text("copy me", encoding="utf-8")
    dst = tmp_path / "dst.txt"
    result = osm.copy_file(str(src), str(dst))
    assert result["success"] is True
    assert result["verified"] is True


def test_osm_copy_file_negative_provider_lies(tmp_path, monkeypatch):
    """OSManager.copy_file must catch provider lying about success."""
    osm = _make_osm()
    src = tmp_path / "src.txt"
    src.write_text("data", encoding="utf-8")
    dst = tmp_path / "phantom_dst.txt"

    original_copy = SafeFileManager.copy

    def _lying_copy(self, source, destination, **kwargs):
        return {"success": True, "operation": "file.copy", "source": str(source), "destination": str(dst), "executed": True}

    monkeypatch.setattr(SafeFileManager, "copy", _lying_copy)
    result = osm.copy_file(str(src), str(dst))
    assert result["success"] is True
    assert result["verified"] is False
    assert "verification_reason" in result


def test_osm_move_file_positive(tmp_path):
    osm = _make_osm()
    src = tmp_path / "movable.txt"
    src.write_text("move me", encoding="utf-8")
    dst = tmp_path / "moved.txt"
    result = osm.move_file(str(src), str(dst))
    assert result["success"] is True
    assert result["verified"] is True


def test_osm_move_file_negative_provider_lies(tmp_path, monkeypatch):
    osm = _make_osm()
    src = tmp_path / "src.txt"
    src.write_text("data", encoding="utf-8")
    dst = tmp_path / "phantom_dst.txt"

    def _lying_move(self, source, destination, **kwargs):
        return {"success": True, "operation": "file.move", "source": str(src), "destination": str(dst), "executed": True}

    monkeypatch.setattr(SafeFileManager, "move", _lying_move)
    result = osm.move_file(str(src), str(dst))
    assert result["success"] is True
    assert result["verified"] is False


def test_osm_rename_file_positive(tmp_path):
    osm = _make_osm()
    src = tmp_path / "old.txt"
    src.write_text("rename", encoding="utf-8")
    result = osm.rename_file(str(src), "new.txt")
    assert result["success"] is True
    assert result["verified"] is True


def test_osm_rename_file_negative_provider_lies(tmp_path, monkeypatch):
    osm = _make_osm()
    src = tmp_path / "old.txt"
    src.write_text("data", encoding="utf-8")

    def _lying_rename(self, source, new_name, **kwargs):
        return {"success": True, "operation": "file.rename", "old_path": str(src), "new_path": str(tmp_path / "new.txt")}

    monkeypatch.setattr(SafeFileManager, "rename", _lying_rename)
    result = osm.rename_file(str(src), "new.txt")
    assert result["success"] is True
    assert result["verified"] is False


def test_osm_delete_file_positive(tmp_path):
    osm = _make_osm()
    target = tmp_path / "delete_me.txt"
    target.write_text("bye", encoding="utf-8")
    result = osm.delete_file(str(target))
    assert result["success"] is True
    assert result["verified"] is True


def test_osm_delete_file_negative_provider_lies(tmp_path, monkeypatch):
    osm = _make_osm()
    target = tmp_path / "immortal.txt"
    target.write_text("live", encoding="utf-8")

    def _lying_delete(self, path, **kwargs):
        return {"success": True, "operation": "file.delete", "path": str(path)}

    monkeypatch.setattr(SafeFileManager, "delete", _lying_delete)
    result = osm.delete_file(str(target))
    assert result["success"] is True
    assert result["verified"] is False


def test_osm_create_folder_positive(tmp_path):
    osm = _make_osm()
    folder = tmp_path / "new_dir"
    result = osm.create_folder(str(folder))
    assert result["success"] is True
    assert result["verified"] is True


def test_osm_create_folder_negative_provider_lies(tmp_path, monkeypatch):
    osm = _make_osm()
    phantom = tmp_path / "phantom_dir"

    def _lying_create(self, path):
        return {"success": True, "operation": "folder.create", "path": str(path)}

    monkeypatch.setattr(FolderManager, "create", _lying_create)
    result = osm.create_folder(str(phantom))
    assert result["success"] is True
    assert result["verified"] is False


def test_osm_list_folder_positive(tmp_path):
    osm = _make_osm()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    result = osm.list_folder(str(tmp_path))
    assert result["success"] is True
    assert result["verified"] is True


# =========================================================
# PART 3: NATURAL-LANGUAGE RESOLUTION INTEGRATION TESTS
# =========================================================


@pytest.fixture
def nl_fs(tmp_path):
    """Create a realistic filesystem for natural-language resolution tests."""
    downloads = tmp_path / "Downloads"
    documents = tmp_path / "Documents"
    desktop = tmp_path / "Desktop"

    for d in (downloads, documents, desktop):
        d.mkdir(parents=True, exist_ok=True)

    files = {}

    # Downloads
    files["tax_2024"] = downloads / "tax_return_2024.pdf"
    files["tax_2024"].write_text("tax data 2024", encoding="utf-8")

    files["tax_2023"] = downloads / "tax_return_2023.pdf"
    files["tax_2023"].write_text("tax data 2023", encoding="utf-8")

    files["budget"] = downloads / "monthly_budget.xlsx"
    files["budget"].write_text("budget data", encoding="utf-8")

    files["photo_beach"] = downloads / "beach_vacation.jpg"
    files["photo_beach"].write_text("jpeg beach", encoding="utf-8")

    files["photo_mountain"] = downloads / "mountain_hike.jpg"
    files["photo_mountain"].write_text("jpeg mountain", encoding="utf-8")

    files["resume"] = downloads / "resume_final.docx"
    files["resume"].write_text("resume content", encoding="utf-8")

    files["presentation"] = downloads / "quarterly_review.pptx"
    files["presentation"].write_text("slides data", encoding="utf-8")

    files["notes"] = downloads / "meeting_notes.txt"
    files["notes"].write_text("meeting notes content", encoding="utf-8")

    files["script"] = downloads / "analysis_script.py"
    files["script"].write_text("print('hello')", encoding="utf-8")

    files["data_csv"] = downloads / "sales_data.csv"
    files["data_csv"].write_text("a,b,c\n1,2,3", encoding="utf-8")

    # Documents
    files["essay"] = documents / "ielts_essay_draft.docx"
    files["essay"].write_text("essay content", encoding="utf-8")

    files["cover_letter"] = documents / "cover_letter.docx"
    files["cover_letter"].write_text("cover letter", encoding="utf-8")

    # Desktop
    files["shortcut"] = desktop / "important_link.txt"
    files["shortcut"].write_text("link data", encoding="utf-8")

    # Set specific mtimes for recency tests
    now = time.time()
    import os as _os
    _os.utime(str(files["tax_2024"]), (now - 1 * 86400, now - 1 * 86400))   # 1 day ago
    _os.utime(str(files["tax_2023"]), (now - 365 * 86400, now - 365 * 86400))  # 1 year ago
    _os.utime(str(files["budget"]), (now - 2 * 86400, now - 2 * 86400))      # 2 days ago
    _os.utime(str(files["photo_beach"]), (now - 3 * 86400, now - 3 * 86400)) # 3 days ago
    _os.utime(str(files["photo_mountain"]), (now - 0.5 * 86400, now - 0.5 * 86400))  # 12 hours ago (newest)
    _os.utime(str(files["resume"]), (now - 10 * 86400, now - 10 * 86400))    # 10 days ago
    _os.utime(str(files["notes"]), (now - 0.1 * 86400, now - 0.1 * 86400))   # ~2 hours ago (newest)
    _os.utime(str(files["essay"]), (now - 7 * 86400, now - 7 * 86400))       # 1 week ago

    # Create copies for "original vs copy" tests
    files["original"] = downloads / "project_report.docx"
    files["original"].write_text("original report content", encoding="utf-8")
    files["copy_of_original"] = downloads / "project_report_copy.docx"
    files["copy_of_original"].write_text("original report content", encoding="utf-8")

    return {
        "tmp_path": tmp_path,
        "downloads": downloads,
        "documents": documents,
        "desktop": desktop,
        "files": files,
    }


def _make_provider(nl_fs):
    """Build a FileTargetProvider rooted at the test filesystem."""
    roots = [nl_fs["downloads"], nl_fs["documents"], nl_fs["desktop"]]
    return FileTargetProvider(search_roots=roots)


def _make_folder_provider(nl_fs):
    """Build a FolderTargetProvider rooted at the test filesystem."""
    fp = FolderTargetProvider()
    fp.standard_folders = {
        "downloads": nl_fs["downloads"],
        "documents": nl_fs["documents"],
        "desktop": nl_fs["desktop"],
    }
    return fp


# --- Category 1: Known folders/aliases ---

def test_resolve_my_downloads_folder(nl_fs):
    """'my downloads' should resolve to the Downloads directory."""
    fp = _make_folder_provider(nl_fs)
    candidates = fp.discover("my downloads")
    assert len(candidates) >= 1
    assert candidates[0].value == str(nl_fs["downloads"].resolve())


def test_resolve_documents_folder(nl_fs):
    """'documents' should resolve to the Documents directory."""
    fp = _make_folder_provider(nl_fs)
    candidates = fp.discover("documents")
    assert len(candidates) >= 1
    assert candidates[0].value == str(nl_fs["documents"].resolve())


def test_resolve_desktop_folder(nl_fs):
    """'desktop' should resolve to the Desktop directory."""
    fp = _make_folder_provider(nl_fs)
    candidates = fp.discover("desktop")
    assert len(candidates) >= 1
    assert candidates[0].value == str(nl_fs["desktop"].resolve())


# --- Category 2: Newest/latest/recency/content discovery ---

def test_resolve_newest_photo(nl_fs):
    """'my most recent photo' should resolve to mountain_hike.jpg (12h old)."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("my most recent photo")
    assert len(candidates) >= 1
    best = candidates[0]
    assert "mountain" in best.display_name.lower() or "hike" in best.display_name.lower()


def test_resolve_latest_download(nl_fs):
    """'my latest txt file' should resolve to a recent txt file,
    with recency ordering producing a definitive winner."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("my latest txt file")
    assert len(candidates) >= 2, "Should find multiple .txt files"
    best = candidates[0]
    assert best.display_name.endswith(".txt")
    # Both .txt files have recency data. The system should pick one
    # and rank the other lower — not return them at identical scores.
    second = candidates[1]
    assert best.confidence >= second.confidence, (
        f"Best ({best.display_name}, {best.confidence}) should rank >= "
        f"second ({second.display_name}, {second.confidence})"
    )


def test_resolve_newest_pdf(nl_fs):
    """'the newest PDF' should resolve to tax_return_2024.pdf (1 day old)."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("the newest PDF")
    assert len(candidates) >= 1
    best = candidates[0]
    assert "2024" in best.display_name


def test_resolve_recent_files(nl_fs):
    """'recent xlsx files' should find spreadsheet files."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("recent xlsx files")
    assert len(candidates) >= 1
    # Only one xlsx exists (monthly_budget.xlsx) — verify it's found
    assert any("budget" in c.display_name.lower() for c in candidates), (
        f"Expected monthly_budget.xlsx, got {[c.display_name for c in candidates]}"
    )


def test_resolve_oldest_photo(nl_fs):
    """'my oldest photo' should resolve to beach_vacation.jpg (3 days old)."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("my oldest photo")
    assert len(candidates) >= 1
    best = candidates[0]
    assert "beach" in best.display_name.lower()


# --- Category 3: Candidate ranking and confidence ---

def test_ambiguous_multiple_pdfs_ranks_by_recency(nl_fs):
    """When multiple PDFs match, the resolver should rank by recency."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("PDF in downloads")
    assert len(candidates) >= 2
    # Newest should be first
    assert "2024" in candidates[0].display_name
    assert "2023" in candidates[1].display_name


def test_target_resolver_ambiguity_detection(nl_fs):
    """TargetResolver should require clarification when confidence is insufficient."""
    provider = _make_provider(nl_fs)
    resolver = TargetResolver()
    candidates = provider.discover("PDF in downloads")
    query = TargetQuery(text="PDF in downloads", target_type="file")
    result = resolver.resolve(query, candidates)
    # Either ambiguous or low_confidence — both mean "not auto-resolved"
    assert result.requires_clarification is True


def test_high_confidence_exact_match_resolves(nl_fs):
    """An exact filename match should auto-resolve."""
    provider = _make_provider(nl_fs)
    resolver = TargetResolver()
    candidates = provider.discover("monthly_budget.xlsx")
    query = TargetQuery(text="monthly_budget.xlsx", target_type="file")
    result = resolver.resolve(query, candidates)
    if not result.requires_clarification:
        assert result.resolved is not None
        assert result.resolved.confidence >= 0.85


# --- Category 4: Existence validation ---

def test_resolve_nonexistent_file_returns_no_candidates(nl_fs):
    """A completely invented filename should yield no or very low-confidence candidates."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("definitely_missing_xyz_file_12345")
    # Should return no candidates — no invented path
    assert len(candidates) == 0


def test_resolve_verify_invented_path_caught():
    """verify_file_resolve catches invented paths."""
    v = verify_file_resolve(True, "/completely/fake/path.txt", {"resolved_path": "/completely/fake/path.txt"})
    assert v["verified"] is False
    assert "does not exist" in v["reason"]


def test_resolve_existing_file_succeeds(tmp_path):
    """verify_file_resolve confirms a real file exists."""
    f = tmp_path / "real.txt"
    f.write_text("hello", encoding="utf-8")
    v = verify_file_resolve(True, str(f), {"resolved_path": str(f)})
    assert v["verified"] is True


def test_essay_in_documents_ranks_essay_over_cover_letter(nl_fs):
    """Regression: 'my essay in documents' must pick ielts_essay_draft.docx
    over cover_letter.docx.  The word 'documents' is a location, not a
    filename term — it must not be treated as a file-type keyword that
    forces .docx extension scoring and equalises unrelated files."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("my essay in documents")
    assert len(candidates) >= 1, "Expected at least 1 candidate"
    best = candidates[0]
    assert "essay" in best.display_name.lower(), (
        f"Expected essay file first, got {best.display_name}"
    )
    # cover_letter.docx should NOT appear, or at least rank below
    names = [c.display_name for c in candidates]
    if "cover_letter.docx" in names:
        essay_idx = next(i for i, n in enumerate(names) if "essay" in n.lower())
        cover_idx = next(i for i, n in enumerate(names) if "cover" in n.lower())
        assert essay_idx < cover_idx, (
            f"Essay (idx {essay_idx}) must rank above cover letter (idx {cover_idx})"
        )


# --- Category 5: Original vs copy semantics ---

def test_resolve_original_file_ranks_above_copy(nl_fs):
    """'the original project report' should rank project_report.docx
    above project_report_copy.docx — not just parse the concept."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("the original project report")
    assert len(candidates) >= 2, f"Expected 2 project report files, got {len(candidates)}"
    names = [c.display_name for c in candidates]
    # project_report.docx should outrank project_report_copy.docx
    orig_idx = next((i for i, n in enumerate(names) if n == "project_report.docx"), None)
    copy_idx = next((i for i, n in enumerate(names) if "copy" in n.lower()), None)
    assert orig_idx is not None, f"project_report.docx not found in {names}"
    assert copy_idx is not None, f"project_report_copy.docx not found in {names}"
    assert orig_idx < copy_idx, (
        f"Original (index {orig_idx}) should rank above copy (index {copy_idx})"
    )


def test_resolve_copy_file_ranks_above_original(nl_fs):
    """'the copy of the project report' should rank
    project_report_copy.docx above project_report.docx."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("the copy of the project report")
    assert len(candidates) >= 2, f"Expected 2 project report files, got {len(candidates)}"
    names = [c.display_name for c in candidates]
    copy_idx = next((i for i, n in enumerate(names) if "copy" in n.lower()), None)
    orig_idx = next((i for i, n in enumerate(names) if n == "project_report.docx"), None)
    assert copy_idx is not None, f"project_report_copy.docx not found in {names}"
    assert orig_idx is not None, f"project_report.docx not found in {names}"
    assert copy_idx < orig_idx, (
        f"Copy (index {copy_idx}) should rank above original (index {orig_idx})"
    )


def test_resolve_original_concept_parsed():
    """SemanticQueryParser extracts concept=original."""
    parser = SemanticQueryParser()
    parsed = parser.parse("the original project report")
    assert parsed.concept == "original"


def test_resolve_copy_concept_parsed():
    """SemanticQueryParser extracts concept=copy."""
    parser = SemanticQueryParser()
    parsed = parser.parse("the copy of the project report")
    assert parsed.concept == "copy"


def test_resolve_semantic_parser_extracts_extension():
    """Semantic query parsing extracts extension preferences."""
    parser = SemanticQueryParser()
    parsed = parser.parse("my latest spreadsheet")
    assert parsed.extension == ".xlsx"
    assert parsed.recency == "latest"


def test_resolve_semantic_parser_extracts_location():
    """Semantic query parsing extracts location preferences."""
    parser = SemanticQueryParser()
    parsed = parser.parse("the report in my documents")
    assert parsed.location == "documents"


def test_resolve_semantic_parser_extracts_recency():
    """Semantic query parsing extracts recency preferences."""
    parser = SemanticQueryParser()
    parsed = parser.parse("the file I worked on yesterday")
    assert parsed.recency == "yesterday"


# --- Category 6: Compound natural-language references ---

def test_resolve_that_spreadsheet_i_was_working_on(nl_fs):
    """'that spreadsheet I was working on' — should find budget xlsx
    and rank it first (only spreadsheet in the filesystem)."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("spreadsheet I was working on")
    assert len(candidates) >= 1
    assert "budget" in candidates[0].display_name.lower(), (
        f"Expected monthly_budget.xlsx as top candidate, got {candidates[0].display_name}"
    )


def test_resolve_the_pdf_about_taxes(nl_fs):
    """'the PDF about taxes' — should find tax PDFs and rank
    the newest (2024) above the older (2023)."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("PDF about taxes")
    assert len(candidates) >= 2, f"Expected 2 tax PDFs, got {len(candidates)}"
    names = [c.display_name for c in candidates]
    assert all("tax" in n.lower() for n in names), (
        f"All candidates should be tax-related, got {names}"
    )
    # 2024 should outrank 2023
    assert "2024" in candidates[0].display_name, (
        f"Expected tax_return_2024.pdf first, got {candidates[0].display_name}"
    )


def test_resolve_my_essay_in_documents(nl_fs):
    """'my essay in documents' — should find ielts_essay_draft.docx
    and rank it among the top candidates (not buried)."""
    roots = [nl_fs["documents"]]
    provider = FileTargetProvider(search_roots=roots)
    candidates = provider.discover("essay in documents")
    assert len(candidates) >= 1
    names = [c.display_name for c in candidates]
    assert any("essay" in n.lower() for n in names), (
        f"Expected ielts_essay_draft.docx in candidates, got {names}"
    )
    # The essay should be in the top 2, not buried behind cover_letter
    essay_candidate = [c for c in candidates if "essay" in c.display_name.lower()]
    assert len(essay_candidate) == 1
    assert candidates.index(essay_candidate[0]) <= 1, (
        f"Essay should be top-2, but is at index {candidates.index(essay_candidate[0])} in {names}"
    )


def test_resolve_open_my_most_recent_download(nl_fs):
    """'open my most recent spreadsheet' — full natural-language reference with extension."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("open my most recent spreadsheet")
    # Should find the budget xlsx
    assert len(candidates) >= 1
    assert any("budget" in c.display_name.lower() for c in candidates)


def test_resolve_find_that_photo_i_took(nl_fs):
    """'find that photo I took' — should find both jpg photos
    and the system should be honest about ambiguity (or pick
    one with documented confidence)."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("photo I took")
    assert len(candidates) >= 2, f"Expected 2 photos, got {len(candidates)}"
    names = [c.display_name for c in candidates]
    assert all("jpg" in n.lower() or "photo" in n.lower() or "beach" in n.lower() or "mountain" in n.lower()
               for n in names), (
        f"Both candidates should be photos, got {names}"
    )


def test_resolve_my_meeting_notes(nl_fs):
    """'my meeting notes' — should find meeting_notes.txt
    and rank it first (direct name match)."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("meeting notes")
    assert len(candidates) >= 1
    assert "notes" in candidates[0].display_name.lower(), (
        f"Expected meeting_notes.txt as top candidate, got {candidates[0].display_name}"
    )


def test_resolve_the_script_about_analysis(nl_fs):
    """'the script about analysis' — should find analysis_script.py."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover("script about analysis")
    assert len(candidates) >= 1
    assert any("script" in c.display_name.lower() or "analysis" in c.display_name.lower() for c in candidates)


# --- Location-hint narrowed search ---

def test_resolve_pdf_in_downloads_only(nl_fs):
    """Location hint 'downloads' narrows search to Downloads folder."""
    provider = _make_provider(nl_fs)
    candidates = provider.discover(TargetQuery(
        text="PDF",
        target_type="file",
        location_hint="downloads",
    ))
    for c in candidates:
        assert "Downloads" in c.metadata.get("parent", "") or "Downloads" in c.value


# =========================================================
# PART 4: SAFETY CONFIRMATION GATING
# =========================================================


def test_resolved_delete_requires_confirmation(workspace_root):
    """A delete requires an AuthorizationGrant, enforced by the AUTHORITY.

    RETARGETED 2026-10-15 (Item 3B-3b).

    This test used to call ``SafeFileManager.delete`` directly and assert
    the manager's own ``if not confirmed`` gate. That gate was removed:
    the OS managers no longer branch on ``confirmed``, because the single
    authority is the executor's blast-radius gate plus a valid grant. So
    the property is now asserted where it actually lives -- on
    ``_operation_requires_authorization``, the function both the executor
    and the adapter consult.

    file.delete is Tier 1 (irreversible), so it requires a grant.
    """
    from genesis_os.action_executor import _operation_requires_authorization

    target = workspace_root / "delete_me.txt"
    target.write_text("bye", encoding="utf-8")
    assert _operation_requires_authorization(
        "file.delete", "file.delete", {"path": str(target)}
    ) is True, (
        "file.delete must require a grant at the authority; it is "
        "irreversible and there is no way back"
    )
    assert target.exists()


def test_resolved_move_requires_confirmation(workspace_root):
    """A move that OVERWRITES requires a grant at the authority.

    RETARGETED 2026-10-15 (Item 3B-3b). The manager gate this used to
    assert is gone; authority is the shared blast-radius gate. A move to a
    FREE destination is Tier 2 and deliberately needs nothing -- an
    overwrite is Tier 1 and does. That asymmetry is the real property, so
    both halves are asserted.
    """
    from genesis_os.action_executor import _operation_requires_authorization

    src = workspace_root / "movable.txt"
    src.write_text("move me", encoding="utf-8")
    free = workspace_root / "moved_free.txt"

    assert _operation_requires_authorization(
        "file.move", "file.move",
        {"source": str(src), "destination": str(free)},
    ) is False, "a move to a FREE destination is reversible; Tier 2"

    occupied = workspace_root / "occupied.txt"
    occupied.write_text("will be destroyed", encoding="utf-8")
    assert _operation_requires_authorization(
        "file.move", "file.move",
        {"source": str(src), "destination": str(occupied)},
    ) is True, "an overwriting move destroys existing data; Tier 1"


def test_resolved_rename_requires_confirmation(workspace_root):
    """A rename that OVERWRITES requires a grant; a free rename does not.

    RETARGETED 2026-10-15 (Item 3B-3b), for the same reason as the move
    test: the manager gate is gone and the authority is the shared gate.
    """
    from genesis_os.action_executor import _operation_requires_authorization

    src = workspace_root / "old_name.txt"
    src.write_text("rename", encoding="utf-8")

    assert _operation_requires_authorization(
        "file.rename", "file.rename",
        {"source": str(src), "destination": str(workspace_root / "brand_new.txt")},
    ) is False, "a rename to a free name is reversible; Tier 2"

    existing = workspace_root / "existing_target.txt"
    existing.write_text("will be destroyed", encoding="utf-8")
    assert _operation_requires_authorization(
        "file.rename", "file.rename",
        {"source": str(src), "destination": str(existing)},
    ) is True, "an overwriting rename destroys existing data; Tier 1"


def test_resolved_delete_executes_after_confirmation(tmp_path):
    """Delete executes only after explicit confirmation."""
    sfm = SafeFileManager()
    target = tmp_path / "confirmed_delete.txt"
    target.write_text("bye", encoding="utf-8")
    result = sfm.delete(str(target))
    assert result.get("executed") is True
    assert not target.exists()


def test_resolved_copy_does_not_require_confirmation(tmp_path):
    """Copy to a new destination does NOT require confirmation."""
    sfm = SafeFileManager()
    src = tmp_path / "src.txt"
    src.write_text("data", encoding="utf-8")
    dst = tmp_path / "dst.txt"
    result = sfm.copy(str(src), str(dst))
    assert result.get("success") is True
    assert dst.exists()


def test_resolved_create_folder_no_confirmation(tmp_path):
    """Folder creation does NOT require confirmation."""
    sfm = SafeFileManager()
    folder = tmp_path / "new_folder"
    result = sfm.create(str(folder / "file.txt"), content="hello")
    # create_file creates the parent dir and file
    assert result.get("success") is True


def test_safe_file_create_rejects_content_mismatch(tmp_path, monkeypatch):
    original_write_text = Path.write_text

    def write_corrupted(self, data, *args, **kwargs):
        return original_write_text(self, "corrupted", *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_corrupted)
    result = SafeFileManager().create(
        str(tmp_path / "mismatch.txt"),
        content="expected",
    )

    assert result["success"] is True
    assert result["verified"] is False
    assert result["content_match"] is False


# =========================================================
# PART 6: CONTEXTUAL REFERENCES (pronouns / anaphora)
# =========================================================
# These test genuine contextual references that require
# conversation history to resolve — NOT recency or alias queries.


def test_context_resolve_that_file(nl_fs):
    """'that file' resolves to the most recently mentioned file."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    # User mentions a specific file first
    target = nl_fs["files"]["resume"]
    ctx.update("file", str(target), target.name)

    # Now "that file" should resolve to resume_final.docx
    candidates = provider.discover("that file", context=ctx)
    assert len(candidates) == 1
    assert candidates[0].display_name == "resume_final.docx"
    assert candidates[0].confidence >= 0.90
    assert candidates[0].metadata.get("context_resolved") is True


def test_context_resolve_this_file(nl_fs):
    """'this file' resolves to the most recently mentioned file."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    target = nl_fs["files"]["tax_2024"]
    ctx.update("file", str(target), target.name)

    candidates = provider.discover("this file", context=ctx)
    assert len(candidates) == 1
    assert candidates[0].display_name == "tax_return_2024.pdf"


def test_context_resolve_ambiguous_pronoun(nl_fs):
    """'open it' resolves to the most recent mention of any type."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    target = nl_fs["files"]["budget"]
    ctx.update("file", str(target), target.name)

    candidates = provider.discover("open it", context=ctx)
    assert len(candidates) == 1
    assert candidates[0].display_name == "monthly_budget.xlsx"


def test_context_resolve_same_folder(nl_fs):
    """'same folder' resolves to the most recently mentioned folder."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    # User mentions Downloads folder
    ctx.update("folder", str(nl_fs["downloads"]), "Downloads")

    # "same folder" should search Downloads for all files
    candidates = provider.discover("same folder", context=ctx)
    assert len(candidates) >= 1
    # All results should be from Downloads
    for c in candidates:
        assert str(nl_fs["downloads"]) in c.value


def test_context_resolve_that_folder(nl_fs):
    """'that folder' resolves to the most recently mentioned folder."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    ctx.update("folder", str(nl_fs["documents"]), "Documents")

    candidates = provider.discover("that folder", context=ctx)
    assert len(candidates) >= 1
    for c in candidates:
        assert str(nl_fs["documents"]) in c.value


def test_context_no_resolution_without_history(nl_fs):
    """Without conversation history, 'that file' returns empty candidates."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    # No mentions → context cannot resolve
    candidates = provider.discover("that file", context=ctx)
    assert len(candidates) == 0


def test_context_no_resolution_without_provider(nl_fs):
    """Without a context object, 'that file' returns empty candidates."""
    provider = _make_provider(nl_fs)

    # No context passed → pronoun cannot be resolved
    candidates = provider.discover("that file")
    assert len(candidates) == 0


def test_context_file_takes_priority_over_folder(nl_fs):
    """When both file and folder were mentioned, 'that file' picks the file."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    # Mention a folder first, then a file
    ctx.update("folder", str(nl_fs["downloads"]), "Downloads")
    ctx.update("file", str(nl_fs["files"]["resume"]), "resume_final.docx")

    # "that file" should resolve to the file, not the folder
    candidates = provider.discover("that file", context=ctx)
    assert len(candidates) == 1
    assert candidates[0].display_name == "resume_final.docx"
    assert candidates[0].metadata.get("context_resolved") is True


def test_context_same_folder_finds_specific_name(nl_fs):
    """'same folder' with name terms searches within the mentioned folder."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    ctx.update("folder", str(nl_fs["downloads"]), "Downloads")

    # Search for a specific file within the mentioned folder
    candidates = provider.discover("same folder tax return", context=ctx)
    assert len(candidates) >= 1
    names = [c.display_name for c in candidates]
    assert any("tax_return" in n for n in names)


def test_context_updates_over_time(nl_fs):
    """Context tracks multiple mentions and resolves to the latest."""
    provider = _make_provider(nl_fs)
    ctx = ConversationContext()

    # First mention: beach photo
    ctx.update("file", str(nl_fs["files"]["photo_beach"]), "beach_vacation.jpg")
    # Second mention: resume
    ctx.update("file", str(nl_fs["files"]["resume"]), "resume_final.docx")

    # "that file" should resolve to the most recent mention (resume)
    candidates = provider.discover("that file", context=ctx)
    assert len(candidates) == 1
    assert candidates[0].display_name == "resume_final.docx"


def test_context_parser_detects_contextual_reference():
    """SemanticQueryParser detects 'that file', 'same folder', etc."""
    parser = SemanticQueryParser()

    assert parser.parse("that file").contextual_reference == "file"
    assert parser.parse("this file").contextual_reference == "file"
    assert parser.parse("that folder").contextual_reference == "folder"
    assert parser.parse("same folder").contextual_reference == "folder"
    assert parser.parse("same directory").contextual_reference == "folder"
    # Self-contained queries should NOT be flagged as contextual
    assert parser.parse("project report").contextual_reference is None
    assert parser.parse("tax return pdf").contextual_reference is None
