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
            # LockWorkStation returns a BOOL: nonzero means the lock was
            # accepted. That return value was previously discarded and
            # `result` was hardcoded to True, so a refusal by Windows
            # (for example with no interactive session) was reported as
            # success=True / verified=True. The `accepted = ...` branch
            # below already existed and correctly described a refusal; it
            # was simply unreachable.
            result = ctypes.windll.user32.LockWorkStation()
        except Exception as error:
            return {
                "success": False,
                "operation": "workstation.lock",
                "error": str(error),
                "executed": False,
                "verified": False,
            }

        accepted = bool(result)

        return {
            "success": accepted,
            "operation": "workstation.lock",
            # `executed` now tracks the API's own verdict. Reporting
            # executed=True alongside success=False would claim the
            # request took effect when Windows declined it.
            "executed": accepted,
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
