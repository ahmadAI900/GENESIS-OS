"""
Genesis OS
File Intelligence — File Type Registry

Level 3.3.1

Central registry for file-type classification and capabilities.
"""

from __future__ import annotations

from typing import Dict, Optional

from .file_types import (
    BINARY_CAPABILITIES,
    DOCUMENT_CAPABILITIES,
    EXECUTABLE_CAPABILITIES,
    IMAGE_CAPABILITIES,
    TEXT_CAPABILITIES,
    UNKNOWN_CAPABILITIES,
    FileCategory,
    FileCapabilities,
    FileTypeDefinition,
)


class FileTypeRegistry:

    VERSION = "3.3.1"

    def __init__(self):

        self._definitions: Dict[
            str,
            FileTypeDefinition
        ] = {}

        self._register_defaults()

    # =====================================================
    # REGISTRATION
    # =====================================================

    def register(
        self,
        definition: FileTypeDefinition,
    ) -> None:

        if not isinstance(
            definition,
            FileTypeDefinition,
        ):
            raise TypeError(
                "definition must be FileTypeDefinition"
            )

        self._definitions[
            definition.name
        ] = definition

    # =====================================================
    # DEFAULT TYPES
    # =====================================================

    def _register_defaults(self):

        self.register(
            FileTypeDefinition(
                name="text",
                category=FileCategory.TEXT,
                extensions=frozenset({
                    ".txt",
                    ".log",
                    ".csv",
                    ".json",
                    ".xml",
                    ".yaml",
                    ".yml",
                    ".ini",
                    ".cfg",
                }),
                capabilities=TEXT_CAPABILITIES,
                description="Plain or structured text.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="python",
                category=FileCategory.SOURCE_CODE,
                extensions=frozenset({
                    ".py",
                    ".pyw",
                }),
                capabilities=TEXT_CAPABILITIES,
                description="Python source code.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="javascript",
                category=FileCategory.SOURCE_CODE,
                extensions=frozenset({
                    ".js",
                    ".jsx",
                    ".mjs",
                    ".cjs",
                }),
                capabilities=TEXT_CAPABILITIES,
                description="JavaScript source code.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="typescript",
                category=FileCategory.SOURCE_CODE,
                extensions=frozenset({
                    ".ts",
                    ".tsx",
                }),
                capabilities=TEXT_CAPABILITIES,
                description="TypeScript source code.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="pdf",
                category=FileCategory.DOCUMENT,
                extensions=frozenset({
                    ".pdf",
                }),
                capabilities=DOCUMENT_CAPABILITIES,
                description="Portable Document Format.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="word",
                category=FileCategory.DOCUMENT,
                extensions=frozenset({
                    ".doc",
                    ".docx",
                }),
                capabilities=DOCUMENT_CAPABILITIES,
                description="Microsoft Word document.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="spreadsheet",
                category=FileCategory.SPREADSHEET,
                extensions=frozenset({
                    ".xls",
                    ".xlsx",
                    ".xlsm",
                    ".csv",
                }),
                capabilities=DOCUMENT_CAPABILITIES,
                description="Spreadsheet or tabular document.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="presentation",
                category=FileCategory.PRESENTATION,
                extensions=frozenset({
                    ".ppt",
                    ".pptx",
                }),
                capabilities=DOCUMENT_CAPABILITIES,
                description="Presentation document.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="image",
                category=FileCategory.IMAGE,
                extensions=frozenset({
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".gif",
                    ".bmp",
                    ".webp",
                    ".svg",
                    ".ico",
                }),
                capabilities=IMAGE_CAPABILITIES,
                description="Image file.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="archive",
                category=FileCategory.ARCHIVE,
                extensions=frozenset({
                    ".zip",
                    ".7z",
                    ".rar",
                    ".tar",
                    ".gz",
                }),
                capabilities=BINARY_CAPABILITIES,
                description="Archive container.",
            )
        )

        self.register(
            FileTypeDefinition(
                name="executable",
                category=FileCategory.EXECUTABLE,
                extensions=frozenset({
                    ".exe",
                    ".com",
                    ".bat",
                    ".cmd",
                    ".msi",
                    ".ps1",
                }),
                capabilities=EXECUTABLE_CAPABILITIES,
                description="Executable or command file.",
            )
        )

    # =====================================================
    # RESOLUTION
    # =====================================================

    def resolve(
        self,
        extension: Optional[str],
    ) -> FileTypeDefinition:

        if not extension:

            return FileTypeDefinition(
                name="unknown",
                category=FileCategory.UNKNOWN,
                extensions=frozenset(),
                capabilities=UNKNOWN_CAPABILITIES,
                description="Unknown file type.",
            )

        normalized = extension.lower()

        if not normalized.startswith("."):
            normalized = "." + normalized

        # Some extensions are intentionally shared by multiple semantic
        # types (CSV is both text and tabular data).  Prefer the more
        # specific semantic type so the rest of Genesis can make better
        # decisions without creating a second classifier.
        priority = (
            "spreadsheet",
            "word",
            "pdf",
            "presentation",
            "image",
            "archive",
            "executable",
            "python",
            "javascript",
            "typescript",
            "text",
        )

        for name in priority:
            definition = self._definitions.get(name)
            if definition and normalized in definition.extensions:
                return definition

        for definition in self._definitions.values():
            if normalized in definition.extensions:
                return definition

        return FileTypeDefinition(
            name="unknown",
            category=FileCategory.UNKNOWN,
            extensions=frozenset(),
            capabilities=UNKNOWN_CAPABILITIES,
            description="Unknown file type.",
        )

    # =====================================================
    # LOOKUP
    # =====================================================

    def get(
        self,
        name: str,
    ) -> Optional[FileTypeDefinition]:

        return self._definitions.get(
            name
        )

    def all_types(self):

        return tuple(
            self._definitions.values()
        )