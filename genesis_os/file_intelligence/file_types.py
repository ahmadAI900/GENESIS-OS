"""
Genesis OS
File Intelligence — File Type Definitions

Level 3.3.1

Defines canonical file categories and capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


class FileCategory:

    TEXT = "text"

    DOCUMENT = "document"

    SPREADSHEET = "spreadsheet"

    PRESENTATION = "presentation"

    IMAGE = "image"

    AUDIO = "audio"

    VIDEO = "video"

    ARCHIVE = "archive"

    SOURCE_CODE = "source_code"

    EXECUTABLE = "executable"

    DIRECTORY = "directory"

    BINARY = "binary"

    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FileCapabilities:
    """
    Describes what Genesis may safely do with a file type.
    """

    inspect: bool = True

    read: bool = False

    extract: bool = False

    summarize: bool = False

    preview: bool = False

    open: bool = True

    search: bool = False

    modify: bool = False

    execute: bool = False

    def to_dict(self):
        return {
            "inspect": self.inspect,
            "read": self.read,
            "extract": self.extract,
            "summarize": self.summarize,
            "preview": self.preview,
            "open": self.open,
            "search": self.search,
            "modify": self.modify,
            "execute": self.execute,
        }


@dataclass(frozen=True)
class FileTypeDefinition:
    """
    Canonical description of a recognized file type.
    """

    name: str

    category: str

    extensions: FrozenSet[str]

    capabilities: FileCapabilities

    description: str = ""


TEXT_CAPABILITIES = FileCapabilities(
    inspect=True,
    read=True,
    extract=True,
    summarize=True,
    preview=True,
    open=True,
    search=True,
    modify=False,
    execute=False,
)


DOCUMENT_CAPABILITIES = FileCapabilities(
    inspect=True,
    read=True,
    extract=True,
    summarize=True,
    preview=True,
    open=True,
    search=True,
    modify=False,
    execute=False,
)


IMAGE_CAPABILITIES = FileCapabilities(
    inspect=True,
    read=False,
    extract=False,
    summarize=False,
    preview=True,
    open=True,
    search=False,
    modify=False,
    execute=False,
)


BINARY_CAPABILITIES = FileCapabilities(
    inspect=True,
    read=False,
    extract=False,
    summarize=False,
    preview=False,
    open=True,
    search=False,
    modify=False,
    execute=False,
)


EXECUTABLE_CAPABILITIES = FileCapabilities(
    inspect=True,
    read=False,
    extract=False,
    summarize=False,
    preview=False,
    open=False,
    search=False,
    modify=False,
    execute=False,
)


UNKNOWN_CAPABILITIES = FileCapabilities(
    inspect=True,
    read=False,
    extract=False,
    summarize=False,
    preview=False,
    open=True,
    search=False,
    modify=False,
    execute=False,
)