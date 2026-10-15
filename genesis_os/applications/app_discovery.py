"""
Genesis OS — Universal Application Discovery

LEVEL 3.2.3
-----------
Universal Application Discovery

Purpose:
    Discover applications installed or available on the
    current Windows machine.

Architecture:

    ApplicationManager
            ↓
    ApplicationDiscovery
            ↓
    ┌──────────────────────────────┐
    │ Start Menu applications     │
    │ Windows application paths   │
    │ PATH executables            │
    │ URI applications            │
    └──────────────────────────────┘

IMPORTANT
---------
Discovery does NOT launch applications.

Discovery does NOT execute arbitrary commands.

Discovery only collects and normalizes application
information for the higher-level ApplicationManager.
"""

from __future__ import annotations

import os
import shutil

from pathlib import Path
from typing import Dict, List, Optional


class ApplicationDiscovery:
    """
    Universal Windows application discovery engine.

    Current discovery sources:

        1. Windows Start Menu shortcuts
        2. Current-user Start Menu
        3. All-users Start Menu
        4. PATH executables

    Future discovery sources:

        - Windows App registrations
        - Microsoft Store applications
        - AppUserModelId
        - Registry application registrations
        - Installed-program metadata
        - Portable applications
        - User-defined application locations
    """

    VERSION = "1.0"

    def __init__(self):

        self.platform = os.name

        self._cache: Dict[str, dict] = {}

    # =========================================================
    # PUBLIC DISCOVERY API
    # =========================================================

    def discover(
        self,
        refresh: bool = False
    ) -> List[dict]:
        """
        Discover available applications.

        Returns a normalized list of application records.
        """

        if (
            self._cache
            and not refresh
        ):

            return list(
                self._cache.values()
            )

        applications: Dict[str, dict] = {}

        # -----------------------------------------------------
        # WINDOWS START MENU
        # -----------------------------------------------------

        if os.name == "nt":

            self._discover_start_menu(
                applications
            )

        # -----------------------------------------------------
        # PATH EXECUTABLES
        # -----------------------------------------------------

        self._discover_path_executables(
            applications
        )

        # -----------------------------------------------------
        # CACHE
        # -----------------------------------------------------

        self._cache = applications

        return list(
            applications.values()
        )

    # =========================================================
    # START MENU DISCOVERY
    # =========================================================

    def _discover_start_menu(
        self,
        applications: Dict[str, dict]
    ) -> None:
        """
        Discover applications from Windows Start Menu.

        We inspect both:

            Current user
            All users
        """

        locations = (
            self._start_menu_locations()
        )

        for location in locations:

            if not location.exists():

                continue

            try:

                for item in location.rglob("*"):

                    if not item.is_file():

                        continue

                    # -------------------------------------------------
                    # Shortcuts
                    # -------------------------------------------------

                    if item.suffix.lower() == ".lnk":

                        self._add_shortcut(
                            applications,
                            item
                        )

                    # -------------------------------------------------
                    # Direct executables
                    # -------------------------------------------------

                    elif item.suffix.lower() == ".exe":

                        self._add_executable(
                            applications,
                            item,
                            source="start_menu"
                        )

            except (
                PermissionError,
                OSError
            ):

                # One inaccessible directory must not
                # terminate the entire discovery process.

                continue

    # =========================================================
    # START MENU LOCATIONS
    # =========================================================

    def _start_menu_locations(
        self
    ) -> List[Path]:
        """
        Return Windows Start Menu application locations.
        """

        locations = []

        app_data = os.environ.get(
            "APPDATA"
        )

        program_data = os.environ.get(
            "PROGRAMDATA"
        )

        if app_data:

            locations.append(
                Path(app_data)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
            )

        if program_data:

            locations.append(
                Path(program_data)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
            )

        return locations

    # =========================================================
    # SHORTCUT DISCOVERY
    # =========================================================

    def _add_shortcut(
        self,
        applications: Dict[str, dict],
        shortcut: Path
    ) -> None:
        """
        Add a Windows .lnk shortcut.

        IMPORTANT:

        We do not attempt to execute the shortcut.

        At this stage we register the shortcut itself
        as a launch target.

        Later versions can resolve shortcut metadata
        through Windows Shell APIs.
        """

        name = shortcut.stem.strip()

        if not name:

            return

        key = self._make_key(
            name
        )

        if key in applications:

            return

        applications[key] = {
            "name": name,
            "normalized_name": key,
            "type": "shortcut",
            "source": "start_menu",
            "path": str(shortcut),
            "launch_target": str(shortcut),
            "executable": None,
            "uri": None,
            "available": True,
        }

    # =========================================================
    # EXECUTABLE DISCOVERY
    # =========================================================

    def _discover_path_executables(
        self,
        applications: Dict[str, dict]
    ) -> None:
        """
        Discover executable applications available
        through the system PATH.

        We deliberately do not scan the entire disk here.
        """

        path_value = os.environ.get(
            "PATH",
            ""
        )

        if not path_value:

            return

        for directory in path_value.split(
            os.pathsep
        ):

            if not directory:

                continue

            path = Path(
                directory
            )

            if not path.exists():

                continue

            try:

                for executable in path.glob(
                    "*.exe"
                ):

                    if not executable.is_file():

                        continue

                    self._add_executable(
                        applications,
                        executable,
                        source="path"
                    )

            except (
                PermissionError,
                OSError
            ):

                continue

    # =========================================================
    # ADD EXECUTABLE
    # =========================================================

    def _add_executable(
        self,
        applications: Dict[str, dict],
        executable: Path,
        source: str
    ) -> None:
        """
        Add an executable to the discovery database.
        """

        name = executable.stem.strip()

        if not name:

            return

        key = self._make_key(
            name
        )

        # -----------------------------------------------------
        # Prefer Start Menu records over PATH-only records.
        # -----------------------------------------------------

        existing = applications.get(
            key
        )

        if existing:

            if (
                existing.get("source")
                == "start_menu"
            ):

                return

        applications[key] = {
            "name": name,
            "normalized_name": key,
            "type": "executable",
            "source": source,
            "path": str(executable),
            "launch_target": str(executable),
            "executable": str(executable),
            "uri": None,
            "available": True,
        }

    # =========================================================
    # SEARCH
    # =========================================================

    def search(
        self,
        query: str,
        refresh: bool = False
    ) -> List[dict]:
        """
        Search discovered applications.

        Examples:

            search("chrome")
            search("visual")
            search("whatsapp")
        """

        query = self._normalize(
            query
        )

        if not query:

            return []

        applications = self.discover(
            refresh=refresh
        )

        results = []

        for application in applications:

            name = (
                application
                .get(
                    "name",
                    ""
                )
                .lower()
            )

            normalized_name = (
                application
                .get(
                    "normalized_name",
                    ""
                )
                .lower()
            )

            if (
                query in name
                or query in normalized_name
            ):

                results.append(
                    application
                )

        return results

    # =========================================================
    # EXACT RESOLUTION
    # =========================================================

    def resolve(
        self,
        name: str,
        refresh: bool = False
    ) -> Optional[dict]:
        """
        Resolve an application name.

        Resolution strategy:

            1. Exact discovered name
            2. Exact normalized name
            3. PATH executable
            4. Partial match
        """

        normalized = self._normalize(
            name
        )

        if not normalized:

            return None

        applications = self.discover(
            refresh=refresh
        )

        # -----------------------------------------------------
        # EXACT
        # -----------------------------------------------------

        for application in applications:

            if (
                application
                .get(
                    "normalized_name"
                )
                == normalized
            ):

                return application

        # -----------------------------------------------------
        # PATH DIRECT RESOLUTION
        # -----------------------------------------------------

        executable = shutil.which(
            normalized
        )

        if executable:

            return {
                "name": Path(
                    executable
                ).stem,

                "normalized_name":
                    normalized,

                "type":
                    "executable",

                "source":
                    "path",

                "path":
                    executable,

                "launch_target":
                    executable,

                "executable":
                    executable,

                "uri":
                    None,

                "available":
                    True,
            }

        # -----------------------------------------------------
        # PARTIAL MATCH
        # -----------------------------------------------------

        matches = self.search(
            normalized
        )

        if len(matches) == 1:

            return matches[0]

        # -----------------------------------------------------
        # AMBIGUOUS
        # -----------------------------------------------------

        return None

    # =========================================================
    # REFRESH
    # =========================================================

    def refresh(
        self
    ) -> List[dict]:
        """
        Force a complete rediscovery.
        """

        self._cache.clear()

        return self.discover(
            refresh=True
        )

    # =========================================================
    # CACHE STATUS
    # =========================================================

    def cache_status(
        self
    ) -> dict:
        """
        Return discovery-cache information.
        """

        return {
            "version": self.VERSION,
            "cached": bool(
                self._cache
            ),
            "application_count": len(
                self._cache
            ),
            "platform": self.platform,
        }

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize(
        value: str
    ) -> str:
        """
        Normalize an application name.
        """

        if not isinstance(
            value,
            str
        ):

            return ""

        value = (
            value
            .strip()
            .lower()
        )

        if value.endswith(
            ".exe"
        ):

            value = value[
                :-4
            ]

        return " ".join(
            value.split()
        )

    # =========================================================
    # SAFE KEY
    # =========================================================

    @staticmethod
    def _make_key(
        name: str
    ) -> str:
        """
        Create a normalized application key.
        """

        return (
            ApplicationDiscovery
            ._normalize(
                name
            )
        )