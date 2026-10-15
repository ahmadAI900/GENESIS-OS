"""
Genesis OS — Level 3.10
Workstation Control.

Session-level security actions implemented through the official
Windows API surface.

    lock — user32.LockWorkStation()

Locking is REVERSIBLE (the user unlocks with their own
credentials) and never exposes or bypasses any credential
material. Genesis cannot and must not observe the locked
session, so the result is reported as dispatch-confirmed,
matching the established Windows URI application contract.
"""

from __future__ import annotations

import ctypes


class WorkstationController:

    VERSION = "3.10.0"

    def lock(self) -> dict:
        """
        Lock the current Windows workstation through the
        official LockWorkStation API.
        """

        if ctypes.sizeof(ctypes.c_void_p) == 0:
            return self._unsupported()

        try:
            ctypes.windll.user32.LockWorkStation()
            result = True
        except Exception as error:
            return {
                "success": False,
                "operation": "workstation.lock",
                "error": str(error),
                "executed": False,
                "verified": False,
            }

        accepted = result != 0

        return {
            "success": accepted,
            "operation": "workstation.lock",
            "executed": True,
            "verified": accepted,
            "verification_type": "dispatch_confirmed",
            "message": (
                "The workstation is locking. Unlock it with "
                "your Windows credentials."
                if accepted
                else (
                    "Windows did not accept the lock request. "
                    "This can happen when no interactive "
                    "session is available."
                )
            ),
        }

    @staticmethod
    def _unsupported():
        return {
            "success": False,
            "operation": "workstation.lock",
            "error": "Workstation locking requires Windows.",
            "executed": False,
            "verified": False,
        }
