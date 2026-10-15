"""
Genesis OS — Level 3.12
Window Management.

Desktop window control through the official Windows Shell
COM interface (the same interface Explorer itself uses):

    - MinimizeAll / UndoMinimizeALL / ToggleDesktop

No window enumeration hacks, no synthetic alt-tab spam.
"""

from __future__ import annotations


class WindowManager:

    VERSION = "3.12.0"

    def __init__(self):
        try:
            import win32com.client  # noqa: F401
            self.available = True
        except Exception:
            self.available = False

    def _shell(self):
        import win32com.client

        return win32com.client.Dispatch("Shell.Application")

    def _dispatch(self, operation, method_name, present_tense):
        if not self.available:
            return {
                "success": False,
                "operation": operation,
                "available": False,
                "error": (
                    "Window management requires the Windows "
                    "COM bridge (pywin32)."
                ),
                "executed": False,
                "verified": False,
            }

        try:
            shell = self._shell()
            getattr(shell, method_name)()
        except Exception as error:
            return {
                "success": False,
                "operation": operation,
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        return {
            "success": True,
            "operation": operation,
            "executed": True,
            "verified": False,
            "verification_type": "unverified_shell_dispatch",
            "verification_reason": "Shell dispatch completed, but desktop state was not independently observed.",
            "message": f"{present_tense}.",
        }

    # =========================================================
    # PUBLIC OPERATIONS
    # =========================================================

    def minimize_all(self) -> dict:
        return self._dispatch(
            "window.minimize_all",
            "MinimizeAll",
            "All windows minimized",
        )

    def restore_all(self) -> dict:
        return self._dispatch(
            "window.restore",
            "UndoMinimizeALL",
            "Windows restored",
        )

    def toggle_desktop(self) -> dict:
        return self._dispatch(
            "window.show_desktop",
            "ToggleDesktop",
            "Toggled desktop visibility",
        )
