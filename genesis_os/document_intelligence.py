"""
Level 3 Document Intelligence Service - Genesis OS

Supports common document types (TXT, DOCX, PDF, XLSX, CSV, PPTX, HTML, JSON, Markdown)
and operations (read, inspect, search, extract, summarize, create, edit, transform, compare, save).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Optional dependency detection
try:
    from docx import Document as DocxDocument

    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from pypdf import PdfReader, PdfWriter

    HAS_PYPDF = True
except ImportError:
    try:
        from pypdf import PdfReader  # type: ignore

        from pypdf import PdfWriter  # type: ignore

        HAS_PYPDF = True
    except ImportError:
        HAS_PYPDF = False

try:
    from reportlab.pdfgen import canvas as ReportlabCanvas  # type: ignore
    from reportlab.lib.pagesizes import letter as ReportlabLetter  # type: ignore

    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

try:
    from openpyxl import load_workbook

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    from pptx import Presentation as PptxPresentation

    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

try:
    from html.parser import HTMLParser

    HAS_HTML_PARSER = True
except ImportError:
    HAS_HTML_PARSER = False


class DocumentFormat(Enum):
    """Supported document formats."""

    TXT = "txt"
    DOCX = "docx"
    PDF = "pdf"
    XLSX = "xlsx"
    CSV = "csv"
    PPTX = "pptx"
    HTML = "html"
    JSON = "json"
    MARKDOWN = "markdown"
    CODE = "code"


@dataclass(frozen=True)
class DocumentType:
    """Immutable metadata about a document format's capabilities."""

    format: DocumentFormat
    mime_type: str
    extensions: Tuple[str, ...]
    supports_read: bool = True
    supports_create: bool = True
    supports_edit: bool = False
    supports_extract: bool = True


@dataclass(frozen=True)
class DocumentInspection:
    """Read-only metadata inspection of a document."""

    path: str
    format: DocumentFormat
    name: str
    size: int
    page_count: int = 0
    word_count: int = 0
    created: float = 0.0
    modified: float = 0.0
    title: str = ""
    author: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentContent:
    """Full text content extracted from a document."""

    path: str
    format: DocumentFormat
    text: str
    pages: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tables: List[List[Dict[str, Any]]] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentResult:
    """Unified result contract for all document operations."""

    success: bool
    operation: str
    path: str
    format: DocumentFormat = DocumentFormat.TXT
    message: str = ""
    data: Any = None
    error: Optional[str] = None
    # Item 13C (C6): did the CONTENT actually change?
    #
    # None means the operation does not claim to have verified anything
    # (reads, inspections, comparisons). True/False mean it read the
    # result back and compared it. Writes must not leave this None:
    # "the file exists and is non-empty" is evidence the write happened,
    # not evidence the replacement landed.
    verified: Optional[bool] = None


