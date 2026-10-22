"""Genesis OS — deterministic document creation primitives."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .file_intelligence.path_security import PathSecurity


class DocumentManager:
    VERSION = "3.8.0"

    def create_docx(self, path: Any, title: str, sections: list[dict] | None = None) -> dict:
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
            # Item 23D (C29): existence is not content. `target.is_file()`
            # was True for a zero-byte file, a truncated file, a corrupt
            # non-zip blob, and a docx whose paragraphs said something
            # else entirely -- all claimed verified=True. Verification
            # now REOPENS the saved package and confirms the paragraphs
            # actually carry the title and sections we were asked to
            # write; any exception while reading fails closed.
            #
            # `content_match` / `file_exists` are the evidence keys
            # contracts.has_meaningful_result_evidence accepts for a
            # document.* write (house pattern: verification_helpers
            # verify_doc_create, safe_file_manager). Without them a
            # legitimately content-verified write was demoted to
            # `verification_unavailable` by the EvidenceContract
            # ("verified result lacks capability-specific evidence").
            # `trustworthy_success` is the Item 13D field consumers
            # read; `success` stays bound to the save itself completing.
            verified = self._verify_saved_document(target, title, sections)
            return {"success": verified, "operation": "document.create_docx",
                    "path": str(target), "executed": True,
                    "verified": verified,
                    "trustworthy_success": verified,
                    "verification_type": "docx_content_readback",
                    "file_exists": target.is_file(),
                    "content_match": verified,
                    "post_state_matches": verified}
        except Exception as exc:
            return {"success": False, "operation": "document.create_docx", "error": str(exc), "executed": False, "verified": False}

    def _verify_saved_document(self, target: Path, title: str, sections: list[dict] | None) -> bool:
        """Reopen the saved docx and confirm the content we wrote.

        Fails closed: the file is missing or zero-length, python-docx
        cannot open it (empty or corrupt packages raise
        ``PackageNotFoundError``), or any expected paragraph -- the
        title plus each truthy section heading/body, mirrored from the
        exact conditions the write above used -- is absent from the
        reopened document. Localised/odd input cannot make this return
        True without the paragraphs actually being there.
        """
        try:
            if not target.is_file() or target.stat().st_size <= 0:
                return False
            from docx import Document

            doc = Document(str(target))
            written = [paragraph.text for paragraph in doc.paragraphs]

            expected = [str(title)]
            for section in sections or []:
                # Mirror the write loop line for line: same truthiness
                # gates, same str() coercion, same insertion order.
                heading = section.get("heading") if isinstance(section, dict) else None
                body = section.get("body", "") if isinstance(section, dict) else str(section)
                if heading:
                    expected.append(str(heading))
                if body:
                    expected.append(str(body))

            return all(text in written for text in expected)
        except Exception:
            return False
