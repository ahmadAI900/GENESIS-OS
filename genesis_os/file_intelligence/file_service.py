"""
Genesis OS
Level 3.7.1 — Universal File Intelligence Service

Provides a canonical, deterministic facade over the existing
File Intelligence subsystem.

Responsibilities:

    - safe file inspection
    - safe existence checks
    - deterministic file discovery
    - canonical path handling
    - file classification
    - capability reporting
    - structured FileResult output

This layer DOES NOT modify files.

Destructive and mutating operations belong to later Level 3.7
capabilities and must pass ExecutionSafety + ActionExecutor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .file_inspector import FileInspector
from .file_result import FileResult, FileStatus
from .file_registry import FileTypeRegistry
from .path_security import PathSecurity


class FileIntelligenceService:
    """
    Canonical Level 3.7 file-intelligence facade.

    This class composes the existing Genesis file-intelligence
    primitives rather than replacing them.
    """

    VERSION = "3.7.1"

    def __init__(
        self,
        inspector: Optional[FileInspector] = None,
        registry: Optional[FileTypeRegistry] = None,
    ) -> None:

        self.registry = (
            registry
            if registry is not None
            else FileTypeRegistry()
        )

        self.inspector = (
            inspector
            if inspector is not None
            else FileInspector(
                registry=self.registry
            )
        )

    # =========================================================
    # PATH NORMALIZATION
    # =========================================================

    @staticmethod
    def normalize(
        path: Any,
    ) -> FileResult:
        """
        Normalize and structurally validate a path.

        No filesystem modification occurs.
        """

        validation = PathSecurity.validate(
            path
        )

        if not validation.get("allowed"):
            return FileResult.failure_result(
                operation="file.normalize",
                status=validation.get(
                    "status",
                    FileStatus.INVALID_PATH,
                ),
                path=validation.get("path"),
                message=validation.get(
                    "reason",
                    "Path validation failed.",
                ),
                error=validation.get("reason"),
                safety={
                    "allowed": False,
                    "validation": validation,
                },
            )

        normalized = validation["path"]

        return FileResult.success_result(
            operation="file.normalize",
            path=normalized,
            message="Path normalized successfully.",
            metadata={
                "exists": bool(
                    validation.get(
                        "exists",
                        False,
                    )
                ),
            },
            evidence={
                "path_validation": validation,
            },
            safety={
                "allowed": True,
                "analysis_only": True,
            },
        )

    # =========================================================
    # INSPECTION
    # =========================================================

    def inspect(
        self,
        path: Any,
    ) -> FileResult:
        """
        Inspect a filesystem object through the existing
        FileInspector.
        """

        result = self.inspector.inspect(
            path
        )

        return self._attach_service_metadata(
            result
        )

    # =========================================================
    # EXISTENCE
    # =========================================================

    def exists(
        self,
        path: Any,
    ) -> FileResult:
        """
        Determine whether a filesystem object exists.
        """

        validation = PathSecurity.validate(
            path
        )

        if not validation.get("allowed"):
            return FileResult.failure_result(
                operation="file.exists",
                status=validation.get(
                    "status",
                    FileStatus.INVALID_PATH,
                ),
                path=validation.get("path"),
                message=validation.get(
                    "reason",
                    "Path validation failed.",
                ),
                error=validation.get("reason"),
                safety={
                    "allowed": False,
                    "validation": validation,
                },
            )

        normalized = validation["path"]

        exists = bool(
            validation.get(
                "exists",
                False,
            )
        )

        if exists:
            return FileResult.success_result(
                operation="file.exists",
                path=normalized,
                message="The filesystem object exists.",
                metadata={
                    "exists": True,
                },
                evidence={
                    "path_validation": validation,
                },
                safety={
                    "allowed": True,
                    "analysis_only": True,
                },
            )

        return FileResult.failure_result(
            operation="file.exists",
            status=FileStatus.NOT_FOUND,
            path=normalized,
            message=(
                "The requested filesystem object "
                "does not exist."
            ),
            metadata={
                "exists": False,
            },
            evidence={
                "path_validation": validation,
            },
            safety={
                "allowed": True,
                "analysis_only": True,
            },
        )

    # =========================================================
    # DISCOVERY
    # =========================================================

    def discover(
        self,
        directory: Any,
        *,
        pattern: str = "*",
        recursive: bool = False,
        files_only: bool = False,
        directories_only: bool = False,
    ) -> FileResult:
        """
        Deterministically discover filesystem objects.

        Discovery is read-only.

        Results are sorted by normalized absolute path so the
        same request produces deterministic output.
        """

        if files_only and directories_only:
            return FileResult.failure_result(
                operation="file.discover",
                status=FileStatus.INVALID_PATH,
                path=None,
                message=(
                    "files_only and directories_only "
                    "cannot both be enabled."
                ),
                error=(
                    "Conflicting discovery filters."
                ),
                safety={
                    "allowed": False,
                },
            )

        validation = PathSecurity.validate(
            directory,
            require_existing=True,
            require_directory=True,
        )

        if not validation.get("allowed"):
            return FileResult.failure_result(
                operation="file.discover",
                status=validation.get(
                    "status",
                    FileStatus.INVALID_PATH,
                ),
                path=validation.get("path"),
                message=validation.get(
                    "reason",
                    "Directory validation failed.",
                ),
                error=validation.get("reason"),
                safety={
                    "allowed": False,
                    "validation": validation,
                },
            )

        root = Path(
            validation["path"]
        )

        try:
            iterator = (
                root.rglob(pattern)
                if recursive
                else root.glob(pattern)
            )

            entries: List[Dict[str, Any]] = []

            for candidate in iterator:

                try:
                    is_file = candidate.is_file()
                    is_directory = candidate.is_dir()

                    if files_only and not is_file:
                        continue

                    if directories_only and not is_directory:
                        continue

                    entries.append(
                        {
                            "path": str(
                                candidate.resolve(
                                    strict=False
                                )
                            ),
                            "name": candidate.name,
                            "extension": (
                                candidate.suffix.lower()
                            ),
                            "is_file": is_file,
                            "is_directory": is_directory,
                        }
                    )

                except (
                    OSError,
                    PermissionError,
                ):
                    # Discovery must remain deterministic and must
                    # never leak filesystem exceptions.
                    continue

            entries.sort(
                key=lambda item: item["path"].casefold()
            )

            return FileResult.success_result(
                operation="file.discover",
                path=str(root),
                message=(
                    f"Discovered {len(entries)} "
                    "filesystem object(s)."
                ),
                metadata={
                    "directory": str(root),
                    "pattern": pattern,
                    "recursive": recursive,
                    "count": len(entries),
                },
                evidence={
                    "entries": entries,
                },
                safety={
                    "allowed": True,
                    "analysis_only": True,
                },
            )

        except (
            OSError,
            PermissionError,
            ValueError,
        ) as error:

            return FileResult.failure_result(
                operation="file.discover",
                status=FileStatus.ERROR,
                path=str(root),
                message=(
                    "Genesis could not complete "
                    "file discovery."
                ),
                error=str(error),
                safety={
                    "allowed": True,
                    "analysis_only": True,
                },
            )

    # =========================================================
    # TYPE RESOLUTION
    # =========================================================

    def classify_extension(
        self,
        extension: Any,
    ) -> FileResult:
        """
        Resolve a file extension through the canonical registry.
        """

        if not isinstance(
            extension,
            str,
        ):
            return FileResult.failure_result(
                operation="file.classify",
                status=FileStatus.INVALID_PATH,
                message=(
                    "File extension must be a string."
                ),
                error=(
                    "Invalid extension type."
                ),
            )

        normalized = extension.strip().lower()

        if not normalized:
            return FileResult.failure_result(
                operation="file.classify",
                status=FileStatus.INVALID_PATH,
                message=(
                    "File extension cannot be empty."
                ),
            )

        definition = self.registry.resolve(
            normalized
        )

        return FileResult.success_result(
            operation="file.classify",
            message=(
                f"Extension '{normalized}' resolved "
                f"as '{definition.name}'."
            ),
            metadata={
                "extension": normalized,
                "file_type": definition.name,
                "category": definition.category,
                "description": definition.description,
            },
            capabilities=(
                definition.capabilities.to_dict()
            ),
            evidence={
                "classification_method": "registry",
            },
            safety={
                "allowed": True,
                "analysis_only": True,
            },
        )

    # =========================================================
    # SERVICE METADATA
    # =========================================================

    def _attach_service_metadata(
        self,
        result: FileResult,
    ) -> FileResult:
        """
        Preserve the existing FileResult contract while recording
        the Level 3.7 service version.
        """

        result.metadata.setdefault(
            "file_intelligence_version",
            self.VERSION,
        )

        result.evidence.setdefault(
            "service",
            "FileIntelligenceService",
        )

        result.safety.setdefault(
            "service_version",
            self.VERSION,
        )

        return result