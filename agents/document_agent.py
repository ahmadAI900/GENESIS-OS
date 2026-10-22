from agents.base_agent import BaseAgent
from ai.ai_engine import AIEngine
from pathlib import Path
from typing import Optional
import re


class DocumentAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Document Agent",
            description=(
                "Reads, analyzes, summarizes, compares, "
                "and answers questions about documents."
            ),
            capabilities=[
                "document_reading",
                "document_analysis",
                "document_summarization",
                "document_question_answering",
                "document_comparison"
            ]
        )

        self.ai = ai_engine or AIEngine()

    # ==========================================
    # CAPABILITY DETECTION
    # ==========================================

    def can_handle(self, task):

        keywords = [
            "document",
            "pdf",
            "file",
            "summarize document",
            "analyze document",
            "read document",
            "compare documents",
            "work sheet"
        ]

        task = task.lower()

        return any(
            keyword in task
            for keyword in keywords
        )

    # ==========================================
    # MAIN DOCUMENT ENGINE
    # ==========================================

    def run(self, task, context=None):

        print(
            f"[Document Agent] Processing: {task}"
        )

        # ==========================================
        # LEVEL 2.5 — REAL DOCUMENT TOOLS
        #
        # 1. READ: if the task mentions an existing
        #    .docx/.txt file, extract its REAL text and feed
        #    it to the AI.
        #
        # 2. WRITE: if the task asks to create/write a
        #    document, generate content and produce a REAL
        #    DOCX file, verified by re-opening it.
        # ==========================================

        import re as _re

        from agents.agent_tools import AgentWorkspace

        tool_metadata = {"operation": "document_analysis"}

        document_text = ""
        creation_requested = _re.search(
            r"\b(create|write|make|draft)\b.*\b(document|report|letter|"
            r"essay|summary doc)\b",
            task,
            _re.IGNORECASE,
        )

        # Document path detection: split on whitespace and
        # test each token that ends in .txt or .docx as a
        # real file via ``Path(...).is_file()``. The previous
        # single-regex (``r"[\w\- ./\\]+\\.(?:txt|docx)"``)
        # greedily matched leading words too, so
        # "summarize /tmp/x/meeting.txt" captured the whole
        # sentence and ``Path(...).is_file()`` returned False
        # for any natural sentence with words before the path,
        # silently skipping real file content.
        #
        # ``read_match`` is preserved as a regex-Match-like
        # wrapper exposing ``.group(1)`` so downstream code
        # (``candidate = Path(read_match.group(1).strip())``)
        # keeps working unchanged.
        read_match_obj: Optional[re.Match] = None
        for raw in _re.split(r"\s+", task):
            token = raw.strip().strip("\"'()[]{}<>.,!?;:")
            if not token:
                continue
            lowered = token.lower()
            if not lowered.endswith((".txt", ".docx", ".pdf", ".pptx", ".xlsx", ".xlsm")):
                continue
            candidate = Path(token).expanduser()
            if candidate.is_file():
                # Wrap the resolved path so callers using
                # ``read_match.group(1)`` continue to work.
                class _PathMatch:
                    def group(self, idx):
                        assert idx == 1
                        return str(candidate)
                read_match_obj = _PathMatch()
        read_match = read_match_obj

        try:
            if not hasattr(self, "workspace"):
                self.workspace = AgentWorkspace()

        except Exception as tool_error:
            tool_metadata["tool_error"] = str(tool_error)

        # --------------------------------------
        # 1. REAL DOCUMENT READING
        # --------------------------------------

        if read_match and not creation_requested:
            candidate = Path(read_match.group(1).strip()).expanduser()

            if candidate.is_file():
                extracted = self._extract_text(candidate)

                if extracted:
                    document_text = (
                        f"\nREAL DOCUMENT CONTENT "
                        f"({candidate.name}) — analyze THIS text, "
                        f"do not invent any other content:\n\n"
                        f"{extracted[:6000]}\n"
                    )

                    print(
                        "[Document Agent] Extracted",
                        len(extracted),
                        "characters from",
                        candidate.name,
                    )

                    tool_metadata["read_document"] = str(candidate)
                    tool_metadata["extracted_chars"] = len(extracted)

        prompt = f"""
You are Genesis Document Agent.

The user requested:

{task}

{document_text}
Your job is to help with document-related work.

Possible operations include:

- reading document content
- summarizing documents
- extracting important information
- answering questions about documents
- comparing documents
- organizing document information
- creating new documents when explicitly requested

Rules:

- Do not invent document content.
- If document content is unavailable, clearly state that.
- Separate information found in the document from assumptions.
- Keep the result structured and useful.

{"The user wants a NEW document created. Write the full document content now, using clear section headings on their own lines." if creation_requested else ""}
"""

        response = self.ai.generate_response(
            prompt
        )

        # --------------------------------------
        # 2. REAL DOCX CREATION
        # --------------------------------------

        if creation_requested:
            docx_result = self._create_docx_from_text(
                title=self._derive_title(task),
                text=response,
            )

            if docx_result.get("success"):
                response = (
                    response
                    + f"\n\n---\n📄 **Real DOCX created & verified:** "
                    f"`{docx_result['path']}` "
                    f"({docx_result['paragraph_count']} paragraphs)"
                )

                tool_metadata["artifact_saved"] = True
                tool_metadata["artifact_path"] = docx_result["path"]
                tool_metadata["paragraph_count"] = docx_result[
                    "paragraph_count"
                ]

            else:
                response = (
                    response
                    + "\n\n---\n⚠️ The DOCX file could not be "
                    "created; the content above is the document text."
                )
                tool_metadata["artifact_error"] = docx_result.get(
                    "error", "unknown"
                )

        return self.create_result(
            task=task,
            response=response,
            success=True,
            metadata={
                **tool_metadata
            }
        )

    # ==========================================
    # DOCUMENT TOOL IMPLEMENTATIONS
    # ==========================================

    @staticmethod
    def _extract_text(path) -> str:
        """
        Extract plain text from .txt or .docx files.
        """

        suffix = path.suffix.lower()

        try:
            if suffix == ".txt":
                return path.read_text(encoding="utf-8", errors="replace")

            if suffix == ".docx":
                from docx import Document as DocxDocument

                document = DocxDocument(str(path))

                return "\n".join(
                    paragraph.text
                    for paragraph in document.paragraphs
                    if paragraph.text.strip()
                )

            if suffix == ".pdf":
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            if suffix == ".pptx":
                from pptx import Presentation
                presentation = Presentation(str(path))
                parts = []
                for slide in presentation.slides:
                    for shape in slide.shapes:
                        if hasattr(shape, "text"):
                            parts.append(shape.text)
                return "\n".join(parts)
            if suffix in (".xlsx", ".xlsm"):
                from openpyxl import load_workbook
                workbook = load_workbook(str(path), read_only=True, data_only=True)
                try:
                    return "\n".join(
                        "\t".join("" if value is None else str(value) for value in row)
                        for sheet in workbook.worksheets
                        for row in sheet.iter_rows(values_only=True)
                    )
                finally:
                    workbook.close()
        except Exception:
            return ""

        return ""

    @staticmethod
    def _derive_title(task: str) -> str:
        cleaned = re.sub(
            r"\b(create|write|make|draft|a|an|the|about|for|me|please|document|report|letter|essay)\b",
            " ",
            task,
            flags=re.IGNORECASE,
        )

        title = " ".join(cleaned.split()).strip().title()

        return title[:60] or "Genesis Document"

    def _create_docx_from_text(self, title: str, text: str) -> dict:
        """
        Build a real .docx from the AI's document text and
        verify by reopening it.
        """

        try:
            from docx import Document as DocxDocument
        except Exception as error:
            return {"success": False, "error": f"python-docx unavailable: {error}"}

        try:
            document = DocxDocument()
            document.add_heading(title, level=0)

            paragraph_count = 0

            for line in (text or "").splitlines():
                line = line.strip()

                if not line:
                    continue

                if line.startswith("### "):
                    document.add_heading(line[4:], level=3)
                elif line.startswith("## "):
                    document.add_heading(line[3:], level=2)
                elif line.startswith("# "):
                    document.add_heading(line[2:], level=1)
                else:
                    cleaned = line.lstrip("-• ").strip()
                    if not cleaned:
                        continue
                    document.add_paragraph(cleaned)
                    paragraph_count += 1

            # Item 27D (L9): the artifact save that used to live here
            # was `self.workspace.save_text_artifact(...) if False
            # else None` -- a dead branch whose result was never read.
            # The document is written below (document.save(target))
            # and verified by reopening it, so the dead call is gone.

            directory = self.workspace.base_root / "Documents"
            directory.mkdir(parents=True, exist_ok=True)

            from datetime import datetime as _dt
            from agents.agent_tools import _slugify

            target = directory / (
                f"{_dt.now().strftime('%Y%m%d_%H%M%S')}_"
                f"{_slugify(title)}.docx"
            )

            document.save(str(target))

            # VERIFICATION: reopen and count real paragraphs.
            reopened = DocxDocument(str(target))
            verified_count = len(reopened.paragraphs)

            verified = verified_count >= paragraph_count

            return {
                "success": bool(verified),
                "operation": "document.create_docx",
                "path": str(target),
                "paragraph_count": verified_count,
                "executed": True,
                "verified": bool(verified),
                "verification_type": "docx_reopen",
            }

        except Exception as error:
            return {"success": False, "error": str(error)}

    # ==========================================
    # DIRECT INTERFACE
    # ==========================================

    def analyze(self, task):

        return self.run(task)

    # ==========================================
    # UNIVERSAL AGENT INTERFACE
    # ==========================================

    def execute(self, task, context=None):

        self.start()

        try:

            result = self.run(
                task,
                context
            )

            if context:

                context.add_result(
                    self.name,
                    result
                )

            return result

        finally:

            self.stop()