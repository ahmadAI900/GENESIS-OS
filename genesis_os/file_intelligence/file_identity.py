"""
Genesis OS
File Intelligence — File Identity

Level 3.3.1

Responsible for representing a filesystem object without
performing any destructive operation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class FileIdentity:
    """
    Canonical identity of a filesystem object.
    """

    path: str

    absolute_path: str

    name: str

    stem: str

    extension: str

    parent: str

    exists: bool

    is_file: bool

    is_directory: bool

    is_symlink: bool

    size: Optional[int] = None

    created_at: Optional[float] = None

    modified_at: Optional[float] = None

    accessed_at: Optional[float] = None

    @property
    def object_type(self) -> str:

        if self.is_symlink:
            return "symlink"

        if self.is_file:
            return "file"

        if self.is_directory:
            return "directory"

        return "unknown"

    def to_dict(self) -> Dict[str, Any]:

        return {
            "path": self.path,
            "absolute_path": self.absolute_path,
            "name": self.name,
            "stem": self.stem,
            "extension": self.extension,
            "parent": self.parent,
            "exists": self.exists,
            "is_file": self.is_file,
            "is_directory": self.is_directory,
            "is_symlink": self.is_symlink,
            "object_type": self.object_type,
            "size": self.size,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "accessed_at": self.accessed_at,
        }


class FileIdentityBuilder:
    """
    Builds FileIdentity objects safely.

    This class does not read file contents.
    """

    @staticmethod
    def normalize_path(
        path: Any,
    ) -> Optional[Path]:

        if path is None:
            return None

        if not isinstance(path, (str, os.PathLike)):
            return None

        raw = str(path).strip()

        if not raw:
            return None

        # Remove surrounding quotes only.
        if (
            len(raw) >= 2
            and raw[0] == raw[-1]
            and raw[0] in {'"', "'"}
        ):
            raw = raw[1:-1].strip()

        if not raw:
            return None

        try:

            expanded = os.path.expandvars(
                os.path.expanduser(raw)
            )

            candidate = Path(
                expanded
            )

            # resolve(strict=False) normalizes . and ..
            # without requiring the target to exist.
            return candidate.resolve(
                strict=False
            )

        except (
            OSError,
            RuntimeError,
            ValueError,
        ):
            return None

    @classmethod
    def build(
        cls,
        path: Any,
    ) -> Optional[FileIdentity]:

        raw = str(path).strip() if isinstance(path, (str, os.PathLike)) else None
        if raw and len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1].strip()
        raw_path = Path(os.path.expandvars(os.path.expanduser(raw))) if raw else None
        is_symlink = raw_path.is_symlink() if raw_path is not None else False

        normalized = cls.normalize_path(
            path
        )

        if normalized is None:
            return None

        exists = normalized.exists()

        is_file = False
        is_directory = False

        try:

            if exists:
                is_file = normalized.is_file()
                is_directory = normalized.is_dir()

        except OSError:
            pass

        stat_result = None

        if exists:

            try:
                stat_result = normalized.stat()

            except (
                OSError,
                PermissionError,
            ):
                stat_result = None

        return FileIdentity(
            path=str(path),

            absolute_path=str(
                normalized
            ),

            name=normalized.name,

            stem=normalized.stem,

            extension=(
                normalized.suffix.lower()
            ),

            parent=str(
                normalized.parent
            ),

            exists=exists,

            is_file=is_file,

            is_directory=is_directory,

            is_symlink=is_symlink,

            size=(
                stat_result.st_size
                if stat_result
                else None
            ),

            created_at=(
                getattr(
                    stat_result,
                    "st_ctime",
                    None,
                )
                if stat_result
                else None
            ),

            modified_at=(
                getattr(
                    stat_result,
                    "st_mtime",
                    None,
                )
                if stat_result
                else None
            ),

            accessed_at=(
                getattr(
                    stat_result,
                    "st_atime",
                    None,
                )
                if stat_result
                else None
            ),
        )