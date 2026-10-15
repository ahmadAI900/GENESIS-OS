"""Genesis OS — deterministic document creation primitives."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .file_intelligence.path_security import PathSecurity


class DocumentManager:
    VERSION = "3.8.0"

    def create_docx(self, path: Any, title: str, sections: list[dict] | None = None, *, confirmed=False) -> dict:
        # `confirmed` is ACCEPTED BUT IGNORED (Item 3B-3b); it is not an
        # authority. Replacing an existing document is Tier 1 at the
        # executor's blast-radius gate (Item 3B-3a) and requires a valid
        # AuthorizationGrant before this is reached; a create onto a free
        # path is Tier 2 and proceeds.
        v = PathSecurity.validate(path)
        if not v["allowed"]:
            return {"success": False, "operation": "document.create_docx", "error": v["reason"]}
        target = Path(v["path"])
        try:
            from docx import Document
        except ImportError:
            return {"success": False, "operation": "document.create_docx", "error": "DOCX support requires python-docx."}
        try:
            doc = Document()
            doc.add_heading(str(title), level=0)
            for section in sections or []:
                heading = section.get("heading") if isinstance(section, dict) else None
                body = section.get("body", "") if isinstance(section, dict) else str(section)
                if heading:
                    doc.add_heading(str(heading), level=1)
                if body:
                    doc.add_paragraph(str(body))
            target.parent.mkdir(parents=True, exist_ok=True)
            doc.save(target)
            return {"success": True, "operation": "document.create_docx", "path": str(target), "executed": True, "verified": target.is_file()}
        except Exception as exc:
            return {"success": False, "operation": "document.create_docx", "error": str(exc), "executed": False, "verified": False}
