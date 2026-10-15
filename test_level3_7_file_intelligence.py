from pathlib import Path

from genesis_os.file_intelligence.file_result import (
    FileStatus,
)
from genesis_os.file_intelligence.file_service import (
    FileIntelligenceService,
)


def test_normalize_valid_path(tmp_path):

    file = tmp_path / "hello.txt"

    file.write_text(
        "Genesis",
        encoding="utf-8",
    )

    result = FileIntelligenceService.normalize(
        file
    )

    assert result.success is True
    assert result.status == FileStatus.OK
    assert Path(result.path) == file.resolve()
    assert result.safety["allowed"] is True


def test_invalid_path_is_rejected():

    result = FileIntelligenceService.normalize(
        None
    )

    assert result.success is False
    assert result.status == FileStatus.INVALID_PATH
    assert result.safety["allowed"] is False


def test_existing_file_is_detected(tmp_path):

    file = tmp_path / "report.txt"

    file.write_text(
        "student results",
        encoding="utf-8",
    )

    result = FileIntelligenceService().exists(
        file
    )

    assert result.success is True
    assert result.metadata["exists"] is True


def test_missing_file_is_not_success(tmp_path):

    file = tmp_path / "missing.txt"

    result = FileIntelligenceService().exists(
        file
    )

    assert result.success is False
    assert result.status == FileStatus.NOT_FOUND


def test_inspection_uses_existing_intelligence(tmp_path):

    file = tmp_path / "results.csv"

    file.write_text(
        "Name,Percentage\nAli,90\nSara,95\n",
        encoding="utf-8",
    )

    result = FileIntelligenceService().inspect(
        file
    )

    assert result.success is True
    assert result.metadata["file_type"] == "spreadsheet"
    assert result.metadata["category"] == "spreadsheet"
    assert result.capabilities["read"] is True


def test_directory_discovery_is_deterministic(tmp_path):

    (tmp_path / "b.txt").write_text(
        "B",
        encoding="utf-8",
    )

    (tmp_path / "a.txt").write_text(
        "A",
        encoding="utf-8",
    )

    service = FileIntelligenceService()

    first = service.discover(
        tmp_path,
        pattern="*.txt",
    )

    second = service.discover(
        tmp_path,
        pattern="*.txt",
    )

    assert first.success is True
    assert second.success is True

    assert first.evidence["entries"] == (
        second.evidence["entries"]
    )


def test_recursive_discovery(tmp_path):

    nested = tmp_path / "nested"
    nested.mkdir()

    file = nested / "result.csv"

    file.write_text(
        "Name,Percentage\nAli,90",
        encoding="utf-8",
    )

    result = FileIntelligenceService().discover(
        tmp_path,
        pattern="*.csv",
        recursive=True,
    )

    assert result.success is True
    assert result.metadata["count"] == 1
    assert result.evidence["entries"][0]["name"] == (
        "result.csv"
    )


def test_discovery_requires_directory(tmp_path):

    file = tmp_path / "not_directory.txt"

    file.write_text(
        "Genesis",
        encoding="utf-8",
    )

    result = FileIntelligenceService().discover(
        file
    )

    assert result.success is False
    assert result.status == FileStatus.NOT_A_DIRECTORY


def test_conflicting_discovery_filters_are_rejected(
    tmp_path,
):

    result = FileIntelligenceService().discover(
        tmp_path,
        files_only=True,
        directories_only=True,
    )

    assert result.success is False
    assert result.status == FileStatus.INVALID_PATH


def test_extension_classification():

    service = FileIntelligenceService()

    result = service.classify_extension(
        ".xlsx"
    )

    assert result.success is True
    assert result.metadata["file_type"] == (
        "spreadsheet"
    )

    assert result.metadata["category"] == (
        "spreadsheet"
    )

    assert result.capabilities["read"] is True


def test_unknown_extension_remains_unknown():

    result = FileIntelligenceService().classify_extension(
        ".something_unknown"
    )

    assert result.success is True
    assert result.metadata["file_type"] == (
        "unknown"
    )

    assert result.metadata["category"] == (
        "unknown"
    )


def test_service_does_not_modify_files(tmp_path):

    file = tmp_path / "important.txt"

    original = "DO NOT MODIFY"

    file.write_text(
        original,
        encoding="utf-8",
    )

    FileIntelligenceService().inspect(
        file
    )

    assert file.read_text(
        encoding="utf-8"
    ) == original