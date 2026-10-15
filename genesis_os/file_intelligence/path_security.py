"""
Genesis OS
File Intelligence — Path Security

Level 3.3.1

Provides conservative validation of filesystem paths.

This layer does not execute anything.

It determines whether a path is structurally safe enough
for a requested file operation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict


class PathSecurity:

    VERSION = "3.3.1"

    @staticmethod
    def validate(
        path: Any,
        *,
        require_existing: bool = False,
        require_file: bool = False,
        require_directory: bool = False,
    ) -> Dict[str, Any]:

        if path is None:

            return {
                "allowed": False,
                "status": "invalid_path",
                "reason": "Path is missing.",
            }

        if not isinstance(
            path,
            (str, os.PathLike),
        ):

            return {
                "allowed": False,
                "status": "invalid_path",
                "reason": "Path must be a string or path-like object.",
            }

        raw = str(path).strip()

        if not raw:

            return {
                "allowed": False,
                "status": "invalid_path",
                "reason": "Path is empty.",
            }

        if "\x00" in raw:

            return {
                "allowed": False,
                "status": "invalid_path",
                "reason": "Path contains an invalid null character.",
            }

        if (
            len(raw) >= 2
            and raw[0] == raw[-1]
            and raw[0] in {'"', "'"}
        ):
            raw = raw[1:-1].strip()

        # Prevent path traversal with ..
        if ".." in Path(raw).parts:
            return {
                "allowed": False,
                "status": "invalid_path",
                "reason": "Path traversal (..) is not allowed.",
            }

        # Reject absolute UNC paths and network shares
        if raw.startswith("\\\\") or raw.startswith("//"):
            return {
                "allowed": False,
                "status": "invalid_path",
                "reason": "Network paths (UNC) are not allowed.",
            }

        try:

            expanded = os.path.expandvars(
                os.path.expanduser(raw)
            )

            resolved = Path(
                expanded
            ).resolve(
                strict=False
            )

        except (
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:

            return {
                "allowed": False,
                "status": "invalid_path",
                "reason": (
                    f"Path could not be normalized: "
                    f"{type(exc).__name__}"
                ),
            }

        exists = resolved.exists()

        if require_existing and not exists:

            return {
                "allowed": False,
                "status": "not_found",
                "path": str(resolved),
                "reason": "Requested path does not exist.",
            }

        if require_file and exists:

            try:

                if not resolved.is_file():

                    return {
                        "allowed": False,
                        "status": "not_a_file",
                        "path": str(resolved),
                        "reason": (
                            "Requested object is not a regular file."
                        ),
                    }

            except OSError:

                return {
                    "allowed": False,
                    "status": "error",
                    "path": str(resolved),
                    "reason": (
                        "Genesis could not determine whether "
                        "the object is a file."
                    ),
                }

        if require_directory and exists:

            try:

                if not resolved.is_dir():

                    return {
                        "allowed": False,
                        "status": "not_a_directory",
                        "path": str(resolved),
                        "reason": (
                            "Requested object is not a directory."
                        ),
                    }

            except OSError:

                return {
                    "allowed": False,
                    "status": "error",
                    "path": str(resolved),
                    "reason": (
                        "Genesis could not determine whether "
                        "the object is a directory."
                    ),
                }

        return {
            "allowed": True,
            "status": "ok",
            "path": str(resolved),
            "exists": exists,
            "reason": "Path passed structural validation.",
            "version": PathSecurity.VERSION,
        }