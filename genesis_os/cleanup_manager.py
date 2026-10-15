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

        # 0 = success; 0x80070091 = bin was already empty.
        already_empty = result == -2147024879 or result == 0x80070091 % (
            1 << 32
        ) - (1 << 32)

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
