"""
Genesis OS — File Intelligence Manager

LEVEL 3.3
---------

Provides safe, centralized file intelligence for Genesis OS.

Core responsibilities:

    - file inspection
    - file discovery/search
    - metadata extraction
    - text reading
    - content extraction
    - summarization hooks
    - file opening through the operating system
    - copy
    - move
    - rename
    - delete
    - existence checks
    - file type detection

IMPORTANT:

    File Intelligence != unrestricted execution.

Executable files are never executed directly by FileManager.
Application execution belongs to ApplicationManager.

FileManager is responsible for understanding and manipulating
files safely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import hashlib
import mimetypes
import os
import shutil
import subprocess
import zipfile

from genesis_os.file_intelligence.path_security import PathSecurity

_OS_NAME = os.name


class FileManager:
    """
    Central Level 3.3 file intelligence manager.
    """

    VERSION = "3.3"

    TEXT_EXTENSIONS = {
        ".txt",
        ".md",
        ".markdown",
        ".py",
        ".pyw",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".go",
        ".rs",
        ".php",
        ".rb",
        ".swift",
        ".kt",
        ".kts",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sql",
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".log",
        ".bat",
        ".cmd",
        ".ps1",
        ".sh",
        ".env",
    }

    STRUCTURED_EXTENSIONS = {
        ".json",
        ".csv",
    }

    DOCUMENT_EXTENSIONS = {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
    }

    ARCHIVE_EXTENSIONS = {
        ".zip",
    }

    EXECUTABLE_EXTENSIONS = {
        ".exe",
        ".msi",
        ".bat",
        ".cmd",
        ".ps1",
        ".com",
    }

    def __init__(self) -> None:
        pass

    # =========================================================
    # PATH
    # =========================================================

    @staticmethod
    def _path(value: str | Path) -> Path:
        resolved = Path(value).expanduser().resolve()
        result = PathSecurity.validate(str(value))
        if not result["allowed"]:
            raise ValueError(result["reason"])
        return resolved

    @staticmethod
    def _content_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    # =========================================================
    # BASIC FILE INFORMATION
    # =========================================================

    def exists(self, path: str | Path) -> bool:
        return self._path(path).exists()

    def is_file(self, path: str | Path) -> bool:
        return self._path(path).is_file()

    def is_directory(self, path: str | Path) -> bool:
        return self._path(path).is_dir()

    def inspect(self, path: str | Path) -> dict:
        """
        Return detailed file information without modifying it.
        """

        target = self._path(path)

        if not target.exists():
            return {
                "success": False,
                "operation": "file.inspect",
                "path": str(target),
                "message": "File does not exist.",
            }

        if not target.is_file():
            return {
                "success": False,
                "operation": "file.inspect",
                "path": str(target),
                "message": "Path is not a file.",
            }

        stat = target.stat()

        mime_type, _ = mimetypes.guess_type(
            str(target)
        )

        return {
            "success": True,
            "operation": "file.inspect",
            "path": str(target),
            "name": target.name,
            "stem": target.stem,
            "extension": target.suffix.lower(),
            "parent": str(target.parent),
            "size_bytes": stat.st_size,
            "size_kb": round(
                stat.st_size / 1024,
                2,
            ),
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "mime_type": mime_type,
            "file_type": self.detect_type(target),
            "readable": os.access(
                target,
                os.R_OK,
            ),
            "writable": os.access(
                target,
                os.W_OK,
            ),
            "executable": (
                target.suffix.lower()
                in self.EXECUTABLE_EXTENSIONS
            ),
        }

    # =========================================================
    # FILE TYPE
    # =========================================================

    def detect_type(
        self,
        path: str | Path,
    ) -> str:

        target = self._path(path)
        extension = target.suffix.lower()

        if extension in self.TEXT_EXTENSIONS:
            return "text"

        if extension in self.STRUCTURED_EXTENSIONS:
            return "structured_data"

        if extension in self.DOCUMENT_EXTENSIONS:
            return "document"

        if extension in self.ARCHIVE_EXTENSIONS:
            return "archive"

        if extension in {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".webp",
            ".svg",
        }:
            return "image"

        if extension in {
            ".mp3",
            ".wav",
            ".flac",
            ".aac",
            ".ogg",
            ".m4a",
        }:
            return "audio"

        if extension in {
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".webm",
        }:
            return "video"

        if extension in self.EXECUTABLE_EXTENSIONS:
            return "executable"

        return "unknown"

    # =========================================================
    # READ TEXT
    # =========================================================

    def read_text(
        self,
        path: str | Path,
        encoding: Optional[str] = None,
        max_bytes: int = 10_000_000,
    ) -> dict:

        target = self._path(path)

        if not target.is_file():
            return {
                "success": False,
                "operation": "file.read_text",
                "message": "File does not exist.",
            }

        if target.stat().st_size > max_bytes:
            return {
                "success": False,
                "operation": "file.read_text",
                "message": (
                    "File is too large for direct text reading."
                ),
                "size_bytes": target.stat().st_size,
            }

        if self.detect_type(target) not in {
            "text",
            "structured_data",
        }:
            return {
                "success": False,
                "operation": "file.read_text",
                "message": (
                    "File is not recognized as a text-readable file."
                ),
                "file_type": self.detect_type(target),
            }

        encodings = []

        if encoding:
            encodings.append(encoding)

        encodings.extend(
            [
                "utf-8",
                "utf-8-sig",
                "utf-16",
                "cp1252",
            ]
        )

        last_error = None

        for current_encoding in encodings:

            try:

                content = target.read_text(
                    encoding=current_encoding
                )

                return {
                    "success": True,
                    "operation": "file.read_text",
                    "path": str(target),
                    "encoding": current_encoding,
                    "content": content,
                    "characters": len(content),
                }

            except (
                UnicodeDecodeError,
                LookupError,
            ) as error:

                last_error = str(error)

        return {
            "success": False,
            "operation": "file.read_text",
            "message": (
                "Unable to decode the file as supported text."
            ),
            "error": last_error,
        }

    # =========================================================
    # CONTENT EXTRACTION
    # =========================================================

    def extract_text(
        self,
        path: str | Path,
    ) -> dict:

        target = self._path(path)
        file_type = self.detect_type(target)

        if file_type in {
            "text",
            "structured_data",
        }:

            return self.read_text(target)

        if target.suffix.lower() == ".pdf":
            return self._extract_pdf(target)

        if target.suffix.lower() == ".docx":
            return self._extract_docx(target)

        if target.suffix.lower() == ".xlsx":
            return self._extract_xlsx(target)

        if target.suffix.lower() == ".pptx":
            return self._extract_pptx(target)

        if file_type == "archive":
            return self._extract_archive_listing(
                target
            )

        return {
            "success": False,
            "operation": "file.extract_text",
            "path": str(target),
            "file_type": file_type,
            "message": (
                "This file type requires a specialized "
                "content/vision/media handler."
            ),
        }

    # =========================================================
    # PDF
    # =========================================================

    def _extract_pdf(
        self,
        path: Path,
    ) -> dict:

        try:

            import pypdf

        except ImportError:

            return {
                "success": False,
                "operation": "file.extract_pdf",
                "message": (
                    "PDF support requires the pypdf package."
                ),
            }

        try:

            reader = pypdf.PdfReader(
                str(path)
            )

            pages = []

            for page in reader.pages:

                text = page.extract_text() or ""

                pages.append(text)

            content = "\n\n".join(
                pages
            )

            return {
                "success": True,
                "operation": "file.extract_pdf",
                "path": str(path),
                "pages": len(reader.pages),
                "content": content,
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.extract_pdf",
                "message": str(error),
            }

    # =========================================================
    # DOCX
    # =========================================================

    def _extract_docx(
        self,
        path: Path,
    ) -> dict:

        try:

            from docx import Document

        except ImportError:

            return {
                "success": False,
                "operation": "file.extract_docx",
                "message": (
                    "DOCX support requires python-docx."
                ),
            }

        try:

            document = Document(
                str(path)
            )

            paragraphs = [
                paragraph.text
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            ]

            content = "\n".join(
                paragraphs
            )

            return {
                "success": True,
                "operation": "file.extract_docx",
                "path": str(path),
                "content": content,
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.extract_docx",
                "message": str(error),
            }

    # =========================================================
    # XLSX
    # =========================================================

    def _extract_xlsx(
        self,
        path: Path,
    ) -> dict:

        try:

            from openpyxl import load_workbook

        except ImportError:

            return {
                "success": False,
                "operation": "file.extract_xlsx",
                "message": (
                    "XLSX support requires openpyxl."
                ),
            }

        try:

            workbook = load_workbook(
                filename=str(path),
                read_only=True,
                data_only=True,
            )

            sheets = {}

            for worksheet in workbook.worksheets:

                rows = []

                for row in worksheet.iter_rows(
                    values_only=True
                ):

                    rows.append(
                        list(row)
                    )

                sheets[
                    worksheet.title
                ] = rows

            return {
                "success": True,
                "operation": "file.extract_xlsx",
                "path": str(path),
                "sheets": sheets,
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.extract_xlsx",
                "message": str(error),
            }

    # =========================================================
    # PPTX
    # =========================================================

    def _extract_pptx(
        self,
        path: Path,
    ) -> dict:

        try:

            from pptx import Presentation

        except ImportError:

            return {
                "success": False,
                "operation": "file.extract_pptx",
                "message": (
                    "PPTX support requires python-pptx."
                ),
            }

        try:

            presentation = Presentation(
                str(path)
            )

            slides = []

            for slide in presentation.slides:

                texts = []

                for shape in slide.shapes:

                    if hasattr(
                        shape,
                        "text",
                    ):

                        if shape.text.strip():

                            texts.append(
                                shape.text
                            )

                slides.append(
                    "\n".join(texts)
                )

            return {
                "success": True,
                "operation": "file.extract_pptx",
                "path": str(path),
                "slides": slides,
                "content": "\n\n".join(slides),
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.extract_pptx",
                "message": str(error),
            }

    # =========================================================
    # ARCHIVE
    # =========================================================

    def _extract_archive_listing(
        self,
        path: Path,
    ) -> dict:

        try:

            with zipfile.ZipFile(
                path,
                "r",
            ) as archive:

                members = archive.namelist()

            return {
                "success": True,
                "operation": "file.inspect_archive",
                "path": str(path),
                "members": members,
                "member_count": len(members),
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.inspect_archive",
                "message": str(error),
            }

    # =========================================================
    # SEARCH
    # =========================================================

    def search(
        self,
        root: str | Path,
        query: str,
        recursive: bool = True,
        max_results: int = 100,
    ) -> dict:

        directory = self._path(root)

        result = PathSecurity.validate(str(directory))
        if not result["allowed"]:
            raise ValueError(result["reason"])

        if not directory.is_dir():
            return {
                "success": False,
                "operation": "file.search",
                "message": "Search root is not a directory.",
            }

        query = str(query).strip().lower()

        if not query:
            return {
                "success": False,
                "operation": "file.search",
                "message": "Search query is empty.",
            }

        iterator: Iterable[Path]

        if recursive:
            iterator = directory.rglob("*")
        else:
            iterator = directory.glob("*")

        matches = []

        for item in iterator:

            if not item.is_file():
                continue

            if query in item.name.lower():

                matches.append(
                    str(item)
                )

            if len(matches) >= max_results:
                break

        return {
            "success": True,
            "operation": "file.search",
            "root": str(directory),
            "query": query,
            "matches": matches,
            "count": len(matches),
        }

    # =========================================================
    # OPEN
    # =========================================================

    def open(
        self,
        path: str | Path,
    ) -> dict:
        """
        Open a file using Windows' registered application.

        This delegates file opening to the OS rather than
        trying to execute the file directly.
        """

        target = self._path(path)

        if not target.is_file():
            return {
                "success": False,
                "operation": "file.open",
                "message": "File does not exist.",
            }

        try:

            if os.name == "nt":

                os.startfile(
                    str(target)
                )

            else:

                subprocess.Popen(
                    ["xdg-open", str(target)]
                )

            return {
                "success": True,
                "operation": "file.open",
                "path": str(target),
                "file_type": self.detect_type(target),
                "executed": True,
                "verified": False,
                "verification_type": "dispatch_only",
                "verification_reason": "OS open dispatch was not independently observed.",
                "message": (
                    f"Opened {target.name}."
                ),
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.open",
                "path": str(target),
                "message": str(error),
            }

    # =========================================================
    # COPY
    # =========================================================

    def copy(
        self,
        source: str | Path,
        destination: str | Path,
    ) -> dict:

        source_path = self._path(source)
        destination_path = self._path(destination)

        try:

            result = shutil.copy2(
                source_path,
                destination_path,
            )

            verified = Path(result).is_file()
            size_ok = True
            content_ok = True
            if verified and source_path.is_file():
                content_ok = self._content_digest(source_path) == self._content_digest(Path(result))
                size_ok = (
                    Path(result).stat().st_size
                    == source_path.stat().st_size
                )

            if not verified or not size_ok or not content_ok:
                return {
                    "success": False,
                    "operation": "file.copy",
                    "source": str(source_path),
                    "destination": str(result),
                    "verified": False,
                    "message": (
                        "Copy operation completed but the "
                        "destination was not verified on disk."
                    ),
                }

            return {
                "success": True,
                "operation": "file.copy",
                "source": str(source_path),
                "destination": str(result),
                "verified": True,
                "file_matches": content_ok,
                "post_state_matches": True,
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.copy",
                "message": str(error),
            }

    # =========================================================
    # MOVE
    # =========================================================

    def move(
        self,
        source: str | Path,
        destination: str | Path,
    ) -> dict:

        source_path = self._path(source)
        destination_path = self._path(destination)

        source_digest = self._content_digest(source_path) if source_path.is_file() else None
        source_size = (
            source_path.stat().st_size
            if source_path.is_file()
            else None
        )

        try:

            result = shutil.move(
                source_path,
                destination_path,
            )

            dest_path = Path(result)
            dest_exists = dest_path.is_file()
            source_removed = not source_path.exists()
            size_ok = True
            content_ok = True
            if dest_exists and source_size is not None:
                size_ok = (
                    dest_path.stat().st_size
                    == source_size
                )
                content_ok = source_digest == self._content_digest(dest_path)

            if not dest_exists or not source_removed or not size_ok or not content_ok:
                return {
                    "success": False,
                    "operation": "file.move",
                    "source": str(source_path),
                    "destination": str(result),
                    "verified": False,
                    "message": (
                        "Move operation completed but the "
                        "destination was not verified or the "
                        "source was not removed."
                    ),
                }

            return {
                "success": True,
                "operation": "file.move",
                "source": str(source_path),
                "destination": str(result),
                "verified": True,
                "file_matches": content_ok,
                "post_state_matches": True,
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.move",
                "message": str(error),
            }

    # =========================================================
    # RENAME
    # =========================================================

    def rename(
        self,
        source: str | Path,
        new_name: str,
    ) -> dict:

        source_path = self._path(source)

        if not source_path.exists():
            return {
                "success": False,
                "operation": "file.rename",
                "message": "File does not exist.",
            }

        destination = (
            source_path.parent
            / str(new_name)
        )

        try:

            result = source_path.rename(
                destination
            )

            return {
                "success": True,
                "operation": "file.rename",
                "old_path": str(source_path),
                "new_path": str(result),
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.rename",
                "message": str(error),
            }

    # =========================================================
    # DELETE
    # =========================================================

    def delete(
        self,
        path: str | Path,
        confirm: bool = False,
        use_recycle_bin: bool = True,
    ) -> dict:

        target = self._path(path)

        if not target.is_file():
            return {
                "success": False,
                "operation": "file.delete",
                "message": "File does not exist.",
            }

        if not confirm:
            return {
                "success": False,
                "operation": "file.delete",
                "requires_confirmation": True,
                "message": (
                    "Deletion requires explicit confirmation."
                ),
            }

        if use_recycle_bin and _OS_NAME == "nt":
            return self._delete_to_recycle_bin(target)

        try:
            target.unlink()
            return {
                "success": True,
                "operation": "file.delete",
                "path": str(target),
                "verification_type": "permanent_delete",
            }
        except Exception as error:
            return {
                "success": False,
                "operation": "file.delete",
                "message": str(error),
            }

    def _delete_to_recycle_bin(self, target: Path) -> dict:
        try:
            import ctypes
            from ctypes import wintypes

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.BOOL),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]

            source = ctypes.create_unicode_buffer(str(target) + "\0\0")
            operation = SHFILEOPSTRUCTW()
            operation.hwnd = None
            operation.wFunc = 3
            operation.pFrom = source
            operation.pTo = None
            operation.fFlags = 0x0010 | 0x0040
            operation.fAnyOperationsAborted = False
            operation.hNameMappings = None
            operation.lpszProgressTitle = None
            result = ctypes.windll.shell32.SHFileOperationW(
                ctypes.byref(operation)
            )
            if result == 0 and not target.exists():
                return {
                    "success": True,
                    "operation": "file.delete",
                    "path": str(target),
                    "verification_type": "recycle_bin",
                    "message": "File moved to Recycle Bin.",
                }
        except Exception:
            pass

        try:
            target.unlink()
        except Exception as error:
            return {
                "success": False,
                "operation": "file.delete",
                "path": str(target),
                "message": "Recycle Bin operation failed and permanent delete failed.",
                "error": str(error),
            }
        return {
            "success": True,
            "operation": "file.delete",
            "path": str(target),
            "verification_type": "permanent_delete",
            "recycle_bin_fallback": True,
            "message": "Recycle Bin operation failed; permanent delete was used after confirmation.",
        }

    def watch(
        self,
        path: str | Path,
        event: str = "modified",
    ) -> dict:
        """
        Watch a file or folder for changes.
        Returns current state and watch readiness.
        """
        target = self._path(path)
        if not target.exists():
            return {
                "success": False,
                "operation": "file.watch",
                "message": "Path does not exist.",
            }
        try:
            import hashlib
            current_hash = self._compute_hash(target)
            return {
                "success": True,
                "operation": "file.watch",
                "path": str(target),
                "event": event,
                "current_hash": current_hash,
                "size": target.stat().st_size,
                "modified": target.stat().st_mtime,
                "message": "Watch ready. Compare hashes on re-check to detect changes.",
            }
        except Exception as error:
            return {
                "success": False,
                "operation": "file.watch",
                "message": str(error),
            }

    def _compute_hash(self, target: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with target.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    # =========================================================
    # OPEN
    # =========================================================

    # =========================================================
    # HASH
    # =========================================================

    def hash(
        self,
        path: str | Path,
        algorithm: str = "sha256",
        chunk_size: int = 1024 * 1024,
    ) -> dict:

        target = self._path(path)

        if not target.is_file():
            return {
                "success": False,
                "operation": "file.hash",
                "message": "File does not exist.",
            }

        try:

            digest = hashlib.new(
                algorithm
            )

            with target.open(
                "rb"
            ) as handle:

                while True:

                    chunk = handle.read(
                        chunk_size
                    )

                    if not chunk:
                        break

                    digest.update(
                        chunk
                    )

            return {
                "success": True,
                "operation": "file.hash",
                "path": str(target),
                "algorithm": algorithm,
                "hash": digest.hexdigest(),
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.hash",
                "message": str(error),
            }

    # =========================================================
    # SUMMARY
    # =========================================================

    def summarize(
        self,
        path: str | Path,
        summarizer=None,
    ) -> dict:
        """
        Extract file content and optionally send it to a
        supplied Genesis AI summarizer.

        FileManager does not own the AI engine.
        """

        extracted = self.extract_text(
            path
        )

        if not extracted.get("success"):
            return extracted

        content = extracted.get(
            "content",
            "",
        )

        if not content:

            return {
                "success": True,
                "operation": "file.summarize",
                "path": str(
                    self._path(path)
                ),
                "summary": (
                    "No textual content was available "
                    "for summarization."
                ),
            }

        if summarizer is None:

            return {
                "success": True,
                "operation": "file.summarize",
                "path": str(
                    self._path(path)
                ),
                "content_available": True,
                "content_length": len(content),
                "summary": None,
                "message": (
                    "Content extracted successfully. "
                    "No AI summarizer was supplied."
                ),
                "content": content,
            }

        try:

            summary = summarizer(
                content
            )

            return {
                "success": True,
                "operation": "file.summarize",
                "path": str(
                    self._path(path)
                ),
                "summary": summary,
            }

        except Exception as error:

            return {
                "success": False,
                "operation": "file.summarize",
                "message": str(error),
            }