"""
Genesis OS — Level 3.10
Clipboard Control.

Text clipboard write and read through pyperclip, which uses the
official Windows clipboard API (no shell, no polling loops).

Verification: a copy is verified by reading the clipboard back
and comparing content.
"""

from __future__ import annotations


class ClipboardManager:

    VERSION = "3.10.0"

    MAX_TEXT_LENGTH = 1_000_000

    def __init__(self):
        try:
            import pyperclip  # noqa: F401
            self._pyperclip = pyperclip
            self.available = True
        except Exception:
            self._pyperclip = None
            self.available = False

    def _unavailable(self, operation):
        return {
            "success": False,
            "operation": operation,
            "available": False,
            "error": "Clipboard control is unavailable on this machine.",
            "verified": False,
        }

    # =========================================================
    # WRITE
    # =========================================================

    def copy(self, text) -> dict:
        """
        Place text on the system clipboard and verify by
        reading it back.
        """

        if not self.available:
            return self._unavailable("clipboard.copy")

        if not isinstance(text, str):
            text = "" if text is None else str(text)

        if not text.strip():
            return {
                "success": False,
                "operation": "clipboard.copy",
                "error": "There is no text to copy.",
                "executed": False,
                "verified": False,
            }

        if len(text) > self.MAX_TEXT_LENGTH:
            return {
                "success": False,
                "operation": "clipboard.copy",
                "error": "The text is too large for the clipboard surface.",
                "executed": False,
                "verified": False,
            }

        try:
            self._pyperclip.copy(text)
            readback = self._pyperclip.paste()
        except Exception as error:
            return {
                "success": False,
                "operation": "clipboard.copy",
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        verified = readback == text

        return {
            # Item 23C (C28): `success` is bound to the readback. A
            # copy whose text did not come back is NOT a success -- the
            # clipboard no longer holds what was written (overwritten
            # by another app, or the write silently did not land), so
            # reporting success=True here told callers the copy worked
            # when it provably did not.
            #
            #   success             the readback confirmed the text
            #   executed            pyperclip.copy ran (the write was
            #                       attempted; a mismatch is a failed
            #                       confirmation, not a failed call)
            #   trustworthy_success Item 13D field consumers read
            #
            # Deliberately NO `error` on mismatch: pyperclip.copy
            # succeeded, and an error key would collapse the executor
            # status to execution_failed, erasing the precise
            # "attempted but final state unconfirmed" signal.
            "success": verified,
            "operation": "clipboard.copy",
            "copied_length": len(text),
            "executed": True,
            "verified": verified,
            "trustworthy_success": verified,
            "post_state_matches": verified,
            "content_match": verified,
            "verification_type": "clipboard_readback",
            "message": (
                f"Copied {len(text)} character(s) to the clipboard."
                if verified
                else "The clipboard did not confirm the copied text."
            ),
        }

    # =========================================================
    # READ
    # =========================================================

    def paste(self) -> dict:
        """
        Read the current clipboard text.
        """

        if not self.available:
            return self._unavailable("clipboard.paste")

        try:
            content = self._pyperclip.paste()
        except Exception as error:
            return {
                "success": False,
                "operation": "clipboard.paste",
                "error": str(error),
                "verified": False,
            }

        if not isinstance(content, str) or not content.strip():
            return {
                "success": True,
                "operation": "clipboard.paste",
                "content": "",
                "empty": True,
                "verified": True,
                "post_state_matches": True,
                "verification_type": "clipboard_query",
                "message": "The clipboard is empty or contains no text.",
            }

        preview = content if len(content) <= 500 else (
            content[:497] + "..."
        )

        return {
            "success": True,
            "operation": "clipboard.paste",
            "content_length": len(content),
            "content_preview": preview,
            "executed": False,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "clipboard_query",
            "message": preview,
        }
