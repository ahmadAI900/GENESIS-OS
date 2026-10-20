"""Genesis OS — safe process intelligence.

Level 3.8
---------
Read-only process visibility for desktop automation.  This module deliberately
does not expose process termination, injection, suspension, or arbitrary shell
execution.  Destructive process control remains outside the Level 3.8 safe
capability surface.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any


class ProcessManager:
    VERSION = "3.8.1"

    @staticmethod
    def _exe_stem(value: str) -> str:
        """Case-fold and drop a trailing .exe so name ≡ name.exe.

        Item 22C (C24): the tasklist filter used to demand an exact
        name match, so inspect("chrome") missed a plainly-running
        chrome.exe (real tasklist output carries the suffix).
        """
        folded = value.casefold()
        if folded.endswith(".exe"):
            return folded[:-4]
        return folded

    def list(self, name: str | None = None, *, limit: int = 500) -> dict:
        """Return a deterministic, read-only process inventory."""
        if os.name != "nt":
            return {
                "success": False,
                "operation": "process.list",
                "error": "Process discovery is currently implemented for Windows.",
                "executed": False,
                "verified": False,
            }

        try:
            completed = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "success": False,
                "operation": "process.list",
                "error": str(exc),
                "executed": False,
                "verified": False,
            }

        if completed.returncode != 0:
            return {
                "success": False,
                "operation": "process.list",
                "error": completed.stderr.strip() or "tasklist failed.",
                # Item 14A (C8): executed=False.
                #
                # NUANCE WORTH NAMING: the subprocess DID spawn here,
                # so under a narrower reading of `executed` ("the
                # command was launched") this would be True. It is False
                # because `executed` means the LISTING was carried out,
                # and a non-zero tasklist produced no inventory. The
                # success path now agrees with that reading.
                "executed": False,
                "verified": False,
            }

        import csv
        from io import StringIO

        rows: list[dict[str, Any]] = []
        # Item 22C (C24): match by executable stem, case-insensitively,
        # in both directions -- "chrome" finds "chrome.exe" and vice
        # versa, the way Windows itself treats the name. A different
        # stem ("chrome" vs "chrome_proxy.exe") still does not match.
        wanted = self._exe_stem(str(name).strip()) if name else None

        try:
            parsed = csv.reader(StringIO(completed.stdout))
            for row in parsed:
                if len(row) < 2:
                    continue
                image = row[0].strip()
                pid = row[1].strip()
                if wanted and self._exe_stem(image) != wanted:
                    continue
                try:
                    pid_value: int | str = int(pid)
                except ValueError:
                    pid_value = pid
                rows.append({"name": image, "pid": pid_value})
                if len(rows) >= max(1, int(limit)):
                    break
        except Exception as exc:
            return {
                "success": False,
                "operation": "process.list",
                "error": f"Unable to parse process inventory: {exc}",
                # Item 14A (C8): executed=False -- same reasoning as the
                # returncode path: tasklist ran, but the listing it was
                # supposed to produce was never assembled.
                "executed": False,
                "verified": False,
            }

        return {
            "success": True,
            "operation": "process.list",
            "name": name,
            "processes": rows,
            "count": len(rows),
            # Item 14A (C8): executed=True.
            #
            # This said False on the SUCCESS path, which is
            # backwards. By the time we are here `tasklist` has run and
            # its CSV output has been parsed into `rows` -- the listing
            # definitely happened. `executed` is how a caller tells "we
            # actually did the thing" from "we declined to", and here
            # we did.
            "executed": True,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "process_table_query",
        }

    def inspect(self, name: str) -> dict:
        """Inspect whether a named process is currently present.

        A name matches an executable by stem, case-insensitively:
        "chrome" finds "chrome.exe" and vice versa (Item 22C).
        "Not running" is still an executed inspection -- the
        process-table query happened and answered negatively.
        """
        if not isinstance(name, str) or not name.strip():
            return {
                "success": False,
                "operation": "process.inspect",
                "error": "Process name is required.",
                "executed": False,
                "verified": False,
            }

        result = self.list(name.strip())
        if not result.get("success"):
            result["operation"] = "process.inspect"
            return result

        processes = result.get("processes", [])
        return {
            "success": True,
            "operation": "process.inspect",
            "name": name.strip(),
            "running": bool(processes),
            "pids": [p["pid"] for p in processes],
            "count": len(processes),
            # Item 22C (C24): this said False on the SUCCESS path --
            # the exact inversion list()'s success path corrected
            # under Item 14A (C8). The process-table query ran and
            # produced an answer; "not running" is a negative
            # answer, not a skipped inspection. Failure paths still
            # propagate list()'s executed=False untouched.
            "executed": True,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "process_table_query",
            "message": (
                f"{name.strip()} is running."
                if processes
                else f"{name.strip()} is not running."
            ),
        }
