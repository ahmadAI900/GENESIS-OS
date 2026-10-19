"""
Genesis OS â€” Application Manager

LEVEL 3.2
---------
Application Intelligence

Responsibilities:
    - Resolve user-facing application names.
    - Resolve common Windows applications.
    - Support Windows URI applications.
    - Discover executables through PATH.
    - Discover common Windows installation paths.
    - Detect whether an application is running.
    - Launch applications safely.
    - Close applications safely.
    - Inspect application state.
    - Support aliases and natural application names.

Architecture:

    WorkflowDecisionEngine
            â†“
    GenesisOS.run_level3()
            â†“
    OSManager
            â†“
    ApplicationManager
            â†“
    Windows

SECURITY PRINCIPLE
------------------
This module does NOT execute arbitrary shell commands.

Applications are launched only through:
    1. validated executable paths
    2. validated Windows URI schemes

The user's text is NEVER passed directly to cmd.exe,
PowerShell, os.system(), or shell=True.
"""

from __future__ import annotations
from genesis_os.applications.unified_discovery import (
    UnifiedApplicationDiscovery,
)

from genesis_os.applications.application_resolution import (
    ApplicationResolutionEngine,
    ResolutionDecision,
)

import os
import shutil
import subprocess
import time

from pathlib import Path
from typing import Optional, Dict, List


class ApplicationManager:
    """
    Controlled Windows application management layer.

    Resolution priority:

        1. Built-in Windows URI applications
        2. Known application aliases
        3. PATH executables
        4. Known Windows installation paths
        5. Safe executable-name fallback

    The manager never executes arbitrary shell strings.
    """

    VERSION = "2.0"

    # =========================================================
    # INITIALIZATION
    # =========================================================

    def __init__(self):

        self.platform = os.name

        # Item 16B (C16): why the last process-table query failed, when
        # it did. Set by running_state(); read by callers that receive
        # STATE_UNKNOWN, so "we could not tell" can say why.
        self._last_process_query_error: Optional[str] = None

        # -----------------------------------------------------
