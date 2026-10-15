"""
Genesis OS
File Intelligence — File Inspector

Level 3.3.1

Provides safe filesystem inspection.

Inspection NEVER launches, modifies, deletes, or executes
anything.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .file_identity import (
    FileIdentityBuilder,
)
from .file_registry import (
    FileTypeRegistry,
)
from .file_result import (
    FileResult,
    FileStatus,
)
from .path_security import (
    PathSecurity,
)


class FileInspector:

    VERSION = "3.3.1"

    def __init__(
        self,
        registry: Optional[
            FileTypeRegistry
        ] = None,
    ):

        self.registry = (
            registry
            or FileTypeRegistry()
        )

    # =====================================================
    # INSPECT
    # =====================================================

    def inspect(
        self,
        path: Any,
    ) -> FileResult:
        """
        Inspect a filesystem object.

        This operation is analysis-only.

        It never opens an application and never modifies
        the filesystem.
        """

        validation = PathSecurity.validate(
            path,
            require_existing=True,
        )

        if not validation.get(
            "allowed"
        ):

            status = validation.get(
                "status",
                FileStatus.INVALID_PATH,
            )

            return FileResult.failure_result(
                operation="file.inspect",
                status=status,
                path=validation.get(
                    "path"
                ),
                message=validation.get(
                    "reason",
                    "File inspection was rejected.",
                ),
                error=validation.get(
                    "reason"
                ),
                safety={
                    "allowed": False,
                    "validation": validation,
                },
            )

        normalized_path = validation[
            "path"
        ]

        identity = FileIdentityBuilder.build(
            normalized_path
        )

        if identity is None:

            return FileResult.failure_result(
                operation="file.inspect",
                status=FileStatus.INVALID_PATH,
                path=normalized_path,
                message=(
                    "Genesis could not construct a "
                    "safe file identity."
                ),
                safety={
                    "allowed": False,
                },
            )

        if not identity.exists:

            return FileResult.failure_result(
                operation="file.inspect",
                status=FileStatus.NOT_FOUND,
                path=identity.absolute_path,
                message=(
                    "The requested filesystem object "
                    "does not exist."
                ),
                identity=identity.to_dict(),
                safety={
                    "allowed": True,
                },
            )

        # -------------------------------------------------
        # DIRECTORY
        # -------------------------------------------------

        if identity.is_directory:

            capabilities = {
                "inspect": True,
                "read": False,
                "extract": False,
                "summarize": False,
                "preview": False,
                "open": True,
                "search": True,
                "modify": False,
                "execute": False,
            }

            return FileResult.success_result(
                operation="file.inspect",
                path=identity.absolute_path,
                message=(
                    f"Genesis identified "
                    f"'{identity.name}' as a directory."
                ),
                identity=identity.to_dict(),
                metadata={
                    "object_type": "directory",
                    "size": identity.size,
                },
                capabilities=capabilities,
                safety={
                    "allowed": True,
                    "analysis_only": True,
                },
            )

        # -------------------------------------------------
        # FILE
        # -------------------------------------------------

        definition = self.registry.resolve(
            identity.extension
        )

        capabilities = (
            definition.capabilities.to_dict()
        )

        metadata = {
            "file_type": definition.name,
            "category": definition.category,
            "description": definition.description,
            "size": identity.size,
            "extension": identity.extension,
            "name": identity.name,
        }

        return FileResult.success_result(
            operation="file.inspect",
            path=identity.absolute_path,
            message=(
                f"Genesis identified "
                f"'{identity.name}' as "
                f"{definition.name}."
            ),
            identity=identity.to_dict(),
            metadata=metadata,
            capabilities=capabilities,
            evidence={
                "classification": {
                    "method": "extension",
                    "extension": identity.extension,
                }
            },
            safety={
                "allowed": True,
                "analysis_only": True,
                "execution_allowed": (
                    capabilities.get(
                        "execute",
                        False,
                    )
                ),
            },
        )

    # =====================================================
    # EXISTS
    # =====================================================

    def exists(
        self,
        path: Any,
    ) -> FileResult:

        validation = PathSecurity.validate(
            path
        )

        if not validation.get(
            "allowed"
        ):

            return FileResult.failure_result(
                operation="file.exists",
                status=validation.get(
                    "status",
                    FileStatus.INVALID_PATH,
                ),
                path=validation.get(
                    "path"
                ),
                message=validation.get(
                    "reason",
                    "Invalid path.",
                ),
            )

        exists = bool(
            validation.get(
                "exists"
            )
        )

        if exists:

            return FileResult.success_result(
                operation="file.exists",
                path=validation["path"],
                message="The filesystem object exists.",
                metadata={
                    "exists": True,
                },
            )

        return FileResult.failure_result(
            operation="file.exists",
            status=FileStatus.NOT_FOUND,
            path=validation["path"],
            message=(
                "The requested filesystem object "
                "does not exist."
            ),
            metadata={
                "exists": False,
            },
        )