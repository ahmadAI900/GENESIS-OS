"""
Genesis OS — Windows Registered Application Discovery

LEVEL 3.2.3B
------------

Discovers Windows applications registered with the
Windows operating-system application infrastructure.

This module is discovery-only.

It does NOT launch applications.

It does NOT execute arbitrary user-provided commands.

The results are normalized so that the higher-level
Application Registry can later combine them with:

    - Start Menu applications
    - PATH executables
    - Windows URI applications
    - Microsoft Store / packaged applications
"""

from __future__ import annotations

import json
import os
import subprocess

from typing import Dict, List, Optional


class WindowsRegisteredApplicationDiscovery:
    """
    Discover applications registered with Windows.

    Strategy:

        Primary:
            PowerShell Appx package inventory

        Secondary:
            PowerShell StartApps inventory

    The two sources are intentionally kept separate
    internally and normalized into the same application
    record format.

    Discovery failures are isolated so that one Windows
    subsystem failing does not break Genesis discovery.
    """

    VERSION = "1.0"

    def __init__(self):

        self.platform = os.name

    # =========================================================
    # PUBLIC API
    # =========================================================

    def discover(self) -> List[dict]:
        """
        Discover registered Windows applications.

        Returns:
            List[dict]
        """

        if self.platform != "nt":

            return []

        applications: Dict[str, dict] = {}

        # -----------------------------------------------------
        # PACKAGED APPLICATIONS
        # -----------------------------------------------------

        for application in self._discover_appx():

            self._merge_application(
                applications,
                application
            )

        # -----------------------------------------------------
        # WINDOWS START APP REGISTRATION
        # -----------------------------------------------------

        for application in self._discover_start_apps():

            self._merge_application(
                applications,
                application
            )

        return list(
            applications.values()
        )

    # =========================================================
    # APPX / PACKAGED APPLICATIONS
    # =========================================================

    def _discover_appx(self) -> List[dict]:
        """
        Discover installed Windows AppX packages.

        Uses PowerShell's Get-AppxPackage.

        Only metadata is collected.
        """

        script = r"""
$ErrorActionPreference = 'SilentlyContinue'

Get-AppxPackage |
    Select-Object `
        Name,
        PackageFullName,
        PackageFamilyName,
        Version,
        PublisherId,
        InstallLocation |
    ConvertTo-Json -Depth 3 -Compress
"""

        result = self._run_powershell(
            script
        )

        if result is None:

            return []

        records = self._parse_json_records(
            result
        )

        applications = []

        for record in records:

            name = self._clean(
                record.get("Name")
            )

            package_full_name = self._clean(
                record.get("PackageFullName")
            )

            package_family_name = self._clean(
                record.get("PackageFamilyName")
            )

            version = self._clean(
                record.get("Version")
            )

            publisher_id = self._clean(
                record.get("PublisherId")
            )

            install_location = self._clean(
                record.get("InstallLocation")
            )

            if not name:

                continue

            applications.append(
                {
                    "name": name,
                    "normalized_name":
                        self._normalize(name),

                    "type":
                        "packaged_application",

                    "category":
                        "windows_registered",

                    "source":
                        "appx",

                    "package_name":
                        name,

                    "package_full_name":
                        package_full_name,

                    "package_family_name":
                        package_family_name,

                    "version":
                        version,

                    "publisher_id":
                        publisher_id,

                    "install_location":
                        install_location,

                    "path":
                        install_location,

                    "launch_target":
                        None,

                    "executable":
                        None,

                    "uri":
                        None,

                    "app_id":
                        None,

                    "available":
                        True,
                }
            )

        return applications

    # =========================================================
    # WINDOWS START APPS
    # =========================================================

    def _discover_start_apps(self) -> List[dict]:
        """
        Discover applications exposed by Windows'
        StartApps provider.

        This is useful for applications that have a
        Windows application identity but are not exposed
        as ordinary PATH executables.
        """

        script = r"""
$ErrorActionPreference = 'SilentlyContinue'

Get-StartApps |
    Select-Object `
        Name,
        AppID |
    ConvertTo-Json -Depth 3 -Compress
"""

        result = self._run_powershell(
            script
        )

        if result is None:

            return []

        records = self._parse_json_records(
            result
        )

        applications = []

        for record in records:

            name = self._clean(
                record.get("Name")
            )

            app_id = self._clean(
                record.get("AppID")
            )

            if not name:

                continue

            applications.append(
                {
                    "name": name,

                    "normalized_name":
                        self._normalize(name),

                    "type":
                        "registered_application",

                    "category":
                        "windows_registered",

                    "source":
                        "start_apps",

                    "package_name":
                        None,

                    "package_full_name":
                        None,

                    "package_family_name":
                        None,

                    "version":
                        None,

                    "publisher_id":
                        None,

                    "install_location":
                        None,

                    "path":
                        None,

                    "launch_target":
                        None,

                    "executable":
                        None,

                    "uri":
                        None,

                    "app_id":
                        app_id,

                    "available":
                        True,
                }
            )

        return applications

    # =========================================================
    # POWERSHELL EXECUTION
    # =========================================================

    def _run_powershell(
        self,
        script: str
    ) -> Optional[str]:
        """
        Execute a fixed internal PowerShell discovery
        script.

        No user input is interpolated into the script.
        """

        try:

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )

        except (
            subprocess.SubprocessError,
            OSError
        ):

            return None

        if result.returncode != 0:

            return None

        output = (
            result.stdout or ""
        ).strip()

        if not output:

            return None

        return output

    # =========================================================
    # JSON PARSING
    # =========================================================

    @staticmethod
    def _parse_json_records(
        output: str
    ) -> List[dict]:
        """
        PowerShell ConvertTo-Json returns:

            object

        for one result and:

            array

        for multiple results.

        Normalize both forms into List[dict].
        """

        try:

            data = json.loads(
                output
            )

        except (
            json.JSONDecodeError,
            TypeError
        ):

            return []

        if isinstance(
            data,
            dict
        ):

            return [data]

        if isinstance(
            data,
            list
        ):

            return [
                item
                for item in data
                if isinstance(
                    item,
                    dict
                )
            ]

        return []

    # =========================================================
    # MERGE
    # =========================================================

    def _merge_application(
        self,
        applications: Dict[str, dict],
        application: dict
    ) -> None:
        """
        Merge an application into the discovery result.

        Existing records are preserved and enriched rather
        than blindly overwritten.
        """

        name = self._clean(
            application.get("name")
        )

        if not name:

            return

        key = self._normalize(
            name
        )

        if not key:

            return

        existing = applications.get(
            key
        )

        if existing is None:

            applications[key] = dict(
                application
            )

            return

        # -----------------------------------------------------
        # Enrich existing record.
        # -----------------------------------------------------

        for field, value in application.items():

            if (
                value is not None
                and value != ""
            ):

                if (
                    existing.get(field)
                    in (
                        None,
                        "",
                    )
                ):

                    existing[field] = value

    # =========================================================
    # STRING CLEANING
    # =========================================================

    @staticmethod
    def _clean(
        value
    ) -> str:
        """
        Safely convert a value into a clean string.
        """

        if value is None:

            return ""

        return str(
            value
        ).strip()

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize(
        value: str
    ) -> str:
        """
        Normalize application names for matching.
        """

        if not isinstance(
            value,
            str
        ):

            return ""

        return " ".join(
            value
            .strip()
            .lower()
            .split()
        )