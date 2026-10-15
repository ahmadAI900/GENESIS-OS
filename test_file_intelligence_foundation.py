from pathlib import Path

from genesis_os.file_intelligence import (
    FileInspector,
    FileStatus,
)


def test_existing_text_file_inspection(tmp_path):

    file = tmp_path / "hello.txt"

    file.write_text(
        "Hello Genesis.",
        encoding="utf-8",
    )

    inspector = FileInspector()

    result = inspector.inspect(file)

    assert result.success is True
    assert result.status == FileStatus.OK

    assert result.identity["exists"] is True
    assert result.identity["is_file"] is True
    assert result.identity["is_directory"] is False

    assert result.metadata["file_type"] == "text"

    assert result.capabilities["read"] is True
    assert result.capabilities["extract"] is True
    assert result.capabilities["summarize"] is True

    assert result.trustworthy_success is True


def test_missing_file_is_not_success(tmp_path):

    file = tmp_path / "missing.txt"

    inspector = FileInspector()

    result = inspector.inspect(file)

    assert result.success is False
    assert result.status == FileStatus.NOT_FOUND

    assert result.trustworthy_success is False


def test_directory_is_first_class_object(tmp_path):

    directory = tmp_path / "documents"

    directory.mkdir()

    inspector = FileInspector()

    result = inspector.inspect(directory)

    assert result.success is True

    assert result.identity["is_directory"] is True
    assert result.identity["is_file"] is False

    assert result.metadata["object_type"] == "directory"

    assert result.capabilities["search"] is True


def test_python_file_classification(tmp_path):

    file = tmp_path / "main.py"

    file.write_text(
        "print('hello')",
        encoding="utf-8",
    )

    result = FileInspector().inspect(file)

    assert result.success is True

    assert result.metadata["file_type"] == "python"

    assert (
        result.metadata["category"]
        == "source_code"
    )

    assert result.capabilities["read"] is True
    assert result.capabilities["summarize"] is True


def test_pdf_classification(tmp_path):

    file = tmp_path / "report.pdf"

    file.write_bytes(
        b"%PDF-test"
    )

    result = FileInspector().inspect(file)

    assert result.success is True

    assert result.metadata["file_type"] == "pdf"

    assert (
        result.metadata["category"]
        == "document"
    )

    assert result.capabilities["extract"] is True


def test_image_is_not_text(tmp_path):

    file = tmp_path / "image.png"

    file.write_bytes(
        b"\x89PNG\r\n\x1a\n"
    )

    result = FileInspector().inspect(file)

    assert result.success is True

    assert result.metadata["file_type"] == "image"

    assert result.capabilities["read"] is False
    assert result.capabilities["extract"] is False


def test_executable_is_not_readable_text(tmp_path):

    file = tmp_path / "program.exe"

    file.write_bytes(
        b"MZ"
    )

    result = FileInspector().inspect(file)

    assert result.success is True

    assert (
        result.metadata["file_type"]
        == "executable"
    )

    assert result.capabilities["read"] is False
    assert result.capabilities["execute"] is False


def test_unknown_extension_is_not_guessed(tmp_path):

    file = tmp_path / "mystery.xyzabc"

    file.write_bytes(
        b"unknown"
    )

    result = FileInspector().inspect(file)

    assert result.success is True

    assert (
        result.metadata["file_type"]
        == "unknown"
    )

    assert (
        result.metadata["category"]
        == "unknown"
    )

    assert result.capabilities["read"] is False


def test_quoted_path(tmp_path):

    file = tmp_path / "quoted.txt"

    file.write_text(
        "Genesis",
        encoding="utf-8",
    )

    quoted = f'"{file}"'

    result = FileInspector().inspect(
        quoted
    )

    assert result.success is True

    assert result.identity["exists"] is True


def test_relative_path_normalization(tmp_path, monkeypatch):

    file = tmp_path / "relative.txt"

    file.write_text(
        "Genesis",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = FileInspector().inspect(
        "./relative.txt"
    )

    assert result.success is True

    assert (
        Path(
            result.identity["absolute_path"]
        ) == file.resolve()
    )


def test_invalid_none_path():

    result = FileInspector().inspect(
        None
    )

    assert result.success is False

    assert result.status == (
        FileStatus.INVALID_PATH
    )


def test_empty_path():

    result = FileInspector().inspect(
        ""
    )

    assert result.success is False

    assert result.status == (
        FileStatus.INVALID_PATH
    )


def test_null_byte_path():

    result = FileInspector().inspect(
        "hello\x00world.txt"
    )

    assert result.success is False

    assert result.status == (
        FileStatus.INVALID_PATH
    )


def test_non_string_path():

    result = FileInspector().inspect(
        12345
    )

    assert result.success is False

    assert result.status == (
        FileStatus.INVALID_PATH
    )


def test_inspection_never_executes(tmp_path):

    file = tmp_path / "test.exe"

    file.write_bytes(
        b"MZ"
    )

    result = FileInspector().inspect(file)

    assert result.success is True

    assert result.capabilities[
        "execute"
    ] is False

    assert result.safety[
        "analysis_only"
    ] is True


def test_result_is_serializable(tmp_path):

    file = tmp_path / "test.txt"

    file.write_text(
        "Genesis",
        encoding="utf-8",
    )

    result = FileInspector().inspect(file)

    data = result.to_dict()

    assert isinstance(
        data,
        dict,
    )

    assert "success" in data
    assert "status" in data
    assert "identity" in data
    assert "metadata" in data
    assert "capabilities" in data
    assert "safety" in data


def test_explanation_is_structured(tmp_path):

    file = tmp_path / "test.txt"

    file.write_text(
        "Genesis",
        encoding="utf-8",
    )

    result = FileInspector().inspect(file)

    explanation = result.explain()

    assert explanation["operation"] == (
        "file.inspect"
    )

    assert explanation["success"] is True

    assert (
        explanation["trustworthy_success"]
        is True
    )


def test_user_message_is_safe(tmp_path):

    file = tmp_path / "test.txt"

    file.write_text(
        "Genesis",
        encoding="utf-8",
    )

    result = FileInspector().inspect(file)

    message = result.user_message()

    assert isinstance(
        message,
        str,
    )

    assert "test.txt" in message