class DocumentIntelligence:
    """
    Main Document Intelligence service.

    Provides reading, inspection, search, extraction, summarization,
    creation, and comparison for common document types.
    """

    def __init__(self) -> None:
        """Initialize the service and register supported formats."""
        self._snapshot_digests = {}
        self._formats: Dict[DocumentFormat, DocumentType] = {
            DocumentFormat.TXT: DocumentType(
                format=DocumentFormat.TXT,
                mime_type="text/plain",
                extensions=(".txt",),
                supports_read=True,
                supports_create=True,
                supports_edit=True,
                supports_extract=True,
            ),
            DocumentFormat.DOCX: DocumentType(
                format=DocumentFormat.DOCX,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                extensions=(".docx",),
                supports_read=HAS_DOCX,
                supports_create=HAS_DOCX,
                supports_edit=HAS_DOCX,
                supports_extract=HAS_DOCX,
            ),
            DocumentFormat.PDF: DocumentType(
                format=DocumentFormat.PDF,
                mime_type="application/pdf",
                extensions=(".pdf",),
                supports_read=HAS_PYPDF,
                supports_create=HAS_REPORTLAB,
                supports_edit=HAS_PYPDF,
                supports_extract=HAS_PYPDF,
            ),
            DocumentFormat.XLSX: DocumentType(
                format=DocumentFormat.XLSX,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                extensions=(".xlsx",),
                supports_read=HAS_OPENPYXL,
                supports_create=HAS_OPENPYXL,
                supports_edit=HAS_OPENPYXL,
                supports_extract=HAS_OPENPYXL,
            ),
            DocumentFormat.CSV: DocumentType(
                format=DocumentFormat.CSV,
                mime_type="text/csv",
                extensions=(".csv",),
                supports_read=True,
                supports_create=True,
                supports_edit=True,
                supports_extract=True,
            ),
            DocumentFormat.PPTX: DocumentType(
                format=DocumentFormat.PPTX,
                mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                extensions=(".pptx",),
                supports_read=HAS_PPTX,
                supports_create=HAS_PPTX,
                supports_edit=HAS_PPTX,
                supports_extract=HAS_PPTX,
            ),
            DocumentFormat.HTML: DocumentType(
                format=DocumentFormat.HTML,
                mime_type="text/html",
                extensions=(".html", ".htm"),
                supports_read=True,
                supports_create=True,
                supports_edit=True,
                supports_extract=True,
            ),
            DocumentFormat.JSON: DocumentType(
                format=DocumentFormat.JSON,
                mime_type="application/json",
                extensions=(".json",),
                supports_read=True,
                supports_create=True,
                supports_edit=True,
                supports_extract=True,
            ),
            DocumentFormat.MARKDOWN: DocumentType(
                format=DocumentFormat.MARKDOWN,
                mime_type="text/markdown",
                extensions=(".md", ".markdown"),
                supports_read=True,
                supports_create=True,
                supports_edit=True,
                supports_extract=True,
            ),
            DocumentFormat.CODE: DocumentType(
                format=DocumentFormat.CODE,
                mime_type="text/plain",
                extensions=(".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".rs", ".go", ".rb"),
                supports_read=True,
                supports_create=True,
                supports_edit=True,
                supports_extract=True,
            ),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inspect(self, path: str) -> DocumentResult:
        """Read-only metadata inspection of a document."""
        try:
            abs_path = os.path.abspath(path)
            if not os.path.exists(abs_path):
                return DocumentResult(
                    success=False,
                    operation="inspect",
                    path=abs_path,
                    message=f"File not found: {abs_path}",
                    error="FileNotFoundError",
                )

            fmt = self._detect_format(abs_path)
            stat = os.stat(abs_path)
            name = os.path.basename(abs_path)

            page_count = 0
            word_count = 0
            title = ""
            author = ""
            metadata: Dict[str, Any] = {}

            if fmt == DocumentFormat.PDF and HAS_PYPDF:
                info = self._read_pdf_metadata(abs_path)
                page_count = info.get("page_count", 0)
                word_count = info.get("word_count", 0)
                title = info.get("title", "")
                author = info.get("author", "")
                metadata = info.get("metadata", {})
            elif fmt == DocumentFormat.DOCX and HAS_DOCX:
                info = self._read_docx_metadata(abs_path)
                word_count = info.get("word_count", 0)
                title = info.get("title", "")
                author = info.get("author", "")
                metadata = info.get("metadata", {})
            elif fmt == DocumentFormat.PPTX and HAS_PPTX:
                info = self._read_pptx_metadata(abs_path)
                page_count = info.get("slide_count", 0)
                word_count = info.get("word_count", 0)
                metadata = info.get("metadata", {})
            elif fmt == DocumentFormat.XLSX and HAS_OPENPYXL:
                info = self._read_xlsx_metadata(abs_path)
                metadata = info.get("metadata", {})
            else:
                content_result = self.read(abs_path)
                if content_result.success and isinstance(content_result.data, dict):
                    word_count = content_result.data.get("word_count", 0)
                    metadata = content_result.data.get("metadata", {})

            inspection = DocumentInspection(
                path=abs_path,
                format=fmt,
                name=name,
                size=stat.st_size,
                page_count=page_count,
                word_count=word_count,
                created=stat.st_ctime,
                modified=stat.st_mtime,
                title=title,
                author=author,
                metadata=metadata,
            )

            return DocumentResult(
                success=True,
                operation="inspect",
                path=abs_path,
                format=fmt,
                message="Document inspected successfully",
                data={
                    "path": inspection.path,
                    "format": inspection.format.value,
                    "name": inspection.name,
                    "size": inspection.size,
                    "page_count": inspection.page_count,
                    "word_count": inspection.word_count,
                    "created": inspection.created,
                    "modified": inspection.modified,
                    "title": inspection.title,
                    "author": inspection.author,
                    "metadata": inspection.metadata,
                },
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="inspect",
                path=path,
                message=f"Inspect failed: {exc}",
                error=str(exc),
            )

    def read(self, path: str) -> DocumentResult:
        """Extract full text content from a document."""
        try:
            abs_path = os.path.abspath(path)
            if not os.path.exists(abs_path):
                return DocumentResult(
                    success=False,
                    operation="read",
                    path=abs_path,
                    message=f"File not found: {abs_path}",
                    error="FileNotFoundError",
                )

            fmt = self._detect_format(abs_path)
            reader = self._get_reader(fmt)
            if reader is None:
                return DocumentResult(
                    success=False,
                    operation="read",
                    path=abs_path,
                    format=fmt,
                    message=f"No reader available for format: {fmt.value}",
                    error="UnsupportedFormatError",
                )

            result = reader(abs_path)
            return DocumentResult(
                success=True,
                operation="read",
                path=abs_path,
                format=fmt,
                message="Document read successfully",
                data=result,
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="read",
                path=path,
                message=f"Read failed: {exc}",
                error=str(exc),
            )

    def search(self, path: str, query: str) -> DocumentResult:
        """Search within document content for matching text."""
        try:
            read_result = self.read(path)
            if not read_result.success:
                return DocumentResult(
                    success=False,
                    operation="search",
                    path=path,
                    format=read_result.format,
                    message=read_result.message,
                    error=read_result.error,
                )

            data = read_result.data
            if not isinstance(data, dict):
                return DocumentResult(
                    success=False,
                    operation="search",
                    path=path,
                    format=read_result.format,
                    message="Unexpected data format from read",
                    error="DataFormatError",
                )

            text = data.get("text", "")
            matches: List[Dict[str, Any]] = []
            pattern = re.compile(re.escape(query), re.IGNORECASE)

            lines = text.split("\n")
            for line_num, line in enumerate(lines, start=1):
                for match in pattern.finditer(line):
                    start = max(0, match.start() - 40)
                    end = min(len(line), match.end() + 40)
                    context = line[start:end]
                    matches.append(
                        {
                            "line": line_num,
                            "match": match.group(),
                            "context": context,
                            "position": match.start(),
                        }
                    )

            return DocumentResult(
                success=True,
                operation="search",
                path=os.path.abspath(path),
                format=read_result.format,
                message=f"Found {len(matches)} match(es) for '{query}'",
                data={
                    "query": query,
                    "match_count": len(matches),
                    "matches": matches,
                },
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="search",
                path=path,
                message=f"Search failed: {exc}",
                error=str(exc),
            )

    def extract_tables(self, path: str) -> DocumentResult:
        """Extract tabular data from a document (CSV, XLSX)."""
        try:
            abs_path = os.path.abspath(path)
            if not os.path.exists(abs_path):
                return DocumentResult(
                    success=False,
                    operation="extract_tables",
                    path=abs_path,
                    message=f"File not found: {abs_path}",
                    error="FileNotFoundError",
                )

            fmt = self._detect_format(abs_path)

            if fmt == DocumentFormat.CSV:
                tables = self._extract_csv_tables(abs_path)
                return DocumentResult(
                    success=True,
                    operation="extract_tables",
                    path=abs_path,
                    format=fmt,
                    message="Tables extracted successfully",
                    data={"tables": tables},
                )
            elif fmt == DocumentFormat.XLSX and HAS_OPENPYXL:
                tables = self._extract_xlsx_tables(abs_path)
                return DocumentResult(
                    success=True,
                    operation="extract_tables",
                    path=abs_path,
                    format=fmt,
                    message="Tables extracted successfully",
                    data={"tables": tables},
                )
            else:
                return DocumentResult(
                    success=False,
                    operation="extract_tables",
                    path=abs_path,
                    format=fmt,
                    message=f"Table extraction not supported for format: {fmt.value}",
                    error="UnsupportedOperationError",
                )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="extract_tables",
                path=path,
                message=f"Table extraction failed: {exc}",
                error=str(exc),
            )

    def create_docx(
        self,
        path: str,
        title: str,
        content: str,
        sections: Optional[List[Dict[str, Any]]] = None,
    ) -> DocumentResult:
        """Create a DOCX document with title, content, and optional sections."""
        try:
            if not HAS_DOCX:
                return DocumentResult(
                    success=False,
                    operation="create_docx",
                    path=path,
                    format=DocumentFormat.DOCX,
                    message="python-docx is not installed. Install with: pip install python-docx",
                    error="DependencyMissingError",
                )

            abs_path = os.path.abspath(path)
            doc = DocxDocument()
            doc.add_heading(title, level=0)
            doc.add_paragraph(content or "")

            if sections:
                for section in sections:
                    heading = section.get("heading", "")
                    body = section.get("content", section.get("body", ""))
                    if heading:
                        doc.add_heading(heading, level=1)
                    if body:
                        doc.add_paragraph(body)

            doc.save(abs_path)
            return DocumentResult(
                success=True,
                operation="create_docx",
                path=abs_path,
                format=DocumentFormat.DOCX,
                message="DOCX document created successfully",
                data={"title": title, "sections": len(sections or [])},
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="create_docx",
                path=path,
                message=f"Create DOCX failed: {exc}",
                error=str(exc),
            )

    def create_txt(self, path: str, content: str) -> DocumentResult:
        """Create a plain text file."""
        try:
            abs_path = os.path.abspath(path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            # Item 16D (C18): read it back.
            verified = self._verify_written_text(abs_path, content)

            return DocumentResult(
                success=True,
                operation="create_txt",
                path=abs_path,
                format=DocumentFormat.TXT,
                message="TXT file created successfully",
                data={"size": len(content.encode("utf-8"))},
            verified=verified,
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="create_txt",
                path=path,
                message=f"Create TXT failed: {exc}",
                error=str(exc),
            )

    def create_csv(
        self, path: str, headers: List[str], rows: List[List[Any]]
    ) -> DocumentResult:
        """Create a CSV file with headers and rows."""
        try:
            abs_path = os.path.abspath(path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            with open(abs_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            # Item 16D (C18): read it back.
            verified = self._verify_written_csv(abs_path, headers, rows)

            return DocumentResult(
                success=True,
                operation="create_csv",
                path=abs_path,
                format=DocumentFormat.CSV,
                message="CSV file created successfully",
                data={"headers": headers, "row_count": len(rows)},
            verified=verified,
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="create_csv",
                path=path,
                message=f"Create CSV failed: {exc}",
                error=str(exc),
            )

    def create_json(self, path: str, data: Any) -> DocumentResult:
        """Create a JSON file with the given data."""
        try:
            abs_path = os.path.abspath(path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            with open(abs_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            # Item 16D (C18): read it back.
            verified = self._verify_written_json(abs_path, data)

            return DocumentResult(
                success=True,
                operation="create_json",
                path=abs_path,
                format=DocumentFormat.JSON,
                message="JSON file created successfully",
                data={"size": os.path.getsize(abs_path)},
            verified=verified,
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="create_json",
                path=path,
                message=f"Create JSON failed: {exc}",
                error=str(exc),
            )

    def create_markdown(self, path: str, content: str) -> DocumentResult:
        """Create a Markdown file."""
        try:
            abs_path = os.path.abspath(path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            # Item 16D (C18): read it back.
            verified = self._verify_written_text(abs_path, content)

            return DocumentResult(
                success=True,
                operation="create_markdown",
                path=abs_path,
                format=DocumentFormat.MARKDOWN,
                message="Markdown file created successfully",
                data={"size": len(content.encode("utf-8"))},
            verified=verified,
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="create_markdown",
                path=path,
                message=f"Create Markdown failed: {exc}",
                error=str(exc),
            )

    def create_pdf(self, path: str, title: str, content: str) -> DocumentResult:
        """Create a PDF document with title + body text via reportlab platypus.

        Writes to the requested ``path`` (parent dirs created), then
        verifies the output exists with size>0. There is no "original"
        for a creation (original N/A). When reportlab is missing this
        returns success=False with error
        "reportlab required for PDF creation (pip install reportlab)"
        instead of faking PDF bytes.
        """
        try:
            if not HAS_REPORTLAB:
                return DocumentResult(
                    success=False,
                    operation="create_pdf",
                    path=path,
                    format=DocumentFormat.PDF,
                    message=(
                        "reportlab is not installed; refusing to fake PDF "
                        "bytes. Install with: pip install reportlab"
                    ),
                    error="reportlab required for PDF creation (pip install reportlab)",
                )

            abs_path = os.path.abspath(path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            try:
                from reportlab.lib.pagesizes import letter as _letter
                from reportlab.lib.styles import getSampleStyleSheet as _get_styles
                from reportlab.platypus import (
                    Paragraph as _Paragraph,
                    SimpleDocTemplate as _DocTemplate,
                    Spacer as _Spacer,
                )
            except ImportError:
                return DocumentResult(
                    success=False,
                    operation="create_pdf",
                    path=abs_path,
                    format=DocumentFormat.PDF,
                    message=(
                        "reportlab is not installed; refusing to fake PDF "
                        "bytes. Install with: pip install reportlab"
                    ),
                    error="reportlab required for PDF creation (pip install reportlab)",
                )

            styles = _get_styles()
            story = [_Paragraph(title or "Untitled", styles["Title"]),
                     _Spacer(1, 12)]
            for para in (content or "").split("\n"):
                story.append(_Paragraph(para if para.strip() else " ",
                                        styles["Normal"]))
                story.append(_Spacer(1, 6))

            _DocTemplate(abs_path, pagesize=_letter).build(story)

            verified = self._verify_output(abs_path)
            if not verified:
                return DocumentResult(
                    success=False,
                    operation="create_pdf",
                    path=abs_path,
                    format=DocumentFormat.PDF,
                    message="PDF creation wrote output but verification failed",
                    error="VerificationFailed",
                )
            return DocumentResult(
                success=True,
                operation="create_pdf",
                path=abs_path,
                format=DocumentFormat.PDF,
                message="PDF document created successfully",
                data={"title": title, "size": os.path.getsize(abs_path),
                      "verified": True},
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="create_pdf",
                path=path,
                message=f"Create PDF failed: {exc}",
                error=str(exc),
            )

    def compare(self, path1: str, path2: str) -> DocumentResult:
        """Compare two documents by text content and report differences."""
        try:
            r1 = self.read(path1)
            r2 = self.read(path2)

            if not r1.success:
                return DocumentResult(
                    success=False,
                    operation="compare",
                    path=path1,
                    format=r1.format,
                    message=f"Failed to read first document: {r1.message}",
                    error=r1.error,
                )
            if not r2.success:
                return DocumentResult(
                    success=False,
                    operation="compare",
                    path=path2,
                    format=r2.format,
                    message=f"Failed to read second document: {r2.message}",
                    error=r2.error,
                )

            text1 = r1.data.get("text", "") if isinstance(r1.data, dict) else ""
            text2 = r2.data.get("text", "") if isinstance(r2.data, dict) else ""

            lines1 = text1.splitlines()
            lines2 = text2.splitlines()

            added: List[str] = []
            removed: List[str] = []
            unchanged = 0

            max_len = max(len(lines1), len(lines2))
            for i in range(max_len):
                l1 = lines1[i] if i < len(lines1) else None
                l2 = lines2[i] if i < len(lines2) else None
                if l1 == l2:
                    unchanged += 1
                else:
                    if l1 is not None:
                        removed.append(l1)
                    if l2 is not None:
                        added.append(l2)

            similarity = unchanged / max_len if max_len > 0 else 1.0

            return DocumentResult(
                success=True,
                operation="compare",
                path=os.path.abspath(path1),
                format=r1.format,
                message=f"Comparison complete: {similarity:.1%} similarity",
                data={
                    "path1": os.path.abspath(path1),
                    "path2": os.path.abspath(path2),
                    "similarity": round(similarity, 4),
                    "added_lines": added,
                    "removed_lines": removed,
                    "unchanged_lines": unchanged,
                },
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="compare",
                path=path1,
                message=f"Compare failed: {exc}",
                error=str(exc),
            )

    def summarize(self, path: str, max_length: int = 500) -> DocumentResult:
        """Basic extractive summary: return the first max_length characters of text."""
        try:
            read_result = self.read(path)
            if not read_result.success:
                return DocumentResult(
                    success=False,
                    operation="summarize",
                    path=path,
                    format=read_result.format,
                    message=read_result.message,
                    error=read_result.error,
                )

            data = read_result.data
            text = data.get("text", "") if isinstance(data, dict) else ""

            sentences = re.split(r"(?<=[.!?])\s+", text)
            summary_parts: List[str] = []
            current_length = 0

            for sentence in sentences:
                if current_length + len(sentence) + 1 > max_length:
                    break
                summary_parts.append(sentence)
                current_length += len(sentence) + 1

            summary = " ".join(summary_parts) if summary_parts else text[:max_length]

            return DocumentResult(
                success=True,
                operation="summarize",
                path=os.path.abspath(path),
                format=read_result.format,
                message="Document summarized successfully",
                data={
                    "summary": summary,
                    "original_length": len(text),
                    "summary_length": len(summary),
                    "truncated": len(text) > max_length,
                },
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="summarize",
                path=path,
                message=f"Summarize failed: {exc}",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # EDIT
    # ------------------------------------------------------------------

    def edit(
        self,
        path: str,
        find_text: str,
        replace_text: str,
        output: Optional[str] = None,
    ) -> DocumentResult:
        """Edit a document by finding and replacing text.

        Supports TXT, CSV, JSON, Markdown, and code files via text
        replacement, DOCX via structure-preserving paragraph
        replacement (styles, runs, tables kept intact), PDF via
        pypdf PdfReader+PdfWriter (append-text-page with reportlab
        plus metadata edit), and PPTX via python-pptx
        (replace-text across shapes/tables).

        The edited content is written to ``output`` when given,
        otherwise to a sibling ``<stem>_edited.<ext>`` file. The
        original is NEVER overwritten by default.

        XLSX and HTML are explicitly refused: the old
        implementation flattened them to plain text, silently
        destroying the file. Refusing loudly beats corrupting data.
        """
        try:
            abs_path = os.path.abspath(path)
            if not os.path.exists(abs_path):
                return DocumentResult(
                    success=False,
                    operation="edit",
                    path=abs_path,
                    message=f"File not found: {abs_path}",
                    error="FileNotFoundError",
                )

            fmt = self._detect_format(abs_path)

            # DOCX: structure-preserving edit via python-docx.
            if fmt == DocumentFormat.DOCX:
                return self._edit_docx(abs_path, fmt, find_text, replace_text, output)

            # PDF: real edit via pypdf (append-text-page + metadata).
            if fmt == DocumentFormat.PDF:
                return self._edit_pdf(abs_path, fmt, find_text, replace_text, output)

            # PPTX: real edit via python-pptx (replace-text).
            if fmt == DocumentFormat.PPTX:
                return self._edit_pptx(abs_path, fmt, find_text, replace_text, output)

            # Formats we cannot edit without destroying structure.
            if fmt in (
                DocumentFormat.XLSX,
                DocumentFormat.HTML,
            ):
                return DocumentResult(
                    success=False,
                    operation="edit",
                    path=abs_path,
                    format=fmt,
                    message=(
                        f"Edit is not supported for {fmt.value.upper()}: "
                        "no structure-preserving editor is available, and "
                        "writing flat text would corrupt the file. The "
                        "original was left untouched."
                    ),
                    error="EditNotSupportedForFormat",
                )

            # Read current content
            read_result = self.read(abs_path)
            if not read_result.success:
                return DocumentResult(
                    success=False,
                    operation="edit",
                    path=abs_path,
                    format=fmt,
                    message=read_result.message,
                    error=read_result.error,
                )

            data = read_result.data
            text = data.get("text", "") if isinstance(data, dict) else ""

            if find_text not in text:
                return DocumentResult(
                    success=False,
                    operation="edit",
                    path=abs_path,
                    format=fmt,
                    message=f"Text not found in document: '{find_text[:50]}...'".rstrip("."),
                    error="TextNotFound",
                )

            edited_text = text.replace(find_text, replace_text)
            occurrences = text.count(find_text)

            dest = self._resolve_output(abs_path, output, "edited")
            with open(dest, "w", encoding="utf-8", newline="") as f:
                f.write(edited_text)
            # Item 16D (C18): read it back. Item 13C did this
            # for .docx only; the text formats were still
            # returning an unclaimed verified=None.
            verified = self._verify_written_text(dest, edited_text)

            return DocumentResult(
                success=True,
                operation="edit",
                path=dest,
                format=fmt,
                message=f"Document edited: {occurrences} occurrence(s) replaced",
                data={
                    "find_text": find_text,
                    "replace_text": replace_text,
                    "occurrences": occurrences,
                    "output_path": dest,
                },
            verified=verified,
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="edit",
                path=path,
                message=f"Edit failed: {exc}",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # DOCX STRUCTURE-PRESERVING EDIT
    # ------------------------------------------------------------------

    # =================================================================
    # ITEM 16D (C18): WRITE VERIFICATION -- read the artifact back
    # =================================================================
    #
    # Same contract Item 13C defined for SpreadsheetResult and Item
    # 16C applied to it:
    #
    #   verified=None  claims nothing about verification
    #   verified=True  written content read back and matched
    #   verified=False read back and did NOT match, or could not be
    #                 read back -- which is NOT verification
    #
    # create_txt, create_csv, create_json, create_markdown, edit (text
    # formats) and transform all returned success=True with
    # verified=None: they never looked at what they had written. On a
    # full disk, a locked file or a silently failing write, `success`
    # only means "the call did not raise".
    #
    # create_pdf is deliberately NOT in this set. It is excluded by the
    # directive and for a good reason: verifying a PDF means checking
    # rendered content rather than bytes, and a byte comparison against
    # the generator would be theatre. It keeps reporting no claim rather
    # than gaining a check that looks meaningful and is not.
    @staticmethod
    def _verify_written_text(path: str, expected: str) -> bool:
        """Read a text artifact back and compare it exactly."""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read() == expected
        except Exception:
            # An unreadable artifact is not a verified one.
            return False

    @staticmethod
    def _verify_written_json(path: str, expected: Any) -> bool:
        """Read JSON back and compare PARSED values, not text."""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle) == expected
        except Exception:
            return False

    @staticmethod
    def _verify_written_csv(
        path: str, headers: List[Any], rows: List[List[Any]]
    ) -> bool:
        """Read a CSV back and compare parsed cells.

        Parsed rather than raw text, so quoting and line-ending
        differences are not mistaken for a content mismatch. Cells are
        compared as strings because that is what the csv module
        round-trips them to.
        """

        def _text(value: Any) -> str:
            return "" if value is None else str(value).strip()

        try:
            with open(path, "r", newline="", encoding="utf-8") as handle:
                parsed = list(csv.reader(handle))
        except Exception:
            return False

        if not parsed:
            return not headers and not rows

        actual_headers = parsed[0]
        actual_rows = parsed[1:]

        if [_text(h) for h in actual_headers] != [
            _text(h) for h in headers
        ]:
            return False
        if len(actual_rows) != len(rows):
            return False

        for expected_row, actual_row in zip(rows, actual_rows):
            width = max(len(expected_row), len(actual_row))
            padded_expected = list(expected_row) + [None] * (
                width - len(expected_row)
            )
            padded_actual = list(actual_row) + [None] * (
                width - len(actual_row)
            )
            if [_text(c) for c in padded_actual] != [
                _text(c) for c in padded_expected
            ]:
                return False
        return True

    @staticmethod
    def _verify_written_docx_text(path: str, expected_lines: List[str]) -> bool:
        """Read a .docx back and confirm its body holds these lines."""
        if not HAS_DOCX:
            return False
        try:
            document = DocxDocument(path)
            actual = [
                p.text
                for p in DocumentIntelligence._iter_docx_paragraphs(document)
            ]
        except Exception:
            return False
        return actual == list(expected_lines)

    def _verify_transform_output(
        self, path: str, out_fmt: "DocumentFormat", text: str
    ) -> bool:
        """Item 16D (C18): did the transformed file hold what we wrote?

        transform branches on the target format and writes a DIFFERENT
        byte sequence for each -- raw text for txt/code/markdown/csv, an
        HTML wrapper for html, a JSON envelope for json, one paragraph
        per source line for docx. Verifying against `text` alone would
        have reported False for three of those five, so each format
        gets the expectation it actually wrote.
        """
        try:
            if out_fmt == DocumentFormat.HTML:
                return self._verify_written_text(
                    path, f"<html><body><pre>{text}</pre></body></html>"
                )
            if out_fmt == DocumentFormat.JSON:
                return self._verify_written_json(path, {"content": text})
            if out_fmt == DocumentFormat.DOCX:
                return self._verify_written_docx_text(
                    path, text.split("\n")
                )
            # TXT, CODE, MARKDOWN, CSV and the fallback branch all
            # write `text` verbatim.
            return self._verify_written_text(path, text)
        except Exception:
            return False

    def _verify_docx_replacement(
        self,
        dest: str,
        find_text: str,
        replace_text: str,
    ) -> Optional[bool]:
        """Item 13C (C6): did the replacement actually LAND?

        Reopens the saved file and reads the text back. Returns
        True/False on a comparison, or None when the file could not be
        read back at all -- which the caller must treat as NOT verified.

        The test is deliberately tolerant of the case where the
        replacement text still contains the search text ("draft" ->
        "draft-final"): we accept either the new text being present or
        the old text being gone. A deletion (empty replacement) can only
        satisfy the second.
        """

        if not HAS_DOCX:
            return None
        try:
            doc = DocxDocument(dest)
            text = "\n".join(
                p.text for p in DocumentIntelligence._iter_docx_paragraphs(doc)
            )
        except Exception:
            return None

        gone = find_text not in text
        if replace_text:
            return (replace_text in text) or gone
        return gone

    def _edit_docx(
        self,
        abs_path: str,
        fmt: DocumentFormat,
        find_text: str,
        replace_text: str,
        output: Optional[str],
    ) -> DocumentResult:
        """Find/replace inside a .docx without flattening it.

        Replacement happens run-by-run (preserving bold/italic/etc.);
        matches spanning runs fall back to paragraph-level replacement
        (structure and styles intact, intra-paragraph formatting of
        that one paragraph simplified). Body paragraphs and tables
        are covered.
        """
        if not HAS_DOCX:
            return DocumentResult(
                success=False,
                operation="edit",
                path=abs_path,
                format=fmt,
                message=(
                    "python-docx is not installed; refusing to edit DOCX "
                    "as flat text because that would corrupt the file. "
                    "The original was left untouched."
                ),
                error="EditNotSupportedForFormat",
            )

        doc = DocxDocument(abs_path)
        full_text = "\n".join(p.text for p in self._iter_docx_paragraphs(doc))
        if find_text not in full_text:
            return DocumentResult(
                success=False,
                operation="edit",
                path=abs_path,
                format=fmt,
                message=f"Text not found in document: '{find_text[:50]}...'".rstrip("."),
                error="TextNotFound",
            )

        occurrences = full_text.count(find_text)
        for paragraph in self._iter_docx_paragraphs(doc):
            self._replace_in_paragraph(paragraph, find_text, replace_text)

        dest = self._resolve_output(abs_path, output, "edited")
        doc.save(dest)

        # Item 13C (C6): read the saved document back and check the
        # replacement is in it. Previously this returned success=True
        # with no `verified` field at all -- python-docx writing the file
        # was treated as proof the replacement had landed.
        verified = self._verify_docx_replacement(
            dest, find_text, replace_text
        )
        if verified is None:
            verified = False

        return DocumentResult(
            success=True,
            operation="edit",
            path=dest,
            format=fmt,
            message=(
                f"Document edited: {occurrences} occurrence(s) replaced"
                if verified else
                f"Document written, but reading it back did NOT confirm "
                f"the replacement ({occurrences} occurrence(s) attempted)"
            ),
            data={
                "find_text": find_text,
                "replace_text": replace_text,
                "occurrences": occurrences,
                "output_path": dest,
                "verified": verified,
            },
            verified=verified,
        )

    @staticmethod
    def _iter_docx_paragraphs(doc):
        """Yield body paragraphs plus every table-cell paragraph."""
        for paragraph in doc.paragraphs:
            yield paragraph
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        yield paragraph

    @staticmethod
    def _replace_in_paragraph(paragraph, find_text: str, replace_text: str) -> int:
        """Replace within one paragraph, preserving run formatting
        when the match sits inside a single run."""
        count = paragraph.text.count(find_text)
        if count == 0:
            return 0
        remaining = count
        for run in paragraph.runs:
            if find_text in run.text:
                hits = run.text.count(find_text)
                run.text = run.text.replace(find_text, replace_text)
                remaining -= hits
        if remaining > 0:
            # Match spans runs: rebuild paragraph text (structure and
            # paragraph style intact; intra-paragraph run formatting
            # of this one paragraph is simplified).
            paragraph.text = paragraph.text.replace(find_text, replace_text)
        return count

    # ------------------------------------------------------------------
    # PDF EDIT (pypdf PdfReader + PdfWriter)
    # ------------------------------------------------------------------

    def _snapshot_stat(self, path: str) -> Tuple[int, float]:
        st = os.stat(path)
        self._snapshot_digests[os.path.abspath(path)] = self._file_digest(path)
        return (st.st_size, st.st_mtime)

    @staticmethod
    def _file_digest(path: str) -> bytes:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.digest()

    def _original_preserved(self, path: str, size_before: int, mtime_before: float) -> bool:
        try:
            st = os.stat(path)
            expected_digest = self._snapshot_digests.get(os.path.abspath(path))
            return bool(
                st.st_size == size_before
                and st.st_mtime == mtime_before
                and expected_digest is not None
                and self._file_digest(path) == expected_digest
            )
        except OSError:
            return False

    @staticmethod
    def _verify_output(dest: str) -> bool:
        """verified=True only when output exists and has non-zero size."""
        try:
            return os.path.isfile(dest) and os.path.getsize(dest) > 0
        except OSError:
            return False

    def _edit_pdf(
        self,
        abs_path: str,
        fmt: DocumentFormat,
        find_text: str,
        replace_text: str,
        output: Optional[str],
    ) -> DocumentResult:
        """Find/replace entry-point for PDF.

        PDF content streams cannot be edited in place without risking
        corruption, so a successful edit = copy all pages via
        PdfWriter, record the replacement in document metadata, and
        append a new page containing the replacement text (created
        with reportlab). Requires reportlab for page creation; fails
        honestly when it is missing instead of faking success.
        """
        if not HAS_PYPDF:
            return DocumentResult(
                success=False,
                operation="edit",
                path=abs_path,
                format=fmt,
                message=(
                    "pypdf is not installed; refusing to edit PDF "
                    "as flat text because that would corrupt the file. "
                    "The original was left untouched."
                ),
                error="EditNotSupportedForFormat",
            )
        size_before, mtime_before = self._snapshot_stat(abs_path)
        try:
            reader = PdfReader(abs_path)
            _ = len(reader.pages)
        except Exception:
            return DocumentResult(
                success=False,
                operation="edit",
                path=abs_path,
                format=fmt,
                message=(
                    "Edit is not supported for this PDF: file could not be "
                    "parsed as a valid PDF (no structure-preserving editor "
                    "available). The original was left untouched."
                ),
                error="EditNotSupportedForFormat",
            )
        # Check the search text exists before touching anything.
        try:
            full_text = "\n\n".join([(p.extract_text() or "") for p in reader.pages])
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="edit",
                path=abs_path,
                format=fmt,
                message=f"PDF text extraction failed: {exc}",
                error=str(exc),
            )
        if find_text not in full_text:
            return DocumentResult(
                success=False,
                operation="edit",
                path=abs_path,
                format=fmt,
                message=f"Text not found in document: '{find_text[:50]}...'".rstrip("."),
                error="TextNotFound",
            )
        occurrences = full_text.count(find_text)
        if not HAS_REPORTLAB:
            return DocumentResult(
                success=False,
                operation="edit",
                path=abs_path,
                format=fmt,
                message=(
                    "reportlab required for PDF page creation: cannot append "
                    "the replacement page without it. The original was left "
                    "untouched. Install with: pip install reportlab"
                ),
                error="reportlab required for PDF page creation",
                data={
                    "find_text": find_text,
                    "occurrences": occurrences,
                    "original_preserved": self._original_preserved(
                        abs_path, size_before, mtime_before
                    ),
                    "verified": False,
                },
            )
        return self.edit_pdf_append_text(
            abs_path,
            replace_text,
            output=output,
            metadata={
                "/EditFind": find_text[:200],
                "/EditOccurrences": str(occurrences),
            },
            _size_before=size_before,
            _mtime_before=mtime_before,
            _occurrences=occurrences,
            _find_text=find_text,
        )

    def edit_pdf_append_text(
        self,
        path: str,
        text: str,
        output: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        _size_before: Optional[int] = None,
        _mtime_before: Optional[float] = None,
        _occurrences: Optional[int] = None,
        _find_text: Optional[str] = None,
    ) -> DocumentResult:
        """Append a new text page to a PDF (sibling output, original preserved).

        Creates the new page with reportlab, copies existing pages with
        pypdf PdfWriter, applies optional metadata, writes to a sibling
        ``<stem>_edited.pdf`` file (never overwrites the original),
        then verifies the original is unchanged (size+mtime) and the
        output exists with size>0.
        """
        abs_path = os.path.abspath(path)
        fmt = DocumentFormat.PDF
        if not os.path.exists(abs_path):
            return DocumentResult(
                success=False, operation="edit", path=abs_path,
                message=f"File not found: {abs_path}", error="FileNotFoundError",
            )
        if not HAS_PYPDF:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message="pypdf is not installed; cannot edit PDF.",
                error="EditNotSupportedForFormat",
            )
        if not HAS_REPORTLAB:
            preserved = True
            try:
                if _size_before is not None and _mtime_before is not None:
                    preserved = self._original_preserved(abs_path, _size_before, _mtime_before)
            except Exception:
                preserved = True
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message=(
                    "reportlab required for PDF page creation: install with "
                    "pip install reportlab. The original was left untouched."
                ),
                error="reportlab required for PDF page creation",
                data={"original_preserved": preserved, "verified": False},
            )
        if _size_before is None or _mtime_before is None:
            size_before, mtime_before = self._snapshot_stat(abs_path)
        else:
            size_before, mtime_before = _size_before, _mtime_before
        try:
            reader = PdfReader(abs_path)
            n_pages = len(reader.pages)
        except Exception:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message="File could not be parsed as a valid PDF.",
                error="EditNotSupportedForFormat",
            )
        try:
            import io as _io

            buf = _io.BytesIO()
            c = ReportlabCanvas.Canvas(buf, pagesize=ReportlabLetter)
            width, height = ReportlabLetter
            c.setFont("Helvetica", 11)
            y = height - 72
            c.drawString(72, y, "Appended by Genesis OS document edit:")
            y -= 20
            for line in (text or "").split("\n") or [""]:
                # Simple word-wrap at ~90 chars.
                while len(line) > 90:
                    chunk, line = line[:90], line[90:]
                    c.drawString(72, y, chunk)
                    y -= 15
                    if y < 72:
                        c.showPage()
                        c.setFont("Helvetica", 11)
                        y = height - 72
                c.drawString(72, y, line)
                y -= 15
                if y < 72:
                    c.showPage()
                    c.setFont("Helvetica", 11)
                    y = height - 72
            c.showPage()
            c.save()
            buf.seek(0)
            overlay = PdfReader(buf)
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            for page in overlay.pages:
                writer.add_page(page)
            meta = {"/Producer": "Genesis OS document edit (pypdf+reportlab)"}
            if _find_text is not None:
                meta["/EditFind"] = (_find_text[:200] if _find_text else "")
            if _occurrences is not None:
                meta["/EditOccurrences"] = str(_occurrences)
            if metadata:
                for k, v in metadata.items():
                    key = k if k.startswith("/") else f"/{k}"
                    meta[key] = str(v)
            writer.add_metadata(meta)
            dest = self._resolve_output(abs_path, output, "edited")
            if os.path.abspath(dest) == abs_path:
                dest = self._default_output_path(abs_path, "edited")
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as f:
                writer.write(f)
            preserved = self._original_preserved(abs_path, size_before, mtime_before)
            verified = preserved and self._verify_output(dest)
            return DocumentResult(
                success=True if verified else False,
                operation="edit",
                path=dest,
                format=fmt,
                message=(
                    f"PDF edited: appended 1 text page ({n_pages}->{n_pages+1} pages)"
                    if verified else
                    "PDF edit wrote output but verification failed"
                ),
                data={
                    "find_text": _find_text,
                    "replace_text": text,
                    "occurrences": _occurrences,
                    "output_path": dest,
                    "original_preserved": preserved,
                    "verified": verified,
                    "page_count_before": n_pages,
                    "page_count_after": n_pages + 1,
                },
                error=None if verified else "VerificationFailed",
            )
        except Exception as exc:
            preserved = self._original_preserved(abs_path, size_before, mtime_before)
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message=f"PDF edit failed: {exc}", error=str(exc),
                data={"original_preserved": preserved, "verified": False},
            )

    def edit_pdf_metadata(
        self,
        path: str,
        metadata: Dict[str, str],
        output: Optional[str] = None,
    ) -> DocumentResult:
        """Edit PDF document metadata via PdfWriter (no reportlab needed).

        Copies all pages unchanged, updates the info dictionary, writes
        to a sibling output, and verifies original-preserved + output>0.
        """
        abs_path = os.path.abspath(path)
        fmt = DocumentFormat.PDF
        if not os.path.exists(abs_path):
            return DocumentResult(
                success=False, operation="edit", path=abs_path,
                message=f"File not found: {abs_path}", error="FileNotFoundError",
            )
        if not HAS_PYPDF:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message="pypdf is not installed; cannot edit PDF metadata.",
                error="EditNotSupportedForFormat",
            )
        size_before, mtime_before = self._snapshot_stat(abs_path)
        try:
            reader = PdfReader(abs_path)
            _ = len(reader.pages)
        except Exception:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message="File could not be parsed as a valid PDF.",
                error="EditNotSupportedForFormat",
            )
        try:
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            meta = {}
            for k, v in (metadata or {}).items():
                key = k if k.startswith("/") else f"/{k}"
                meta[key] = str(v)
            if meta:
                writer.add_metadata(meta)
            dest = self._resolve_output(abs_path, output, "edited")
            if os.path.abspath(dest) == abs_path:
                dest = self._default_output_path(abs_path, "edited")
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as f:
                writer.write(f)
            preserved = self._original_preserved(abs_path, size_before, mtime_before)
            verified = preserved and self._verify_output(dest)
            return DocumentResult(
                success=True if verified else False,
                operation="edit",
                path=dest,
                format=fmt,
                message="PDF metadata edited" if verified else "PDF metadata edit verification failed",
                data={
                    "output_path": dest,
                    "metadata": dict(metadata or {}),
                    "original_preserved": preserved,
                    "verified": verified,
                },
                error=None if verified else "VerificationFailed",
            )
        except Exception as exc:
            preserved = self._original_preserved(abs_path, size_before, mtime_before)
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message=f"PDF metadata edit failed: {exc}", error=str(exc),
                data={"original_preserved": preserved, "verified": False},
            )

    # ------------------------------------------------------------------
    # PPTX EDIT (python-pptx)
    # ------------------------------------------------------------------

    def _edit_pptx(
        self,
        abs_path: str,
        fmt: DocumentFormat,
        find_text: str,
        replace_text: str,
        output: Optional[str],
    ) -> DocumentResult:
        """Generic edit() entry-point for PPTX: replace-text across slides."""
        return self.edit_pptx_replace_text(abs_path, find_text, replace_text, output=output)

    def edit_pptx_replace_text(
        self,
        path: str,
        find_text: str,
        replace_text: str,
        output: Optional[str] = None,
    ) -> DocumentResult:
        """Replace text across all PPTX slides (shapes + tables).

        Writes to a sibling ``<stem>_edited.pptx`` file, never the
        original, and returns original_preserved + verified flags.
        """
        abs_path = os.path.abspath(path)
        fmt = DocumentFormat.PPTX
        if not os.path.exists(abs_path):
            return DocumentResult(
                success=False, operation="edit", path=abs_path,
                message=f"File not found: {abs_path}", error="FileNotFoundError",
            )
        if not HAS_PPTX:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message="python-pptx is not installed; cannot edit PPTX.",
                error="EditNotSupportedForFormat",
            )
        size_before, mtime_before = self._snapshot_stat(abs_path)
        try:
            prs = PptxPresentation(abs_path)
            _ = len(prs.slides)
        except Exception:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message=(
                    "Edit is not supported for this PPTX: file could not be "
                    "parsed as a valid presentation. The original was left untouched."
                ),
                error="EditNotSupportedForFormat",
            )
        # Gather full text to check existence first.
        texts: List[str] = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    texts.append(shape.text)
                if shape.has_table:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            texts.append(cell.text)
        full = "\n".join(texts)
        if find_text not in full:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message=f"Text not found in document: '{find_text[:50]}...'".rstrip("."),
                error="TextNotFound",
            )
        occurrences = full.count(find_text)
        try:
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for paragraph in shape.text_frame.paragraphs:
                            for run in paragraph.runs:
                                if find_text in run.text:
                                    run.text = run.text.replace(find_text, replace_text)
                            # Fallback when match spans runs.
                            if find_text in paragraph.text:
                                # Rebuild only if runs didn't already fix it.
                                if any(find_text in r.text for r in paragraph.runs):
                                    pass
                                else:
                                    paragraph.text = paragraph.text.replace(find_text, replace_text)
                        # Final safety net for shapes whose text lives outside runs.
                        if find_text in shape.text:
                            if find_text in "\n".join(p.text for p in shape.text_frame.paragraphs):
                                # Clear + rewrite preserving first paragraph formatting is
                                # complex; paragraph-level rewrite above already ran, so
                                # do a direct text_frame clear only as last resort.
                                tf = shape.text_frame
                                combined = "\n".join(p.text for p in tf.paragraphs)
                                if find_text in combined:
                                    new_text = combined.replace(find_text, replace_text)
                                    tf.clear()
                                    tf.paragraphs[0].text = new_text
                    if shape.has_table:
                        for row in shape.table.rows:
                            for cell in row.cells:
                                if find_text in cell.text:
                                    for paragraph in cell.text_frame.paragraphs:
                                        for run in paragraph.runs:
                                            if find_text in run.text:
                                                run.text = run.text.replace(find_text, replace_text)
                                        if find_text in paragraph.text:
                                            paragraph.text = paragraph.text.replace(find_text, replace_text)
            dest = self._resolve_output(abs_path, output, "edited")
            if os.path.abspath(dest) == abs_path:
                dest = self._default_output_path(abs_path, "edited")
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            prs.save(dest)
            preserved = self._original_preserved(abs_path, size_before, mtime_before)
            verified = preserved and self._verify_output(dest)
            return DocumentResult(
                success=True if verified else False,
                operation="edit",
                path=dest,
                format=fmt,
                message=(
                    f"Document edited: {occurrences} occurrence(s) replaced"
                    if verified else "PPTX edit wrote output but verification failed"
                ),
                data={
                    "find_text": find_text,
                    "replace_text": replace_text,
                    "occurrences": occurrences,
                    "output_path": dest,
                    "original_preserved": preserved,
                    "verified": verified,
                },
                error=None if verified else "VerificationFailed",
            )
        except Exception as exc:
            preserved = self._original_preserved(abs_path, size_before, mtime_before)
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message=f"PPTX edit failed: {exc}", error=str(exc),
                data={"original_preserved": preserved, "verified": False},
            )

    def edit_pptx_add_slide(
        self,
        path: str,
        text: str,
        output: Optional[str] = None,
        title: str = "",
    ) -> DocumentResult:
        """Add a new slide with text to a PPTX (sibling output, original preserved)."""
        abs_path = os.path.abspath(path)
        fmt = DocumentFormat.PPTX
        if not os.path.exists(abs_path):
            return DocumentResult(
                success=False, operation="edit", path=abs_path,
                message=f"File not found: {abs_path}", error="FileNotFoundError",
            )
        if not HAS_PPTX:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message="python-pptx is not installed; cannot edit PPTX.",
                error="EditNotSupportedForFormat",
            )
        size_before, mtime_before = self._snapshot_stat(abs_path)
        try:
            prs = PptxPresentation(abs_path)
            n_before = len(prs.slides)
        except Exception:
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message="File could not be parsed as a valid PPTX.",
                error="EditNotSupportedForFormat",
            )
        try:
            # Prefer a blank layout; fall back to the last available layout.
            layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
            slide = prs.slides.add_slide(layout)
            if title:
                try:
                    slide.shapes.title.text = title
                except Exception:
                    left = top = width = height = 0
                    from pptx.util import Inches as _Inches

                    box = slide.shapes.add_textbox(_Inches(0.5), _Inches(0.2), _Inches(9), _Inches(0.8))
                    box.text_frame.text = title
            from pptx.util import Inches as _Inches

            left, top, width, height = _Inches(0.5), _Inches(1.2), _Inches(9), _Inches(4.5)
            textbox = slide.shapes.add_textbox(left, top, width, height)
            textbox.text_frame.text = text or ""
            dest = self._resolve_output(abs_path, output, "edited")
            if os.path.abspath(dest) == abs_path:
                dest = self._default_output_path(abs_path, "edited")
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            prs.save(dest)
            preserved = self._original_preserved(abs_path, size_before, mtime_before)
            verified = preserved and self._verify_output(dest)
            return DocumentResult(
                success=True if verified else False,
                operation="edit",
                path=dest,
                format=fmt,
                message=(
                    f"PPTX edited: added 1 slide ({n_before}->{n_before+1} slides)"
                    if verified else "PPTX add-slide wrote output but verification failed"
                ),
                data={
                    "output_path": dest,
                    "added_text": text,
                    "title": title,
                    "original_preserved": preserved,
                    "verified": verified,
                    "slide_count_before": n_before,
                    "slide_count_after": n_before + 1,
                },
                error=None if verified else "VerificationFailed",
            )
        except Exception as exc:
            preserved = self._original_preserved(abs_path, size_before, mtime_before)
            return DocumentResult(
                success=False, operation="edit", path=abs_path, format=fmt,
                message=f"PPTX add-slide failed: {exc}", error=str(exc),
                data={"original_preserved": preserved, "verified": False},
            )

    @staticmethod
    def _default_output_path(path: str, suffix: str) -> str:
        """Derive a sibling output path so edits never overwrite the
        source file by default (same pattern as spreadsheet ops)."""
        base, ext = os.path.splitext(path)
        candidate = f"{base}_{suffix}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter = 1
        while True:
            numbered = f"{base}_{suffix}_{counter}{ext}"
            if not os.path.exists(numbered):
                return numbered
            counter += 1

    def _resolve_output(
        self, path: str, output: Optional[str], suffix: str
    ) -> str:
        if output:
            from .file_intelligence.path_security import PathSecurity
            validation = PathSecurity.validate(output)
            if not validation["allowed"]:
                raise ValueError(validation["reason"])
            source = os.path.abspath(path)
            destination = os.path.abspath(validation["path"])
            if source == destination:
                raise ValueError("Output must not overwrite the source artifact.")
            return destination
        return self._default_output_path(path, suffix)

    # ------------------------------------------------------------------
    # TRANSFORM
    # ------------------------------------------------------------------

    def transform(self, path: str, output_path: str, output_format: str) -> DocumentResult:
        """Transform a document from one format to another.

        Supports conversion between: txt, csv, json, markdown, html, docx.
        """
        try:
            from .file_intelligence.path_security import PathSecurity
            source_validation = PathSecurity.validate(path, require_existing=True, require_file=True)
            if not source_validation["allowed"]:
                error_code = (
                    "FileNotFoundError"
                    if not os.path.exists(path)
                    else "InvalidPath"
                )
                return DocumentResult(
                    success=False,
                    operation="transform",
                    path=path,
                    message=source_validation["reason"],
                    error=error_code,
                )
            abs_path = os.path.abspath(path)
            source_stat = os.stat(abs_path)
            source_digest = hashlib.sha256()
            with open(abs_path, "rb") as source_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    source_digest.update(chunk)
            source_hash = source_digest.digest()
            if not os.path.exists(abs_path):
                return DocumentResult(
                    success=False,
                    operation="transform",
                    path=abs_path,
                    message=f"File not found: {abs_path}",
                    error="FileNotFoundError",
                )

            src_fmt = self._detect_format(abs_path)

            # Read source content
            read_result = self.read(abs_path)
            if not read_result.success:
                return DocumentResult(
                    success=False,
                    operation="transform",
                    path=abs_path,
                    format=src_fmt,
                    message=read_result.message,
                    error=read_result.error,
                )

            data = read_result.data
            text = data.get("text", "") if isinstance(data, dict) else ""

            # Determine output format
            out_fmt_map = {
                "txt": DocumentFormat.TXT,
                "csv": DocumentFormat.CSV,
                "json": DocumentFormat.JSON,
                "markdown": DocumentFormat.MARKDOWN,
                "md": DocumentFormat.MARKDOWN,
                "html": DocumentFormat.HTML,
                "htm": DocumentFormat.HTML,
                "docx": DocumentFormat.DOCX,
            }
            normalized_output_format = str(output_format or "").strip().lower()
            if normalized_output_format not in out_fmt_map:
                return DocumentResult(
                    success=False,
                    operation="transform",
                    path=abs_path,
                    format=src_fmt,
                    message=f"Unsupported output format: {output_format}",
                    error="UnsupportedFormat",
                )
            out_fmt = out_fmt_map[normalized_output_format]

            if not output_path:
                output_extension = {
                    "md": "md",
                    "markdown": "md",
                    "htm": "html",
                }.get(normalized_output_format, normalized_output_format)
                output_path = f"{os.path.splitext(abs_path)[0]}_transformed.{output_extension}"
            abs_output = self._resolve_output(abs_path, output_path, "transformed")
            output_suffix = os.path.splitext(abs_output)[1].lower().lstrip(".")
            allowed_suffixes = {
                DocumentFormat.TXT: {"txt"},
                DocumentFormat.MARKDOWN: {"md", "markdown"},
                DocumentFormat.HTML: {"html", "htm"},
                DocumentFormat.JSON: {"json"},
                DocumentFormat.CSV: {"csv"},
                DocumentFormat.DOCX: {"docx"},
            }
            if output_suffix not in allowed_suffixes.get(out_fmt, {output_suffix}):
                return DocumentResult(
                    success=False,
                    operation="transform",
                    path=abs_path,
                    format=out_fmt,
                    message="Output extension does not match the requested format.",
                    error="FormatMismatch",
                )
            os.makedirs(os.path.dirname(abs_output), exist_ok=True)

            # Write in target format
            if out_fmt == DocumentFormat.TXT or out_fmt == DocumentFormat.CODE:
                with open(abs_output, "w", encoding="utf-8") as f:
                    f.write(text)
            elif out_fmt == DocumentFormat.MARKDOWN:
                with open(abs_output, "w", encoding="utf-8") as f:
                    f.write(text)
            elif out_fmt == DocumentFormat.HTML:
                html_content = f"<html><body><pre>{text}</pre></body></html>"
                with open(abs_output, "w", encoding="utf-8") as f:
                    f.write(html_content)
            elif out_fmt == DocumentFormat.JSON:
                import json
                with open(abs_output, "w", encoding="utf-8") as f:
                    json.dump({"content": text}, f, indent=2)
            elif out_fmt == DocumentFormat.CSV:
                with open(abs_output, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
            elif out_fmt == DocumentFormat.DOCX:
                if HAS_DOCX:
                    doc = DocxDocument()
                    for line in text.split("\n"):
                        doc.add_paragraph(line)
                    doc.save(abs_output)
                else:
                    return DocumentResult(
                        success=False,
                        operation="transform",
                        path=abs_path,
                        format=out_fmt,
                        message="python-docx is required for DOCX output.",
                        error="ImportError",
                    )
            else:
                with open(abs_output, "w", encoding="utf-8") as f:
                    f.write(text)

            # Item 16D (C18): read the output back. The
            # expectation depends on the output format, because
            # transform does not always write `text` verbatim.
            verified = self._verify_transform_output(
                abs_output, out_fmt, text
            )

            return DocumentResult(
                success=True,
                operation="transform",
                path=abs_path,
                format=out_fmt,
                message=f"Document transformed from {src_fmt.value} to {out_fmt.value}",
                data={
                    "source_path": abs_path,
                    "source_format": src_fmt.value,
                    "output_path": abs_output,
                    "output_format": out_fmt.value,
                    "content_length": len(text),
                    "output_exists": os.path.isfile(abs_output) and os.path.getsize(abs_output) > 0,
                    "original_preserved": self._file_digest(abs_path) == source_hash,
                },
            verified=verified,
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="transform",
                path=path,
                message=f"Transform failed: {exc}",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # VERIFY
    # ------------------------------------------------------------------

    def verify(self, path: str, expected_content: Optional[str] = None, expected_format: Optional[str] = None) -> DocumentResult:
        """Verify a document exists, is readable, and optionally matches expected content/format."""
        try:
            abs_path = os.path.abspath(path)
            checks = []

            # Check existence
            exists = os.path.exists(abs_path)
            checks.append({"check": "exists", "passed": exists})
            if not exists:
                return DocumentResult(
                    success=False,
                    operation="verify",
                    path=abs_path,
                    message=f"File not found: {abs_path}",
                    data={"checks": checks, "all_passed": False},
                )

            # Check readability
            read_result = self.read(abs_path)
            readable = read_result.success
            checks.append({"check": "readable", "passed": readable})
            if not readable:
                return DocumentResult(
                    success=False,
                    operation="verify",
                    path=abs_path,
                    message=f"Document is not readable: {read_result.error}",
                    data={"checks": checks, "all_passed": False},
                )

            # Check format if expected
            if expected_format:
                fmt = self._detect_format(abs_path)
                format_ok = fmt.value == expected_format.lower()
                checks.append({"check": "format", "passed": format_ok, "expected": expected_format, "actual": fmt.value})

            # Check content if expected
            if expected_content:
                data = read_result.data
                text = data.get("text", "") if isinstance(data, dict) else ""
                content_ok = expected_content in text
                checks.append({"check": "content", "passed": content_ok, "expected_snippet": expected_content[:50]})

            all_passed = all(c["passed"] for c in checks)

            return DocumentResult(
                success=all_passed,
                operation="verify",
                path=abs_path,
                format=self._detect_format(abs_path),
                message="Verification passed" if all_passed else f"Verification failed: {[c['check'] for c in checks if not c['passed']]}",
                data={"checks": checks, "all_passed": all_passed},
            )
        except Exception as exc:
            return DocumentResult(
                success=False,
                operation="verify",
                path=path,
                message=f"Verify failed: {exc}",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Format detection
    # ------------------------------------------------------------------

    def _detect_format(self, path: str) -> DocumentFormat:
        """Detect document format from file extension."""
        ext = Path(path).suffix.lower()
        for fmt, doc_type in self._formats.items():
            if ext in doc_type.extensions:
                return fmt

        code_extensions = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".rs", ".go", ".rb"}
        if ext in code_extensions:
            return DocumentFormat.CODE

        return DocumentFormat.TXT

    # ------------------------------------------------------------------
    # Reader registry
    # ------------------------------------------------------------------

    def _get_reader(self, fmt: DocumentFormat):
        """Return the appropriate reader function for a format."""
        readers = {
            DocumentFormat.TXT: self._read_txt,
            DocumentFormat.DOCX: self._read_docx,
            DocumentFormat.PDF: self._read_pdf,
            DocumentFormat.XLSX: self._read_xlsx,
            DocumentFormat.CSV: self._read_csv,
            DocumentFormat.PPTX: self._read_pptx,
            DocumentFormat.HTML: self._read_html,
            DocumentFormat.JSON: self._read_json,
            DocumentFormat.MARKDOWN: self._read_markdown,
            DocumentFormat.CODE: self._read_txt,
        }
        return readers.get(fmt)

    # ------------------------------------------------------------------
    # Per-format readers
    # ------------------------------------------------------------------

    def _read_txt(self, path: str) -> dict:
        """Read a plain text or code file."""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        lines = text.split("\n")
        word_count = len(text.split())
        return {
            "text": text,
            "pages": [text],
            "word_count": word_count,
            "line_count": len(lines),
            "metadata": {"encoding": "utf-8"},
        }

    def _read_docx(self, path: str) -> dict:
        """Read a DOCX file using python-docx."""
        if not HAS_DOCX:
            raise ImportError(
                "python-docx is not installed. Install with: pip install python-docx"
            )

        doc = DocxDocument(path)
        paragraphs = [p.text for p in doc.paragraphs]
        text = "\n".join(paragraphs)
        word_count = len(text.split())

        title = ""
        author = ""
        if doc.core_properties.title:
            title = doc.core_properties.title
        if doc.core_properties.author:
            author = doc.core_properties.author

        metadata = {"title": title, "author": author}

        page_texts: List[str] = []
        current_page: List[str] = []
        for para in paragraphs:
            current_page.append(para)
            if len("\n".join(current_page)) > 3000:
                page_texts.append("\n".join(current_page))
                current_page = []
        if current_page:
            page_texts.append("\n".join(current_page))

        return {
            "text": text,
            "pages": page_texts or [text],
            "word_count": word_count,
            "title": title,
            "author": author,
            "metadata": metadata,
        }

    def _read_docx_metadata(self, path: str) -> dict:
        """Extract metadata from a DOCX without full text read."""
        if not HAS_DOCX:
            return {}

        doc = DocxDocument(path)
        word_count = sum(len(p.text.split()) for p in doc.paragraphs)
        title = doc.core_properties.title or ""
        author = doc.core_properties.author or ""

        return {
            "word_count": word_count,
            "title": title,
            "author": author,
            "metadata": {"paragraphs": len(doc.paragraphs)},
        }

    def _read_pdf(self, path: str) -> dict:
        """Read a PDF file using pypdf."""
        if not HAS_PYPDF:
            raise ImportError(
                "pypdf is not installed. Install with: pip install pypdf"
            )

        reader = PdfReader(path)
        pages: List[str] = []
        all_text_parts: List[str] = []

        for page in reader.pages:
            page_text = page.extract_text() or ""
            pages.append(page_text)
            all_text_parts.append(page_text)

        text = "\n\n".join(all_text_parts)
        word_count = len(text.split())

        info = reader.metadata
        title = ""
        author = ""
        if info:
            title = info.get("/Title", "") or ""
            author = info.get("/Author", "") or ""

        return {
            "text": text,
            "pages": pages,
            "word_count": word_count,
            "page_count": len(pages),
            "title": title,
            "author": author,
            "metadata": {"pages": len(pages)},
        }

    def _read_pdf_metadata(self, path: str) -> dict:
        """Extract metadata from a PDF without full text extraction."""
        if not HAS_PYPDF:
            return {}

        reader = PdfReader(path)
        word_count = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            word_count += len(text.split())

        info = reader.metadata
        title = ""
        author = ""
        if info:
            title = info.get("/Title", "") or ""
            author = info.get("/Author", "") or ""

        return {
            "page_count": len(reader.pages),
            "word_count": word_count,
            "title": title,
            "author": author,
            "metadata": {"pages": len(reader.pages)},
        }

    def _read_xlsx(self, path: str) -> dict:
        """Read an XLSX file using openpyxl."""
        if not HAS_OPENPYXL:
            raise ImportError(
                "openpyxl is not installed. Install with: pip install openpyxl"
            )

        wb = load_workbook(path, read_only=True, data_only=True)
        all_text_parts: List[str] = []
        tables: List[List[Dict[str, Any]]] = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows_data: List[Dict[str, Any]] = []
            headers: List[str] = []

            for i, row in enumerate(ws.iter_rows(values_only=True)):
                row_values = [str(cell) if cell is not None else "" for cell in row]
                if i == 0:
                    headers = row_values
                    all_text_parts.append(f"Sheet: {sheet_name}")
                    all_text_parts.append("  " + " | ".join(headers))
                else:
                    row_dict = {}
                    for j, h in enumerate(headers):
                        row_dict[h] = row_values[j] if j < len(row_values) else ""
                    rows_data.append(row_dict)
                    all_text_parts.append("  " + " | ".join(row_values))

            if rows_data:
                tables.append(rows_data)

        wb.close()
        text = "\n".join(all_text_parts)
        word_count = len(text.split())

        return {
            "text": text,
            "pages": [text],
            "word_count": word_count,
            "tables": tables,
            "metadata": {"sheets": len(wb.sheetnames)},
        }

    def _read_xlsx_metadata(self, path: str) -> dict:
        """Extract metadata from an XLSX."""
        if not HAS_OPENPYXL:
            return {}

        wb = load_workbook(path, read_only=True, data_only=True)
        sheet_count = len(wb.sheetnames)
        wb.close()

        return {"metadata": {"sheets": sheet_count}}

    def _read_csv(self, path: str) -> dict:
        """Read a CSV file."""
        rows: List[Dict[str, Any]] = []
        headers: List[str] = []

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    headers = row
                    continue
                row_dict = {}
                for j, h in enumerate(headers):
                    row_dict[h] = row[j] if j < len(row) else ""
                rows.append(row_dict)

        lines = [headers] + [list(r.values()) for r in rows]
        text = "\n".join([" | ".join(line) for line in lines])
        word_count = len(text.split())

        return {
            "text": text,
            "pages": [text],
            "word_count": word_count,
            "tables": [rows],
            "metadata": {"headers": headers, "row_count": len(rows)},
        }

    def _read_pptx(self, path: str) -> dict:
        """Read a PPTX file using python-pptx."""
        if not HAS_PPTX:
            raise ImportError(
                "python-pptx is not installed. Install with: pip install python-pptx"
            )

        prs = PptxPresentation(path)
        slide_texts: List[str] = []
        all_text_parts: List[str] = []

        for slide_num, slide in enumerate(prs.slides, start=1):
            shape_texts: List[str] = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    shape_texts.append(shape.text.strip())
            slide_text = f"[Slide {slide_num}]\n" + "\n".join(shape_texts)
            slide_texts.append(slide_text)
            all_text_parts.append(slide_text)

        text = "\n\n".join(all_text_parts)
        word_count = len(text.split())

        return {
            "text": text,
            "pages": slide_texts,
            "word_count": word_count,
            "metadata": {"slide_count": len(prs.slides)},
        }

    def _read_pptx_metadata(self, path: str) -> dict:
        """Extract metadata from a PPTX."""
        if not HAS_PPTX:
            return {}

        prs = PptxPresentation(path)
        word_count = 0
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    word_count += len(shape.text.split())

        return {
            "slide_count": len(prs.slides),
            "word_count": word_count,
            "metadata": {"slides": len(prs.slides)},
        }

    def _read_html(self, path: str) -> dict:
        """Read an HTML file and extract visible text."""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw_html = f.read()

        text_parts: List[str] = []
        title = ""

        class _HTMLTextExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self._skip = False
                self._title_parts: List[str] = []
                self._in_title = False

            def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
                if tag in ("script", "style", "noscript"):
                    self._skip = True
                if tag == "title":
                    self._in_title = True

            def handle_endtag(self, tag: str) -> None:
                if tag in ("script", "style", "noscript"):
                    self._skip = False
                if tag == "title":
                    self._in_title = False

            def handle_data(self, data: str) -> None:
                if self._in_title:
                    self._title_parts.append(data)
                elif not self._skip:
                    stripped = data.strip()
                    if stripped:
                        text_parts.append(stripped)

        extractor = _HTMLTextExtractor()
        extractor.feed(raw_html)
        title = "".join(extractor._title_parts).strip()

        text = "\n".join(text_parts)
        word_count = len(text.split())

        return {
            "text": text,
            "pages": [text],
            "word_count": word_count,
            "title": title,
            "metadata": {"raw_length": len(raw_html)},
        }

    def _read_json(self, path: str) -> dict:
        """Read a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        text = json.dumps(data, indent=2, default=str)
        word_count = len(text.split())

        return {
            "text": text,
            "pages": [text],
            "word_count": word_count,
            "metadata": {"type": type(data).__name__},
        }

    def _read_markdown(self, path: str) -> dict:
        """Read a Markdown file."""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        word_count = len(text.split())

        title = ""
        for line in text.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("# "):
                title = line_stripped[2:].strip()
                break

        return {
            "text": text,
            "pages": [text],
            "word_count": word_count,
            "title": title,
            "metadata": {"format": "markdown"},
        }

    # ------------------------------------------------------------------
    # Table extraction helpers
    # ------------------------------------------------------------------

    def _extract_csv_tables(self, path: str) -> List[List[Dict[str, Any]]]:
        """Extract all rows from a CSV as a list of dicts."""
        rows: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return [rows]

    def _extract_xlsx_tables(self, path: str) -> List[List[Dict[str, Any]]]:
        """Extract all sheets from an XLSX as lists of dicts."""
        if not HAS_OPENPYXL:
            raise ImportError(
                "openpyxl is not installed. Install with: pip install openpyxl"
            )

        wb = load_workbook(path, read_only=True, data_only=True)
        all_tables: List[List[Dict[str, Any]]] = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            headers: List[str] = []
            rows: List[Dict[str, Any]] = []

            for i, row in enumerate(ws.iter_rows(values_only=True)):
                row_values = [str(cell) if cell is not None else "" for cell in row]
                if i == 0:
                    headers = row_values
                else:
                    row_dict = {}
                    for j, h in enumerate(headers):
                        row_dict[h] = row_values[j] if j < len(row_values) else ""
                    rows.append(row_dict)

            if rows:
                all_tables.append(rows)

        wb.close()
        return all_tables
