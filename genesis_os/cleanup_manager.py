"""
Genesis OS — Level 3.12
Cleanup Control.

Recycle Bin management through the official Windows shell32
API (SHEmptyRecycleBinW / SHQueryRecycleBinW).

Safety:

    - emptying the Recycle Bin is IRREVERSIBLE, so it is
      CONFIRMATION-GATED at the capability level;
    - before confirming, Genesis can QUERY how many items and
      bytes are pending so the user confirms with full
      knowledge.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


# Item 14B (C9): name the HRESULT instead of inlining a bare decimal.
#
# "The Recycle Bin was already empty" is reported as
# HRESULT_FROM_WIN32(ERROR_DIR_NOT_EMPTY) -- 0x80070091, which is
# -2147024751 when interpreted as a signed 32-bit value.
#
# This used to be tested as:
#
#     already_empty = result == -2147024879 or result == 0x80070091 % (
#         1 << 32
#     ) - (1 << 32)
#
# Two separate things were wrong with that line, and it is worth being
# precise about which was which:
#
#   1. The FIRST literal is the wrong constant. -2147024879 is
#      0x80070011 = ERROR_NOT_SAME_DEVICE -- "the move/delete crossed a
#      volume boundary". It is a completely different failure and was
#      never the empty-bin code.
#
#   2. The SECOND literal is CORRECT -- but only by luck of operator
#      precedence. `%` and `-` bind tighter than `==`, so it does
#      evaluate to `result == ((0x80070091 % (1 << 32)) - (1 << 32))`,
#      which is the right code. It was typeset across three lines with
#      the arithmetic dangling off the end of a comparison, which
#      invited exactly the kind of "helpful" re-parenthesisation that
#      would have silently broken it. Explicit parentheses and a name
#      remove both the fragility and the invitation.
#
# Only the documented code is kept. ERROR_NOT_SAME_DEVICE is dropped
# rather than carried along "just in case": nothing indicated it was
# intended, and treating an unrelated failure as "already empty" would
# report success -- and set verified=True -- for an operation that
# actually failed.
ERROR_DIR_NOT_EMPTY_HRESULT = 0x80070091 - (1 << 32)  # == -2147024751


class CleanupManager:

    VERSION = "3.12.0"

    SHERB_NOCONFIRMATION = 0x00000001
    SHERB_NOPROGRESSUI = 0x00000002
    SHERB_NOSOUND = 0x00000004

    # =========================================================
    # QUERY (read-only)
    # =========================================================

    def recycle_bin_stats(self) -> dict:
        """
        Report item count and total size of the Recycle Bin.
        """

        if not hasattr(ctypes, "windll"):
            return self._unsupported()

        class _SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong),
            ]

        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)

        try:
            result = int(
                ctypes.windll.shell32.SHQueryRecycleBinW(
                    None,
                    ctypes.byref(info),
                )
            )
        except Exception as error:
            return {
                "success": False,
                "operation": "cleanup.recycle_bin_query",
                "error": str(error),
                "verified": False,
            }

        if result != 0:
            return {
                "success": False,
                "operation": "cleanup.recycle_bin_query",
                "error": f"Shell query failed (code {result}).",
                "verified": False,
            }

        count = int(info.i64NumItems)
        size_mb = round(info.i64Size / (1024 * 1024), 2)

        return {
            "success": True,
            "operation": "cleanup.recycle_bin_query",
            "item_count": count,
            "size_mb": size_mb,
            "executed": False,
            "verified": True,
            "verification_type": "shell_query",
            "message": (
                f"The Recycle Bin holds {count} item(s) "
                f"({size_mb} MB)."
            ),
        }

    # =========================================================
    # EMPTY — CONFIRMATION GATED UPSTREAM
    # =========================================================

    def empty_recycle_bin(self) -> dict:
        """
        Permanently empty the Recycle Bin.

        The capability is confirmation-gated; by the time this
        runs the user has explicitly said yes.
        """

        if not hasattr(ctypes, "windll"):
            return self._unsupported()

        stats = self.recycle_bin_stats()

        try:
            result = int(
                ctypes.windll.shell32.SHEmptyRecycleBinW(
                    None,
                    None,
                    self.SHERB_NOCONFIRMATION
                    | self.SHERB_NOPROGRESSUI
                    | self.SHERB_NOSOUND,
                )
            )

        except Exception as error:
            return {
                "success": False,
                "operation": "cleanup.empty_recycle_bin",
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        # Item 14B (C9): 0 = success; ERROR_DIR_NOT_EMPTY = already
        # empty. Both operands now use the named HRESULT above.
        already_empty = result == ERROR_DIR_NOT_EMPTY_HRESULT

        success = result == 0 or already_empty

        after = self.recycle_bin_stats() if result == 0 else None

        verified = bool(
            after is not None
            and after.get("success")
            and after.get("item_count", 1) == 0
        ) or already_empty

        return {
            "success": success,
            "operation": "cleanup.empty_recycle_bin",
            "before_item_count": stats.get("item_count"),
            "before_size_mb": stats.get("size_mb"),
            "freed_mb": stats.get("size_mb"),
            "after_item_count": (
                after.get("item_count")
                if isinstance(after, dict)
                else 0 if already_empty else None
            ),
            "item_count": 0 if verified else None,
            "executed": True,
            "verified": verified,
            "verification_type": "shell_requery",
            "message": (
                "The Recycle Bin was already empty."
                if already_empty
                else (
                    f"Recycle Bin emptied "
                    f"({stats.get('item_count')} items, "
                    f"{stats.get('size_mb')} MB freed)."
                    if verified
                    else "The Recycle Bin could not be verified as emptied."
                )
            ),
        }

    @staticmethod
    def _unsupported():
        return {
            "success": False,
            "operation": "cleanup.recycle_bin",
            "error": "Cleanup control requires Windows.",
            "executed": False,
            "verified": False,
        }