# UNIFIED APPLICATION INTELLIGENCE
# -----------------------------------------------------

        self.discovery = UnifiedApplicationDiscovery()

        self.resolution_engine = (
            ApplicationResolutionEngine(
                discovery=self.discovery
            )
        )

        # -----------------------------------------------------
        # ALIAS â†’ EXECUTABLE
        # -----------------------------------------------------

        self.application_aliases = {

            # =================================================
            # BROWSERS
            # =================================================

            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "chrome browser": "chrome.exe",

            "edge": "msedge.exe",
            "microsoft edge": "msedge.exe",
            "edge browser": "msedge.exe",

            "firefox": "firefox.exe",
            "mozilla firefox": "firefox.exe",
            "firefox browser": "firefox.exe",

            "opera": "opera.exe",
            "opera browser": "opera.exe",

            "brave": "brave.exe",
            "brave browser": "brave.exe",

            # =================================================
            # MICROSOFT DEVELOPMENT
            # =================================================

            "vscode": "code.exe",
            "vs code": "code.exe",
            "visual studio code": "code.exe",
            "visual studio code editor": "code.exe",

            "visual studio": "devenv.exe",
            "vs": "devenv.exe",

            # =================================================
            # WINDOWS BASIC APPS
            # =================================================

            "notepad": "notepad.exe",
            "windows notepad": "notepad.exe",

            "paint": "mspaint.exe",
            "ms paint": "mspaint.exe",
            "microsoft paint": "mspaint.exe",

            "calculator": "calc.exe",
            "calc": "calc.exe",
            "windows calculator": "calc.exe",

            "snipping tool": "SnippingTool.exe",
            "snip tool": "SnippingTool.exe",

            "wordpad": "wordpad.exe",

            # =================================================
            # FILE MANAGEMENT
            # =================================================

            "explorer": "explorer.exe",
            "file explorer": "explorer.exe",
            "windows explorer": "explorer.exe",

            # =================================================
            # TERMINALS
            # =================================================

            "command prompt": "cmd.exe",
            "cmd": "cmd.exe",
            "cmd prompt": "cmd.exe",

            "powershell": "powershell.exe",
            "power shell": "powershell.exe",
            "windows powershell": "powershell.exe",

            "terminal": "wt.exe",
            "windows terminal": "wt.exe",

            # =================================================
            # TASK / SYSTEM UTILITIES
            # =================================================

            "task manager": "taskmgr.exe",
            "taskmgr": "taskmgr.exe",

            "control panel": "control.exe",
            "control": "control.exe",

            "registry editor": "regedit.exe",
            "regedit": "regedit.exe",

            "resource monitor": "resmon.exe",
            "resource monitor app": "resmon.exe",

            "system configuration": "msconfig.exe",
            "msconfig": "msconfig.exe",

            "services": "services.msc",

            # =================================================
            # MICROSOFT OFFICE
            # =================================================

            "word": "WINWORD.EXE",
            "microsoft word": "WINWORD.EXE",

            "excel": "EXCEL.EXE",
            "microsoft excel": "EXCEL.EXE",

            "powerpoint": "POWERPNT.EXE",
            "microsoft powerpoint": "POWERPNT.EXE",

            "outlook": "OUTLOOK.EXE",
            "microsoft outlook": "OUTLOOK.EXE",

            "onenote": "ONENOTE.EXE",
            "microsoft onenote": "ONENOTE.EXE",

            # =================================================
            # COMMON DEVELOPMENT TOOLS
            # =================================================

            "pycharm": "pycharm64.exe",
            "pycharm community": "pycharm64.exe",

            "android studio": "studio64.exe",

            # =================================================
            # MEDIA / COMMUNICATION
            # =================================================

            "discord": "Discord.exe",

            "spotify": "Spotify.exe",

            "vlc": "vlc.exe",
            "vlc media player": "vlc.exe",

            # =================================================
            # ARCHIVERS
            # =================================================

            "7zip": "7zFM.exe",
            "7 zip": "7zFM.exe",

            "winrar": "WinRAR.exe",

            # =================================================
            # PDF
            # =================================================

            "adobe reader": "AcroRd32.exe",
            "adobe acrobat reader": "AcroRd32.exe",
            "acrobat reader": "AcroRd32.exe",
        }

        # -----------------------------------------------------
        # WINDOWS URI APPLICATIONS
        # -----------------------------------------------------
        #
        # These are NOT executable paths.
        #
        # They are Windows URI schemes.
        #
        # This is especially important for modern Windows
        # applications such as Settings.
        #

        self.windows_uri_apps = {

            # =================================================
            # WINDOWS SETTINGS
            # =================================================

            "settings":
                "ms-settings:",

            "windows settings":
                "ms-settings:",

            "system settings":
                "ms-settings:",

            "pc settings":
                "ms-settings:",

            # =================================================
            # SETTINGS SUB-PAGES
            # =================================================

            "display settings":
                "ms-settings:display",

            "sound settings":
                "ms-settings:sound",

            "network settings":
                "ms-settings:network",

            "wifi settings":
                "ms-settings:network-wifi",

            "bluetooth settings":
                "ms-settings:bluetooth",

            "personalization settings":
                "ms-settings:personalization",

            "apps settings":
                "ms-settings:appsfeatures",

            "installed apps":
                "ms-settings:appsfeatures",

            "windows update":
                "ms-settings:windowsupdate",

            "update settings":
                "ms-settings:windowsupdate",

            "privacy settings":
                "ms-settings:privacy",

            "accounts settings":
                "ms-settings:accounts",

            "time settings":
                "ms-settings:dateandtime",

            "language settings":
                "ms-settings:regionlanguage",

            "accessibility settings":
                "ms-settings:easeofaccess",

            # =================================================
            # WINDOWS SECURITY
            # =================================================

            "windows security":
                "windowsdefender:",

            "windows defender":
                "windowsdefender:",

            # =================================================
            # XBOX
            # =================================================

            "xbox":
                "xbox:",

            "xbox app":
                "xbox:",

            # =================================================
            # MICROSOFT STORE
            # =================================================

            "microsoft store":
                "ms-windows-store:",

            "windows store":
                "ms-windows-store:",

            "store":
                "ms-windows-store:",
            "display_settings":
                "ms-settings:display",

            "sound_settings":
                "ms-settings:sound",

            "network_settings":
                "ms-settings:network",

            "wifi_settings":
                 "ms-settings:network-wifi",

            "bluetooth_settings":
                "ms-settings:bluetooth",

            "personalization_settings":
                "ms-settings:personalization",

            "apps_settings":
                "ms-settings:appsfeatures",

            "windows_update":
                "ms-settings:windowsupdate",

            "privacy_settings":
                "ms-settings:privacy",

            "accounts_settings":
                "ms-settings:accounts",

            "time_settings":
                "ms-settings:dateandtime",

            "language_settings":
                "ms-settings:regionlanguage",

            "accessibility_settings":
                "ms-settings:easeofaccess",

            "windows_security":
                "windowsdefender:",

            "microsoft_store":
                "ms-windows-store:",

            "xbox":
                "xbox:",
            }

        # -----------------------------------------------------
        # KNOWN WINDOWS PATHS
        # -----------------------------------------------------

        self.application_paths = (
            self._build_known_paths()
        )

    # =========================================================
    # PUBLIC API
    # =========================================================

    def inspect(
        self,
        application: str
    ) -> dict:
        """
        Inspect an application without modifying the system.
        """
        resolution = self.resolve_application_record(application)

        target = (resolution.get("name") if resolution else None) or self._normalize_name(application)

        if not target:
            return self._error(
                "No application name was provided."
            )

        # -----------------------------------------------------
        # URI APPLICATION
        # -----------------------------------------------------

        uri = self.resolve_uri(
            target
        )

        if uri:

            return {
                "success": True,
                "operation": "application.inspect",
                "application": target,
                "resolved_uri": uri,
                "resolved_executable": None,
                "running": None,
                "available": True,
                "application_type": "windows_uri",
                "verified": False,
                "verification_type": "uri_identity_only",
                "verification_reason": "URI identity was resolved, but its handler was not independently observed.",
                "message": (
                    f"{target} is a Windows application "
                    f"interface."
                ),
            }

        # -----------------------------------------------------
        # EXECUTABLE APPLICATION
        # -----------------------------------------------------

        executable = (
            self.resolve_application(
                target
            )
        )

        if executable is None:

            return {
                "success": False,
                "operation": "application.inspect",
                "application": target,
                "resolved_executable": None,
                "running": False,
                "available": False,
                "message": (
                    f"Could not resolve application "
                    f"'{target}'."
                ),
            }

        # On non-Windows hosts the process-table query is not
        # implemented; ``is_running`` returns False without
        # actually inspecting anything. Be honest: do not
        # claim ``verified=True`` for a value we did not
        # actually observe.
        if os.name != "nt":
            return {
                "success": True,
                "operation": "application.inspect",
                "application": target,
                "resolved_executable": executable,
                "resolved_uri": None,
                "running": None,
                "available": None,
                "application_type": "executable",
                "platform_unsupported": True,
                "platform_reason": (
                    "Process-table inspection is only "
                    "implemented on Windows."
                ),
                "verified": False,
                "verification_type": "platform_unsupported",
                "message": (
                    f"{target} resolves to "
                    f"{executable}, but process state "
                    f"cannot be inspected on this host."
                ),
            }

        running = self.is_running(
            executable
        )

        return {
            "success": True,
            "operation": "application.inspect",
            "application": target,
            "resolved_executable": executable,
            "resolved_uri": None,
            "running": running,
            "available": True,
            "application_type": "executable",
            # The inspection itself IS the verification of the
            # application state: the process table was actually
            # consulted and the answer is evidence-backed.
            "verified": True,
            "verification_type": (
                "process_table_inspection"
            ),
            "verification_method": "tasklist",
            "message": (
                f"{target} is "
                f"{'running' if running else 'not running'}."
            ),
        }

    # =========================================================
    # OPEN APPLICATION
    # =========================================================

    def open(
        self,
        application: str,
        file_path: Optional[str] = None,
    ) -> dict:
        """
        Launch a validated application.
        """

        target = self._normalize_name(
            application
        )

        if not target:

            return self._error(
                "No application name was provided."
            )

        file_argument = None
        if file_path:
            file_argument = Path(str(file_path)).expanduser()
            if not file_argument.is_absolute():
                file_argument = Path.cwd() / file_argument
            if not file_argument.is_file():
                return {
                    "success": False,
                    "operation": "application.open",
                    "application": target,
                    "error": "The requested file does not exist.",
                    "verified": False,
                }
            file_argument = str(file_argument)

        # -----------------------------------------------------
        # EXECUTABLE (preferred; the URI path below is fallback)
        # -----------------------------------------------------

        executable = (
            self.resolve_application(
                target
            )
        )

        if executable is None:
            # -------------------------------------------------
            # WINDOWS URI APPLICATION -- LAST RESORT (Item 14D)
            # -------------------------------------------------
            #
            # This block used to sit at the TOP of `open()`, so any
            # name present in the URI alias table went to
            # explorer.exe before the executable resolver was ever
            # consulted. A direct executable launch is the mechanism
            # that can be VERIFIED (this manager polls tasklist for the
            # process and reports `verified=True`); the URI path can
            # only ever report `dispatched` with `verified=False`. So
            # preferring the URI route threw away the stronger,
            # observable guarantee for every name that had both.
            #
            # It is now reached only when no executable could be
            # resolved, which is what "last resort" has to mean if it
            # is to mean anything.
            uri = self.resolve_uri(
                target
            )

            if uri:
                if file_argument:
                    return {
                        "success": False,
                        "operation": "application.open",
                        "application": target,
                        "resolved_uri": uri,
                        "error": "File arguments are not supported for URI applications.",
                        "verified": False,
                    }

                return self._open_uri(
                    target,
                    uri
                )

            return {
                "success": False,
                "operation": "application.open",
                "application": target,
                "resolved_executable": None,
                "available": False,
                "verified": False,
                "verification_type": "application_unavailable",
                "message": (
                    f"Application '{target}' "
                    f"could not be found."
                ),
            }

        # -----------------------------------------------------
        # ALREADY RUNNING
        # -----------------------------------------------------

        if self.is_running(
            executable
        ):

            if file_argument:
                try:
                    self._launch(
                        executable,
                        file_argument
                    )
                except Exception as error:
                    return {
                        "success": False,
                        "operation": "application.open",
                        "application": target,
                        "resolved_executable": executable,
                        "already_running": True,
                        "error": str(error),
                        "message": f"Failed to open {file_argument} in {target}.",
                        "verified": False,
                    }

            result = {
                "success": True,
                "operation": "application.open",
                "application": target,
                "resolved_executable": executable,
                "already_running": True,
                "application_type": "executable",
                "running": True,
                "verified": True,
                "verification_type": "process_table_inspection",
                "verification_method": "tasklist",
                "message": (
                    f"{target} is already running."
                ),
            }
            if file_argument:
                result["opened_file"] = file_argument
                result["file_argument"] = file_argument
            return result

        # -----------------------------------------------------
        # LAUNCH
        # -----------------------------------------------------

        try:

            self._launch(
                executable,
                file_argument
            )

        except Exception as error:

            return {
                "success": False,
                "operation": "application.open",
                "application": target,
                "resolved_executable": executable,
                "already_running": False,
                "error": str(error),
                "message": (
                    f"Failed to launch {target}."
                ),
            }

        # -----------------------------------------------------
        # POST-ACTION VERIFICATION
        # -----------------------------------------------------

        # Item 16B (C16): tri-state. `is_running` now returns None for
        # UNKNOWN, and `success: None` in a result dict is neither True
        # nor False -- so the boolean is derived explicitly and the
        # state is carried alongside it rather than being flattened away.
        state = self.running_state(
            executable,
            attempts=5
        )

        running = state == self.STATE_RUNNING

        result = {
            "success": running,
            "operation": "application.open",
            "application": target,
            "resolved_executable": executable,
            "already_running": False,
            "running": running,
            "process_state": state,
            "verified": running,
            "verification_type": (
                "process_state_unknown"
                if state == self.STATE_UNKNOWN
                else "process_table_inspection"
            ),
            "verification_method": "tasklist",
            "application_type": "executable",
            "message": (
                f"{target} opened successfully."
                if running
                else (
                    f"{target} launch was requested "
                    f"but could not be verified."
                )
            ),
        }
        if file_argument:
            result["opened_file"] = file_argument
            result["file_argument"] = file_argument
        return result

    # =========================================================
    # OPEN WINDOWS URI
    # =========================================================

    def _open_uri(
        self,
        application: str,
        uri: str
    ) -> dict:
        """
    Open a validated Windows URI application.

    Uses the same mechanism that works directly
    from the Windows terminal:

        explorer.exe ms-settings:
        """

        if os.name != "nt":

            return {
                "success": False,
                "operation": "application.open",
                "application": application,
                "resolved_uri": uri,
                "message": (
                    "Windows URI applications are supported "
                    "only on Windows."
                ),
            }

        # DEFENCE IN DEPTH (Item 14D). `open()` only ever passes the
        # pair it got from `resolve_uri(target)`, so this re-check is
        # redundant on the current call path -- and it is here
        # precisely because that is a fact about the CALLER, not a
        # fact about this method. `_open_uri` hands its argument to
        # `explorer.exe`, which dispatches whatever URI scheme it is
        # given.
        #
        # The check is deliberately the STRICTER of the two available
        # forms: not merely "this URI is somewhere in the table" but
        # "this URI is the one registered FOR THIS APPLICATION". A
        # value-only check would still accept
        # _open_uri("settings", "ms-settings:display") -- a URI from
        # the allowlist, but bound to a different alias.
        if uri != self.resolve_uri(application):
            return {
                "success": False,
                "operation": "application.open",
                "application": application,
                "resolved_uri": uri,
                "error": "Refused: the URI is not the one registered for this application.",
                "verified": False,
            }

        try:
            # The URI comes from Genesis' internal
            # allowlisted URI registry (see the check above).
            subprocess.Popen(
                [
                    "explorer.exe",
                    uri
                ],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )

        except Exception as error:

            return {
                "success": False,
                "operation": "application.open",
                "application": application,
                "resolved_uri": uri,
                "error": str(error),
                "message": (
                    f"Failed to open {application}."
                ),
            }

        # Dispatch was accepted by Windows. The visible UI was
        # NOT independently inspected; an asynchronous Settings
        # page or URI handler may have refused the request or
        # never show a window. Be honest: only ``dispatched``
        # was observed. ``verified`` remains False so the
        # executor does not claim trustworthy success.
        return {
            "success": True,
            "operation": "application.open",
            "application": application,
            "resolved_uri": uri,
            "application_type": "windows_uri",
            "executed": True,
            # Windows accepted the launch request (dispatch confirmed).
            # This does NOT mean the visible UI was independently
            # inspected; UI verification requires polling for the
            # target process/window which the URI dispatch path does
            # not perform. ``verified`` is therefore left False so the
            # executor's post-state observation is the sole source of
            # truth for ``application_running=True``.
            "verified": False,
            "verification_type": "dispatch_confirmed_not_inspected",
            "dispatched": True,
            "message": (
                f"{application} launch request dispatched "
                f"to Windows; UI state not independently "
                f"verified."
            ),
        }

    def close(
        self,
        application: str
    ) -> dict:
        """
        Close a resolved executable application.

        Windows URI applications generally do not expose
        a universal executable process that can safely be
        terminated through this resolver.

        Therefore URI applications are handled conservatively.
        """

        target = self._normalize_name(
            application
        )

        if not target:

            return self._error(
                "No application name was provided."
            )

        # -----------------------------------------------------
        # URI APPLICATION
        # -----------------------------------------------------

        uri = self.resolve_uri(
            target
        )

        if uri:

            return {
                "success": False,
                "operation": "application.close",
                "application": target,
                "resolved_uri": uri,
                "message": (
                    f"'{target}' is a Windows URI application. "
                    "Genesis cannot safely close it through "
                    "the current application process manager."
                ),
            }

        # -----------------------------------------------------
        # EXECUTABLE
        # -----------------------------------------------------

        executable = (
            self.resolve_application(
                target
            )
        )

        if executable is None:

            return {
                "success": False,
                "operation": "application.close",
                "application": target,
                "message": (
                    f"Application '{target}' "
                    f"could not be resolved."
                ),
            }

        # -----------------------------------------------------
        # ALREADY CLOSED
        # -----------------------------------------------------
        #
        # Item 16B (C16): three outcomes, not two.
        #
        # The old code branched on a bare bool:
        #
        #     if not self.is_running(executable):
        #
        # and `is_running` reported False both when the process table
        # confirmed absence AND when the process table could not be
        # consulted at all -- so a broken tasklist produced:
        #
        #     success=True, already_closed=True, running=False,
        #     verified=True,
        #     verification_type="process_table_inspection"
        #
        # A verified claim about an inspection that never ran.
        #
        # `is_running` now returns None for UNKNOWN, so the check is on
        # the tri-state rather than on truthiness. Reading None as
        # "not False" is the entire fix.
        observed = self.is_running(
            executable
        )

        state = (
            self.STATE_RUNNING
            if observed is True
            else self.STATE_UNKNOWN
            if observed is None
            else self.STATE_NOT_RUNNING
        )

        if state == self.STATE_UNKNOWN:

            # Fail closed. We do not know whether the application is
            # running, so we cannot certify that it is closed.
            return {
                "success": False,
                "operation": "application.close",
                "application": target,
                "resolved_executable": executable,
                # None, not False: the state was not determined. A
                # consumer reading `already_closed` gets something
                # falsy, and a consumer reading it strictly gets an
                # explicit "unknown" rather than a fabricated "no".
                "already_closed": None,
                "running": None,
                "process_state": self.STATE_UNKNOWN,
                "verified": False,
                "verification_type": "process_state_unknown",
                "error": (
                    self._last_process_query_error
                    or "The process table could not be queried."
                ),
                "message": (
                    f"Genesis could not determine whether "
                    f"{target} is running, so closure was not "
                    f"certified. The application may still be open."
                ),
            }

        if state == self.STATE_NOT_RUNNING:

            return {
                "success": True,
                "operation": "application.close",
                "application": target,
                "resolved_executable": executable,
                "already_closed": True,
                "running": False,
                "process_state": self.STATE_NOT_RUNNING,
                "verified": True,
                "verification_type": "process_table_inspection",
                "verification_method": "tasklist",
                "message": (
                    f"{target} is not running."
                ),
            }

        # -----------------------------------------------------
        # WINDOWS ONLY
        # -----------------------------------------------------

        if os.name != "nt":

            return {
                "success": False,
                "operation": "application.close",
                "application": target,
                "message": (
                    "Application closing is currently "
                    "implemented for Windows."
                ),
            }

        executable_name = Path(
            executable
        ).name

        # -----------------------------------------------------
        # SAFETY CHECK
        # -----------------------------------------------------

        if not executable_name:

            return {
                "success": False,
                "operation": "application.close",
                "application": target,
                "message": (
                    "Genesis could not determine the "
                    "application process name."
                ),
            }

        try:

            completed = subprocess.run(
                [
                    "taskkill",
                    "/IM",
                    executable_name,
                    "/T",
                    "/F",
                ],
                capture_output=True,
                text=True,
                shell=False,
                timeout=10,
            )

        except Exception as error:

            return {
                "success": False,
                "operation": "application.close",
                "application": target,
                "resolved_executable": executable,
                "error": str(error),
                "message": (
                    f"Failed to close {target}."
                ),
            }

        # -----------------------------------------------------
        # POST-ACTION VERIFICATION
        #
        # Applications — especially browsers — tear down their
        # whole process tree over several seconds. A single
        # sighting of a dying process must NOT be treated as
        # evidence that the application is still running.
        # Poll until the process tree is actually gone.
        # -----------------------------------------------------

        stopped = self.wait_until_stopped(
            executable,
            attempts=12,
        )

        already_gone = (
            completed.returncode != 0
            and "not found" in (
                completed.stdout or ""
            ).lower() + (completed.stderr or "").lower()
        )

        success = (
            completed.returncode == 0
            and stopped
        ) or (already_gone and stopped)

        return {
            "success": success,
            "operation": "application.close",
            "application": target,
            "resolved_executable": executable,
            "running": False,
            "verified": stopped,
            "verification_type": "process_table_inspection",
            "verification_method": "tasklist",
            "return_code": completed.returncode,
            "stdout": (
                completed.stdout or ""
            ).strip(),
            "stderr": (
                completed.stderr or ""
            ).strip(),
            "message": (
                f"{target} closed successfully."
                if success
                else (
                    f"Genesis could not verify that "
                    f"{target} was closed."
                )
            ),
        }

    # =========================================================
    # RUNNING CHECK
    # =========================================================

    # -------------------------------------------------------------
    # Item 16B (C16): three process states, not two.
    # -------------------------------------------------------------
    #
    # The process table can fail to answer, and "no answer" is not the
    # same answer as "no". See running_state() for why that matters.
    STATE_RUNNING = "running"
    STATE_NOT_RUNNING = "not_running"
    STATE_UNKNOWN = "unknown"

    def running_state(
        self,
        executable: str,
        attempts: int = 1
    ) -> str:
        """Is the executable running, not running, or UNKNOWN?

        Item 16B (C16). Previously `is_running` returned a bare bool and
        turned every exception into `return False`. So a tasklist that
        could not be executed AT ALL was reported as "not running", and
        `close` -- which branches on exactly that value -- answered:

            {"success": True, "already_closed": True, "running": False,
             "verified": True,
             "verification_type": "process_table_inspection"}

        A certificate of inspection for an inspection that never
        happened. Reproduced by making tasklist raise: the application
        could be alive the entire time and Genesis reported it closed,
        verified.

        Three states instead of two:
          running     - the process table showed it
          not_running - the table was consulted and did not show it
          unknown     - the table could not be consulted at all
                        (tasklist missing, errored, non-zero exit, or
                        the host is not Windows)
        """

        if not executable:
            return self.STATE_UNKNOWN

        executable_name = (
            Path(executable)
            .name
            .lower()
        )

        if not executable_name:
            return self.STATE_UNKNOWN

        if os.name != "nt":
            # Process-table inspection is not implemented here. Saying
            # "not running" would be a claim about a platform we never
            # looked at.
            return self.STATE_UNKNOWN

        error: Optional[str] = None
        answered = False

        for _ in range(
            max(1, attempts)
        ):

            try:

                completed = subprocess.run(
                    [
                        "tasklist",
                        "/FI",
                        f"IMAGENAME eq {executable_name}",
                    ],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=5,
                )

                output = (
                    completed.stdout
                    or ""
                ).lower()

                if executable_name in output:

                    self._last_process_query_error = None
                    return self.STATE_RUNNING

                if completed.returncode != 0:
                    # The query ran and FAILED. A failure is not
                    # evidence of absence.
                    error = (
                        (completed.stderr or "").strip()
                        or f"tasklist exited {completed.returncode}"
                    )
                    continue

                # Exit 0 and the name is absent: the table answered.
                answered = True

            except Exception as failure:

                # Recorded, not swallowed. The old code turned every
                # one of these into `return False`, which is
                # indistinguishable from "asked, found nothing".
                error = str(failure)
                continue

            if attempts > 1:
                time.sleep(
                    0.5
                )

        self._last_process_query_error = error

        if answered:
            return self.STATE_NOT_RUNNING

        return self.STATE_UNKNOWN

    def is_running(
        self,
        executable: str,
        attempts: int = 1
    ) -> Optional[bool]:
        """
        Check whether the specific executable is running.

        Item 16B (C16): returns True, False, or **None** for UNKNOWN.
        None is falsy, so `if not manager.is_running(x)` behaves exactly
        as it always did -- but a caller that cares can now tell
        "confirmed absent" from "never asked". Prefer `running_state`
        where three states are available.
        """

        state = self.running_state(
            executable,
            attempts,
        )

        if state == self.STATE_RUNNING:
            return True
        if state == self.STATE_NOT_RUNNING:
            return False
        return None

    def wait_until_stopped(
        self,
        executable: str,
        attempts: int = 10,
        delay_seconds: float = 0.5,
    ) -> bool:
        """
        Poll the process table until the executable is gone.

        Returns True only when a poll confirms the process is
        no longer running. This is the correct verification
        primitive after close(): a dying process may still be
        visible in the process table for a short while, so the
        check must WAIT for absence instead of returning on
        the first sighting.
        """

        if not executable:
            return False

        if os.name != "nt":
            return False

        executable_name = Path(executable).name.lower()

        if not executable_name:
            return False

        for _ in range(max(1, attempts)):

            try:

                completed = subprocess.run(
                    [
                        "tasklist",
                        "/FI",
                        f"IMAGENAME eq {executable_name}",
                    ],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=5,
                )

                output = (
                    completed.stdout
                    or ""
                ).lower()

                if executable_name not in output:
                    return True

            except Exception:

                return False

            time.sleep(delay_seconds)

        return False

    # =========================================================
    # RESOLVE URI APPLICATION
    # =========================================================

    def resolve_uri(
        self,
        application: str
    ) -> Optional[str]:
        """
        Resolve a user-facing application name into a
        validated Windows URI.
        """

        target = self._normalize_name(
            application
        )

        if not target:

            return None

        return self.windows_uri_apps.get(
            target
        )

    # =========================================================
    # RESOLVE EXECUTABLE
    # =========================================================

    def resolve_application(
        self,
        application: str
    ) -> Optional[str]:
        """
    Resolve a human application reference into a
    validated executable path.

    Resolution flow:

        Human query
            â†“
        ApplicationResolutionEngine
            â†“
        Canonical application record
            â†“
        Executable/path extraction
            â†“
        PATH fallback
            â†“
        Known Windows installation fallback

    This method NEVER launches anything.
        """

        if application is None:
            return None

        query = str(application).strip()

        if not query:
            return None

    # =========================================================
    # 1. PRIMARY INTELLIGENT RESOLUTION
    # =========================================================

        result = self.resolution_engine.resolve(query)

        if result.decision != ResolutionDecision.RESOLVED:
            return None

        record = result.application

        if not isinstance(record, dict):
            return None

    # =========================================================
    # 2. CANONICAL EXECUTABLES
    # =========================================================

        executables = record.get(
            "executables",
            []
        )

        if not isinstance(
            executables,
            list
        ):
            executables = []

        for executable in executables:

            if not executable:
                continue

            executable = str(
                executable
            ).strip()

            if not executable:
                continue

        # Absolute path
            if os.path.isabs(executable):

                if os.path.isfile(executable):
                    return executable

        # Executable available through PATH
            located = shutil.which(
                executable
            )

            if located:
                 return located

    # =========================================================
    # 3. CANONICAL PATHS
    # =========================================================

        paths = record.get(
            "paths",
            []
        )

        if not isinstance(
            paths,
            list
        ):
            paths = []

        for path in paths:

            if not path:
                continue

            path = str(
                path
            ).strip()

            if not path:
                continue

            if os.path.isfile(path):

                if (
                     Path(path).suffix.lower()
                    == ".exe"
                ):
                    return path

    # =========================================================
    # 4. SINGLE EXECUTABLE FIELD
    # =========================================================

        single_executable = record.get(
            "executable"
        )

        if single_executable:

            single_executable = str(
                single_executable
            ).strip()

            if os.path.isabs(
                single_executable
            ):

                if os.path.isfile(
                     single_executable
                ):
                     return single_executable

            located = shutil.which(
                single_executable
            )

            if located:
                return located

    # =========================================================
    # 5. DISCOVERY LAUNCH TARGET
    # =========================================================

        launch_target = record.get(
            "launch_target"
        )

        if launch_target:

            launch_target = str(
                launch_target
            ).strip()

            if os.path.isabs(
                 launch_target
            ):

                if os.path.isfile(
                    launch_target
                ):

                    return launch_target

                located = shutil.which(
                    launch_target
                )

                if located:
                    return located

    # =========================================================
    # 6. SAFE BUILT-IN ALIAS FALLBACK
    #
    # This preserves the older ApplicationManager's
    # known Windows executable knowledge.
    # =========================================================

        normalized = self._normalize_name(
            query
        )

        executable_name = (
            self.application_aliases.get(
                normalized
            )
        )

        if not executable_name:
            # -------------------------------------------------
            # TYPO-TOLERANT FUZZY ALIAS MATCH
            #
            # Real users type "chrom", "notpad", "vscod".
            # Accept a CLOSE alias match instead of failing.
            # -------------------------------------------------

            from difflib import get_close_matches

            close = get_close_matches(
                normalized,
                self.application_aliases.keys(),
                n=1,
                cutoff=0.84,
            )

            if close:
                executable_name = self.application_aliases[close[0]]

        if executable_name:

        # PATH
            located = shutil.which(
                executable_name
            )

            if located:
                return located

        # Known installation paths
            candidates = (
                self.application_paths.get(
                    executable_name.lower(),
                    []
                )
            )

            for candidate in candidates:

                if not candidate:
                    continue

                candidate_path = Path(
                    candidate
                )

                if candidate_path.is_file():

                    return str(
                        candidate_path
                    )

    # =========================================================
    # 7. SAFE DIRECT EXECUTABLE FALLBACK
    # =========================================================

        if normalized.endswith(
            ".exe"
        ):

            located = shutil.which(
                normalized
            )

            if located:
                return located

    # =========================================================
    # NOTHING RESOLVED
    # =========================================================

        return None


    def resolve_application_record(
        self,
        application: str,
    ):
        """
    Resolve a human application reference into the
    canonical application record.

    This performs resolution only.

    It NEVER launches or modifies an application.
        """

        if application is None:

            return None

        query = str(
            application
        ).strip()

        if not query:

            return None

        result = self.resolution_engine.resolve(
            query
        )

        if (
            result.decision
            != ResolutionDecision.RESOLVED
        ):

            return None

        return result.application

    def resolve_application_intelligence(
        self,
        application: str,   
    ) -> dict:
        """
        Return the complete explainable resolution result.

        This is a resolution-only API.
        """

        result = self.resolution_engine.resolve(
            application
        )

        return result.to_dict()

    # =========================================================
    # APPLICATION ALIASES
    # =========================================================

    def list_applications(self) -> dict:
        """
        Return the applications Genesis currently knows.

        Useful for debugging and future GUI integration.
        """

        return {
            "executables": sorted(
                self.application_aliases.keys()
            ),
            "windows_uri": sorted(
                self.windows_uri_apps.keys()
            ),
            "count": (
                len(
                    self.application_aliases
                )
                +
                len(
                    self.windows_uri_apps
                )
            ),
            "version": self.VERSION,
        }

    # =========================================================
    # INTERNAL HELPERS
    # =========================================================

    def _normalize_name(
        self,
        application: str
    ) -> str:
        """
        Normalize an application name.
        """

        if not isinstance(
            application,
            str
        ):

            return ""

        return (
            application
            .strip()
            .lower()
            .strip("\"'")
        )

    # =========================================================
    # KNOWN WINDOWS PATHS
    # =========================================================

    def _build_known_paths(
        self
    ) -> Dict[str, List[str]]:
        """
        Build common Windows installation paths.

        Environment variables are used instead of
        hard-coded user directories.
        """

        local_app_data = os.environ.get(
            "LOCALAPPDATA",
            ""
        )

        program_files = os.environ.get(
            "PROGRAMFILES",
            ""
        )

        program_files_x86 = os.environ.get(
            "PROGRAMFILES(X86)",
            ""
        )

        program_data = os.environ.get(
            "PROGRAMDATA",
            ""
        )

        windir = os.environ.get(
            "WINDIR",
            "C:\\Windows"
        )

        paths = {}

        def add(
            executable,
            *candidates
        ):

            existing = paths.setdefault(
                executable.lower(),
                []
            )

            for candidate in candidates:

                if candidate:

                    existing.append(
                        candidate
                    )

        # =====================================================
        # CHROME
        # =====================================================

        add(
            "chrome.exe",

            os.path.join(
                local_app_data,
                "Google",
                "Chrome",
                "Application",
                "chrome.exe"
            ),

            os.path.join(
                program_files,
                "Google",
                "Chrome",
                "Application",
                "chrome.exe"
            ),

            os.path.join(
                program_files_x86,
                "Google",
                "Chrome",
                "Application",
                "chrome.exe"
            ),
        )

        # =====================================================
        # EDGE
        # =====================================================

        add(
            "msedge.exe",

            os.path.join(
                program_files,
                "Microsoft",
                "Edge",
                "Application",
                "msedge.exe"
            ),

            os.path.join(
                program_files_x86,
                "Microsoft",
                "Edge",
                "Application",
                "msedge.exe"
            ),
        )

        # =====================================================
        # FIREFOX
        # =====================================================

        add(
            "firefox.exe",

            os.path.join(
                program_files,
                "Mozilla Firefox",
                "firefox.exe"
            ),

            os.path.join(
                program_files_x86,
                "Mozilla Firefox",
                "firefox.exe"
            ),
        )

        # =====================================================
        # OPERA
        # =====================================================

        add(
            "opera.exe",

            os.path.join(
                local_app_data,
                "Programs",
                "Opera",
                "opera.exe"
            ),

            os.path.join(
                program_files,
                "Opera",
                "opera.exe"
            ),

            os.path.join(
                program_files_x86,
                "Opera",
                "opera.exe"
            ),
        )

        # =====================================================
        # BRAVE
        # =====================================================

        add(
            "brave.exe",

            os.path.join(
                program_files,
                "BraveSoftware",
                "Brave-Browser",
                "Application",
                "brave.exe"
            ),

            os.path.join(
                local_app_data,
                "BraveSoftware",
                "Brave-Browser",
                "Application",
                "brave.exe"
            ),
        )

        # =====================================================
        # VS CODE
        # =====================================================

        add(
            "code.exe",

            os.path.join(
                local_app_data,
                "Programs",
                "Microsoft VS Code",
                "Code.exe"
            ),

            os.path.join(
                program_files,
                "Microsoft VS Code",
                "Code.exe"
            ),

            os.path.join(
                program_files_x86,
                "Microsoft VS Code",
                "Code.exe"
            ),
        )

        # =====================================================
        # VISUAL STUDIO
        # =====================================================

        add(
            "devenv.exe",

            os.path.join(
                program_files,
                "Microsoft Visual Studio",
                "2022",
                "Community",
                "Common7",
                "IDE",
                "devenv.exe"
            ),

            os.path.join(
                program_files,
                "Microsoft Visual Studio",
                "2022",
                "Professional",
                "Common7",
                "IDE",
                "devenv.exe"
            ),

            os.path.join(
                program_files,
                "Microsoft Visual Studio",
                "2022",
                "Enterprise",
                "Common7",
                "IDE",
                "devenv.exe"
            ),
        )

        # =====================================================
        # NOTEPAD
        # =====================================================

        add(
            "notepad.exe",

            os.path.join(
                windir,
                "System32",
                "notepad.exe"
            ),

            os.path.join(
                windir,
                "notepad.exe"
            ),
        )

        # =====================================================
        # PAINT
        # =====================================================

        add(
            "mspaint.exe",

            os.path.join(
                windir,
                "System32",
                "mspaint.exe"
            ),

            os.path.join(
                windir,
                "mspaint.exe"
            ),
        )

        # =====================================================
        # EXPLORER
        # =====================================================

        add(
            "explorer.exe",

            os.path.join(
                windir,
                "explorer.exe"
            ),
        )

        # =====================================================
        # CMD
        # =====================================================

        add(
            "cmd.exe",

            os.path.join(
                windir,
                "System32",
                "cmd.exe"
            ),
        )

        # =====================================================
        # POWERSHELL
        # =====================================================

        add(
            "powershell.exe",

            os.path.join(
                windir,
                "System32",
                "WindowsPowerShell",
                "v1.0",
                "powershell.exe"
            ),
        )

        # =====================================================
        # TASK MANAGER
        # =====================================================

        add(
            "taskmgr.exe",

            os.path.join(
                windir,
                "System32",
                "Taskmgr.exe"
            ),
        )

        # =====================================================
        # CONTROL PANEL
        # =====================================================

        add(
            "control.exe",

            os.path.join(
                windir,
                "System32",
                "control.exe"
            ),
        )

        # =====================================================
        # REGISTRY EDITOR
        # =====================================================

        add(
            "regedit.exe",

            os.path.join(
                windir,
                "regedit.exe"
            ),

            os.path.join(
                windir,
                "System32",
                "regedit.exe"
            ),
        )

        # =====================================================
        # RESOURCE MONITOR
        # =====================================================

        add(
            "resmon.exe",

            os.path.join(
                windir,
                "System32",
                "resmon.exe"
            ),
        )

        # =====================================================
        # SYSTEM CONFIGURATION
        # =====================================================

        add(
            "msconfig.exe",

            os.path.join(
                windir,
                "System32",
                "msconfig.exe"
            ),
        )

        # =====================================================
        # CALCULATOR
        # =====================================================
        #
        # Modern Windows Calculator is often a packaged app.
        # The executable alias remains as a compatibility
        # fallback. The URI resolver can be extended later
        # if required by the installed Windows version.
        #

        add(
            "calc.exe",

            os.path.join(
                windir,
                "System32",
                "calc.exe"
            ),
        )

        # =====================================================
        # MICROSOFT OFFICE
        # =====================================================

        office_roots = [

            os.path.join(
                program_files,
                "Microsoft Office"
            ),

            os.path.join(
                program_files_x86,
                "Microsoft Office"
            ),

            os.path.join(
                program_files,
                "Microsoft Office",
                "root",
                "Office16"
            ),

            os.path.join(
                program_files_x86,
                "Microsoft Office",
                "root",
                "Office16"
            ),
        ]

        for root in office_roots:

            if not root:

                continue

            add(
                "WINWORD.EXE",
                os.path.join(
                    root,
                    "root",
                    "Office16",
                    "WINWORD.EXE"
                ),
                os.path.join(
                    root,
                    "Office16",
                    "WINWORD.EXE"
                ),
            )

            add(
                "EXCEL.EXE",
                os.path.join(
                    root,
                    "root",
                    "Office16",
                    "EXCEL.EXE"
                ),
                os.path.join(
                    root,
                    "Office16",
                    "EXCEL.EXE"
                ),
            )

            add(
                "POWERPNT.EXE",
                os.path.join(
                    root,
                    "root",
                    "Office16",
                    "POWERPNT.EXE"
                ),
                os.path.join(
                    root,
                    "Office16",
                    "POWERPNT.EXE"
                ),
            )

            add(
                "OUTLOOK.EXE",
                os.path.join(
                    root,
                    "root",
                    "Office16",
                    "OUTLOOK.EXE"
                ),
                os.path.join(
                    root,
                    "Office16",
                    "OUTLOOK.EXE"
                ),
            )

            add(
                "ONENOTE.EXE",
                os.path.join(
                    root,
                    "root",
                    "Office16",
                    "ONENOTE.EXE"
                ),
                os.path.join(
                    root,
                    "Office16",
                    "ONENOTE.EXE"
                ),
            )

        return paths

    # =========================================================
    # SAFE EXECUTABLE LAUNCH
    # =========================================================

    @staticmethod
    def _launch(
        executable: str,
        file_path: Optional[str] = None,
    ) -> None:
        """
        Launch a validated executable.

        shell=False is mandatory.
        """

        command = [executable]
        if file_path:
            command.append(str(file_path))

        subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

    # =========================================================
    # STANDARD ERROR
    # =========================================================

    @staticmethod
    def _error(
        message: str
    ) -> dict:

        return {
            "success": False,
            "operation": "application.unknown",
            "application": None,
            "message": message,
        }
