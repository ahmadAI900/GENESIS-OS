"""
Genesis OS — Level 3.12
Notes.

Plain-text personal notes stored under the user's own
Documents folder:

    ~/Documents/Genesis Notes/

Creation is verified by reading the file back; listing is a
read-only directory query. No cloud, no accounts — the user's
own disk.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class NotesManager:

    VERSION = "3.12.0"

    MAX_NOTE_CHARS = 100_000

    def __init__(self, base_dir=None):
        self.base_dir = (
            Path(base_dir)
            if base_dir is not None
            else Path.home() / "Documents" / "Genesis Notes"
        )

    # =========================================================
    # CREATE
    # =========================================================

    def create_note(self, text: str) -> dict:
        """
        Save one note with a timestamped filename.
        """

        if not isinstance(text, str) or not text.strip():
            return {
                "success": False,
                "operation": "notes.create",
                "error": "There is no note content to save.",
                "executed": False,
                "verified": False,
            }

        text = text.strip()

        if len(text) > self.MAX_NOTE_CHARS:
            return {
                "success": False,
                "operation": "notes.create",
                "error": "The note is too large for this surface.",
                "executed": False,
                "verified": False,
            }

        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)

            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

            slug_source = "".join(
                ch if ch.isalnum() else "-"
                for ch in text[:40]
            ).strip("-").lower()

            slug = "-".join(
                part for part in slug_source.split("-") if part
            )[:40] or "note"

            target = self.base_dir / f"{stamp}_{slug}.txt"

            target.write_text(
                f"{text}\n\n-- Genesis note, "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
                encoding="utf-8",
            )

        except OSError as error:
            return {
                "success": False,
                "operation": "notes.create",
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        # -----------------------------------------------------
        # READBACK VERIFICATION
        # -----------------------------------------------------

        try:
            saved = target.read_text(encoding="utf-8")
        except OSError as error:
            return {
                "success": False,
                "operation": "notes.create",
                "path": str(target),
                "error": f"The note could not be read back: {error}",
                "executed": True,
                "verified": False,
            }

        verified = text in saved

        return {
            "success": bool(verified),
            "operation": "notes.create",
            "path": str(target),
            "length": len(text),
            "executed": True,
            "verified": bool(verified),
            "post_state_matches": bool(verified),
            "content_match": bool(verified),
            "verification_type": "file_readback",
            "message": f"Note saved: '{text[:60]}{'...' if len(text) > 60 else ''}'",
        }

    # =========================================================
    # LIST / READ
    # =========================================================

    def list_notes(self) -> dict:
        """
        List existing notes, newest first.
        """

        if not self.base_dir.exists():
            return {
                "success": True,
                "operation": "notes.list",
                "notes": [],
                "count": 0,
                "verified": True,
                "post_state_matches": True,
                "verification_type": "directory_query",
                "message": "You have no notes yet.",
            }

        try:
            files = sorted(
                (p for p in self.base_dir.glob("*.txt") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError as error:
            return {
                "success": False,
                "operation": "notes.list",
                "error": str(error),
                "verified": False,
            }

        notes = []

        for path in files[:50]:
            try:
                first_line = next(
                    (line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()),
                    "(empty note)",
                )
            except OSError:
                first_line = "(unreadable note)"

            notes.append({
                "file": path.name,
                "preview": first_line[:120],
            })

        preview_lines = [
            f"{i}. {note['preview']}"
            for i, note in enumerate(notes, start=1)
        ]

        message = (
            "\n".join(preview_lines)
            if notes
            else "You have no notes yet."
        )

        return {
            "success": True,
            "operation": "notes.list",
            "notes": notes,
            "count": len(notes),
            "verified": True,
            "verification_type": "directory_query",
            "message": message,
        }
