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
                "executed": True,
                "verified": False,
            }

        import csv
        from io import StringIO

        rows: list[dict[str, Any]] = []
        wanted = str(name).strip().casefold() if name else None

        try:
            parsed = csv.reader(StringIO(completed.stdout))
            for row in parsed:
                if len(row) < 2:
                    continue
                image = row[0].strip()
                pid = row[1].strip()
                if wanted and image.casefold() != wanted:
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
                "executed": True,
                "verified": False,
            }

        return {
            "success": True,
            "operation": "process.list",
            "name": name,
            "processes": rows,
            "count": len(rows),
            "executed": False,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "process_table_query",
        }

    def inspect(self, name: str) -> dict:
        """Inspect whether a named process is currently present."""
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
            "executed": False,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "process_table_query",
            "message": (
                f"{name.strip()} is running."
                if processes
                else f"{name.strip()} is not running."
            ),
        }
