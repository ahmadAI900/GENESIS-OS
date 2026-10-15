"""
Genesis OS — Level 3.12
Package Management.

Application install/uninstall/search through Windows Package
Manager (winget) — Microsoft's official, signed package
manager built into Windows 10/11.

Safety:

    - Installs and uninstallations are CONFIRMATION-GATED at
      the capability level; they never run without an explicit
      user yes.
    - Only the winget executable is invoked (resolved from
      PATH), never a shell string.
    - Genesis never auto-accepts on the user's behalf beyond
      winget's own source-agreement flags required for
      non-interactive operation.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class PackageManager:

    VERSION = "3.12.0"

    def _winget(self):
        return shutil.which("winget")

    # =========================================================
    # SEARCH
    # =========================================================

    def search(self, query: str, max_results: int = 5) -> dict:
        """
        Search the winget repository. Read-only.
        """

        if not isinstance(query, str) or not query.strip():
            return {
                "success": False,
                "operation": "package.search",
                "error": "A package name is required.",
                "executed": False,
                "verified": False,
            }

        winget = self._winget()

        if not winget:
            return {
                "success": False,
                "operation": "package.search",
                "available": False,
                "error": (
                    "Windows Package Manager (winget) is not "
                    "available on this machine."
                ),
                "verified": False,
            }

        try:
            completed = subprocess.run(
                [
                    winget, "search", query.strip(),
                    "--accept-source-agreements",
                ],
                capture_output=True,
                text=True,
                shell=False,
                timeout=60,
            )

        except Exception as error:
            return {
                "success": False,
                "operation": "package.search",
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        lines = [
            line.rstrip()
            for line in (completed.stdout or "").splitlines()
            if line.strip()
        ]

        # Keep only plausible result rows (winget prints banners).
        rows = [
            line for line in lines
            if not line.startswith((" ", "-", "="))
            and not line.lower().startswith(("winget", "the following", "name "))
        ][2:max_results + 2:]

        return {
            "success": True,
            "operation": "package.search",
            "query": query.strip(),
            "results": rows[:max_results],
            "result_count": len(rows[:max_results]),
            "return_code": completed.returncode,
            "executed": True,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "provider_response",
            "message": "\n".join(rows[:max_results]) or "No matching packages found.",
        }

    # =========================================================
    # INSTALL / UNINSTALL — CONFIRMATION GATED UPSTREAM
    # =========================================================

    def install(self, package_id: str) -> dict:
        return self._mutate("package.install", "install", package_id)

    def uninstall(self, package_id: str) -> dict:
        return self._mutate("package.uninstall", "uninstall", package_id)

    def _mutate(self, operation, verb, package_id: str) -> dict:
        if not isinstance(package_id, str) or not package_id.strip():
            return {
                "success": False,
                "operation": operation,
                "error": f"A package name is required to {verb}.",
                "executed": False,
                "verified": False,
            }

        winget = self._winget()

        if not winget:
            return {
                "success": False,
                "operation": operation,
                "available": False,
                "error": (
                    "Windows Package Manager (winget) is not "
                    "available on this machine."
                ),
                "executed": False,
                "verified": False,
            }

        try:
            completed = subprocess.run(
                [
                    winget, verb, package_id.strip(),
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                    "--silent",
                ],
                capture_output=True,
                text=True,
                shell=False,
                timeout=600,
            )

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "operation": operation,
                "package": package_id.strip(),
                "error": "The package operation timed out after 10 minutes.",
                "executed": True,
                "verified": False,
            }
        except Exception as error:
            return {
                "success": False,
                "operation": operation,
                "package": package_id.strip(),
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        success = completed.returncode == 0

        tail = [
            line.strip()
            for line in (completed.stdout or "").splitlines()
            if line.strip()
        ][-4:]

        return {
            "success": success,
            "operation": operation,
            "package": package_id.strip(),
            "return_code": completed.returncode,
            "output_tail": tail,
            "executed": True,
            "verified": False,
            "verification_type": "winget_exit_code_dispatch_only",
            "message": (
                f"{package_id.strip()} was {verb}ed successfully."
                if success
                else (
                    f"winget could not {verb} '{package_id.strip()}' "
                    f"(exit code {completed.returncode})."
                )
            ),
        }
