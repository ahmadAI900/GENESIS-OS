"""Genesis OS — Level 3 operating-system gateway."""
from __future__ import annotations

import os
import threading
import time

from genesis_os.applications.app_manager import ApplicationManager
from genesis_os.safe_file_manager import SafeFileManager
from genesis_os.filesystem.folder_manager import FolderManager
from genesis_os.system.system_manager import SystemManager
from genesis_os.browser_manager import BrowserManager
from genesis_os.network_manager import NetworkManager
from genesis_os.spreadsheet_manager import SpreadsheetManager
from genesis_os.document_manager import DocumentManager
from genesis_os.processes.process_manager import ProcessManager
from genesis_os.media_control import MediaController
from genesis_os.display_control import DisplayController
from genesis_os.hardware_intelligence import HardwareIntelligence
from genesis_os.clipboard_manager import ClipboardManager
from genesis_os.capture_manager import CaptureManager
from genesis_os.workstation_control import WorkstationController
from genesis_os.web_intelligence import WebIntelligence
from genesis_os.window_manager import WindowManager
from genesis_os.daily_intelligence import DailyIntelligence
from genesis_os.notes_manager import NotesManager
from genesis_os.package_manager import PackageManager
from genesis_os.cleanup_manager import CleanupManager

# LEVEL 3.14+ — NEW SUBSYSTEMS (lazy imports to avoid circular deps)
GUIController = None
DocumentIntelligence = None
SpreadsheetIntelligence = None
EnhancedObservationLoop = None
PersistentSessionState = None
SessionPersistence = None
ContextPipeline = None
MultiTurnTracker = None
SessionState = None

# Document / spreadsheet / browser post-state verification helpers.
# The previous Phase-0 audit identified these as the SELF_REPORTED_ONLY
# set: every method bound ``verified = result.success`` which conflates
# "no exception was raised" with "post-state was actually observed".
# The helpers expose one function per capability that derives verified
# from a real, cheap, observable post-state signal (file exists,
# non-empty payload, provider-reported URL, etc.). When no real
# signal is cheaply available they return ``verified=False`` with
# an explicit reason — honest "can't verify" beats fake "verified".
try:
    from genesis_os.verification_helpers import (
        verify_doc_inspect as _verify_doc_inspect,
        verify_doc_read as _verify_doc_read,
        verify_doc_search as _verify_doc_search,
        verify_doc_create as _verify_doc_create,
        verify_doc_compare as _verify_doc_compare,
        verify_doc_summarize as _verify_doc_summarize,
        verify_doc_edit as _verify_doc_edit,
        verify_doc_transform as _verify_doc_transform,
        verify_doc_verify as _verify_doc_verify,
        verify_sheet_inspect as _verify_sheet_inspect,
        verify_sheet_read as _verify_sheet_read,
        verify_sheet_sort as _verify_sheet_sort,
        verify_sheet_filter as _verify_sheet_filter,
        verify_sheet_calculate as _verify_sheet_calculate,
        verify_sheet_rank as _verify_sheet_rank,
        verify_sheet_add_column as _verify_sheet_add_column,
        verify_sheet_update_cell as _verify_sheet_update_cell,
        verify_sheet_create_from_dicts as _verify_sheet_create_from_dicts,
        verify_sheet_calculate_values as _verify_sheet_calculate_values,
        verify_sheet_rank_values as _verify_sheet_rank_values,
        verify_sheet_group_by as _verify_sheet_group_by,
        verify_sheet_aggregate as _verify_sheet_aggregate,
        verify_sheet_compare as _verify_sheet_compare,
        verify_data_inspect as _verify_data_inspect,
        verify_data_transform as _verify_data_transform,
        verify_browser_navigate as _verify_browser_navigate,
        verify_browser_click as _verify_browser_click,
        verify_browser_scroll as _verify_browser_scroll,
        verify_browser_type as _verify_browser_type,
        verify_browser_extract as _verify_browser_extract,
        verify_browser_find as _verify_browser_find,
        verify_browser_title as _verify_browser_title,
        verify_browser_tab_mgmt as _verify_browser_tab_mgmt,
        verify_browser_wait as _verify_browser_wait,
        verify_browser_screenshot as _verify_browser_screenshot,
        verify_browser_select as _verify_browser_select,
        verify_browser_download as _verify_browser_download,
        verify_browser_upload as _verify_browser_upload,
        verify_browser_verify as _verify_browser_verify,
        verify_browser_capabilities as _verify_browser_capabilities,
        verify_file_copy as _verify_file_copy,
        verify_file_move as _verify_file_move,
        verify_file_rename as _verify_file_rename,
        verify_file_delete as _verify_file_delete,
        verify_folder_create as _verify_folder_create,
        verify_folder_list as _verify_folder_list,
        verify_file_resolve as _verify_file_resolve,
    )
    _VERIFICATION_HELPERS_AVAILABLE = True
except Exception:  # pragma: no cover - import failure
    _VERIFICATION_HELPERS_AVAILABLE = False

def _import_new_subsystems():
    global GUIController, DocumentIntelligence, SpreadsheetIntelligence
    global EnhancedObservationLoop, PersistentSessionState, SessionPersistence
    global ContextPipeline, MultiTurnTracker, SessionState
    try:
        from genesis_os.gui_controller import GUIController as _GC
        GUIController = _GC
    except Exception:
        pass
    try:
        from genesis_os.document_intelligence import DocumentIntelligence as _DI
        DocumentIntelligence = _DI
    except Exception:
        pass
    try:
        from genesis_os.spreadsheet_intelligence import SpreadsheetIntelligence as _SI
        SpreadsheetIntelligence = _SI
    except Exception:
        pass
    try:
        from genesis_os.enhanced_observation import EnhancedObservationLoop as _EO
        EnhancedObservationLoop = _EO
    except Exception:
        pass
    try:
        from genesis_os.session_persistence import PersistentSessionState as _PSS, SessionPersistence as _SP
        PersistentSessionState = _PSS
        SessionPersistence = _SP
    except Exception:
        pass
    try:
        from genesis_os.context_pipeline import ContextPipeline as _CP, MultiTurnTracker as _MTT
        ContextPipeline = _CP
        MultiTurnTracker = _MTT
    except Exception:
        pass
    try:
        from genesis_os.session_state import SessionState as _SS
        SessionState = _SS
    except Exception:
        pass


class OSManager:
    """Single execution gateway for implemented Level 3 capabilities."""

    VERSION = "3.14.0"

    def __init__(self, applications=None, files=None, folders=None, system=None, browser=None, network=None):
        _import_new_subsystems()
        self.applications = applications or ApplicationManager()
        self.files = files or SafeFileManager()
        self.folders = folders or FolderManager()
        self.system = system or SystemManager()
        self.browser = browser or BrowserManager()
        self.network = network or NetworkManager()
        self.spreadsheets = SpreadsheetManager()
        self.documents = DocumentManager()
        self.processes = ProcessManager()

        # -----------------------------------------------------
        # LEVEL 3.10 — UNIVERSAL HARDWARE / DESKTOP CONTROL
        # -----------------------------------------------------

        self.media = MediaController()
        self.display = DisplayController()
        self.hardware = HardwareIntelligence()
        self.clipboard = ClipboardManager()
        self.capture = CaptureManager()
        self.workstation = WorkstationController()

        # -----------------------------------------------------
        # LEVEL 3.11 — WEB INTELLIGENCE
        # -----------------------------------------------------

        try:
            self.web = WebIntelligence()
        except Exception:
            self.web = None

        # -----------------------------------------------------
        # LEVEL 3.12 — WINDOWS / PRODUCTIVITY CONTROL
        # -----------------------------------------------------

        self.windows = WindowManager()
        self.daily = DailyIntelligence()
        self.notes = NotesManager()
        self.packages = PackageManager()
        self.cleanup = CleanupManager()

        # -----------------------------------------------------
        # LEVEL 3.14+ — NEW SUBSYSTEMS
        # -----------------------------------------------------

        # GUI interaction controller
        if GUIController is not None:
            try:
                self.gui = GUIController()
            except Exception:
                self.gui = None
        else:
            self.gui = None

        # Enhanced document intelligence (multi-format)
        if DocumentIntelligence is not None:
            try:
                self.doc_intel = DocumentIntelligence()
            except Exception:
                self.doc_intel = None
        else:
            self.doc_intel = None

        # Enhanced spreadsheet intelligence (multi-operation)
        if SpreadsheetIntelligence is not None:
            try:
                self.sheet_intel = SpreadsheetIntelligence()
            except Exception:
                self.sheet_intel = None
        else:
            self.sheet_intel = None

        # Session state with persistence
        if PersistentSessionState is not None and SessionPersistence is not None and SessionState is not None:
            try:
                self._session_state = SessionState()
                self._session_persistence = SessionPersistence()
                self.session = PersistentSessionState(self._session_state, self._session_persistence)
                self.session.restore()
            except Exception:
                self._session_state = SessionState() if SessionState is not None else None
                self.session = self._session_state
        else:
            self._session_state = None
            self.session = None

        # Enhanced observation loop
        if EnhancedObservationLoop is not None:
            try:
                self.observation = EnhancedObservationLoop(self)
            except Exception:
                self.observation = None
        else:
            self.observation = None

        # Context pipeline for multi-turn
        if ContextPipeline is not None and SessionState is not None:
            try:
                self.context_pipeline = ContextPipeline(
                    session_state=self._session_state or SessionState(),
                    decision_engine=None,
                )
            except Exception:
                self.context_pipeline = None
        else:
            self.context_pipeline = None

        # Multi-turn tracker
        if MultiTurnTracker is not None:
            try:
                self.multi_turn = MultiTurnTracker()
            except Exception:
                self.multi_turn = None
        else:
            self.multi_turn = None

        # -----------------------------------------------------
        # PHASE 7 — LIVE FILESYSTEM WATCHING
        # -----------------------------------------------------
        self._fs_monitor = None
        self._fs_event_log: list = []
        self._fs_lock = threading.Lock()
        self._fs_watching_path = None

    # Applications
    def open_application(
        self,
        application: str,
        file_path: str | None = None,
    ) -> dict:
        if file_path is None:
            return self.applications.open(application)
        return self.applications.open(application, file_path=file_path)
    def close_application(self, application: str) -> dict: return self.applications.close(application)
    def inspect_application(self, application: str) -> dict: return self.applications.inspect(application)
    def list_applications(self) -> dict:
        result = self.applications.list_applications()
        if not isinstance(result, dict):
            return {"success": False, "operation": "application.list", "error": "Invalid application inventory result.", "executed": False, "verified": False}
        result = dict(result)
        result.update({
            "success": True,
            "operation": "application.list",
            "executed": False,
            "verified": bool(result.get("verified", False)),
        })
        return result
    def application_running(self, application: str) -> dict:
        result = self.applications.inspect(application)
        if not isinstance(result, dict):
            return {"success": False, "operation": "application.is_running", "application": application, "error": "Invalid inspection result."}
        result = dict(result); result["operation"] = "application.is_running"
        return result

    # Files
    def inspect_file(self, path): return self.files.inspect(path)
    def read_file(self, path): return self.files.read(path)
    def search_file(self, path, query): return self.files.search(path, query)
    def hash_file(self, path, algorithm="sha256"): return self.files.hash(path, algorithm)
    def watch_file(self, path, event="modified"): return self.files.watch(path, event)
    def open_file(self, path): return self.files.open(path)
    def create_file(self, path, content="", **kwargs): return self.files.create(path, content, **kwargs)

    def copy_file(self, source, destination, **kwargs):
        result = self.files.copy(source, destination, **kwargs)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_file_copy(bool(result.get("success")), result.get("path"), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result

    def move_file(self, source, destination, **kwargs):
        result = self.files.move(source, destination, **kwargs)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_file_move(bool(result.get("success")), result.get("path"), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result

    def rename_file(self, source, new_name, **kwargs):
        result = self.files.rename(source, new_name, **kwargs)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_file_rename(bool(result.get("success")), result.get("path"), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result

    def delete_file(self, path, **kwargs):
        result = self.files.delete(path, **kwargs)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_file_delete(bool(result.get("success")), result.get("path"), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result

    # Folders
    def inspect_folder(self, path): return self.folders.inspect(path)
    def open_folder(self, path): return self.folders.open(path)

    def create_folder(self, path):
        result = self.folders.create(path)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_folder_create(bool(result.get("success")), result.get("path"), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result

    def list_folder(self, path):
        result = self.folders.inspect(path)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_folder_list(bool(result.get("success")), path, result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result

    def organize_folder(self, path, **kwargs): return self.folders.organize(path, **kwargs)
    def rename_folder(self, source, new_name, **kwargs): return self.folders.rename(source, new_name, **kwargs)
    def move_folder(self, source, destination, **kwargs): return self.folders.move(source, destination, **kwargs)
    def delete_folder(self, path, **kwargs): return self.folders.delete(path, **kwargs)

    # Browser/network/system
    def open_url(self, url): return self.browser.open_url(url)
    def web_search(self, query, engine="google"): return self.browser.search(query, engine)
    def system_status(self): return self.system.status()
    def open_settings(self, target): return self.system.open_settings(target)
    def list_wifi(self): return self.network.list_wifi()
    def connect_wifi(self, ssid, password, **kwargs): return self.network.connect_wifi(ssid, password, **kwargs)
    def sort_spreadsheet(self, path, column, **kwargs): return self.spreadsheets.sort(path, column, **kwargs)
    def create_docx(self, path, title, sections=None, **kwargs): return self.documents.create_docx(path, title, sections, **kwargs)
    # Processes (read-only intelligence)
    def list_processes(self, name=None, **kwargs): return self.processes.list(name, **kwargs)
    def inspect_process(self, name): return self.processes.inspect(name)

    # Advanced Browser (Level 3.13).
    #
    # Each wrapper now binds ``verified`` to a real, observable
    # post-state signal computed by ``verification_helpers`` rather
    # than trusting the underlying provider's success flag as a
    # synonym for verification. Where no cheap real signal is
    # available (click / type / upload / tab mgmt) the helper
    # returns ``verified=False`` with an explicit reason. This is
    # the same honest-fallback rule applied to doc / sheet ops.
    def browser_click(self, selector, session_id="default"):
        result = self.browser.click(selector, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_click(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_type(self, selector, text, session_id="default"):
        result = self.browser.type_text(selector, text, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_type(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_scroll(self, direction="down", amount=3, session_id="default"):
        result = self.browser.scroll(direction, amount, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_scroll(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_find(self, text, session_id="default"):
        result = self.browser.find_text(text, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_find(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_extract(self, selector=None, session_id="default"):
        result = self.browser.extract_text(selector, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_extract(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_get_title(self, session_id="default"):
        result = self.browser.get_page_title(session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_title(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_get_url(self, session_id="default"):
        result = self.browser.get_page_url(session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_title(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_switch_tab(self, index, session_id="default"):
        result = self.browser.switch_tab(index, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_tab_mgmt(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_open_tab(self, url=None, session_id="default"):
        result = self.browser.open_tab(url, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_tab_mgmt(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_close_tab(self, index=None, session_id="default"):
        result = self.browser.close_tab(index, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_tab_mgmt(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_get_tabs(self, session_id="default"):
        result = self.browser.get_tabs(session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_tab_mgmt(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_wait(self, selector, timeout=10.0, session_id="default"):
        result = self.browser.wait_for_element(selector, timeout, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_wait(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_screenshot(self, path=None, session_id="default"):
        result = self.browser.screenshot(path, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_screenshot(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_verify(self, expected_url=None, expected_title_contains=None, session_id="default"):
        result = self.browser.verify_page_state(expected_url, expected_title_contains, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_verify(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_capabilities(self):
        result = self.browser.get_available_capabilities()
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_capabilities(bool(result.get("provider") is not None), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_get_page_state(self, session_id="default"):
        result = self.browser.get_page_state(session_id)
        if isinstance(result, dict) and result.get("success"):
            result["verified"] = bool(
                result.get("url") or result.get("title") or result.get("text_length")
            )
            result["verification_reason"] = "browser page state observed" if result["verified"] else "browser page state was empty"
        elif isinstance(result, dict):
            result["verified"] = False
            result["verification_reason"] = "browser page state unavailable"
        return result
    def browser_select(self, selector, value=None, label=None, index=None, session_id="default"):
        result = self.browser.select(selector, value=value, label=label, index=index, session_id=session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_select(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_download(self, url, save_path=None, session_id="default"):
        result = self.browser.download(url, save_path, session_id=session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_download(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result
    def browser_upload(self, selector, file_path, session_id="default"):
        result = self.browser.upload(selector, file_path, session_id)
        if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
            v = _verify_browser_upload(bool(result.get("success")), result)
            result["verified"] = v["verified"]
            result["post_state_matches"] = bool(v["verified"])
            result["verification_reason"] = v["reason"]
        return result

    # Media / audio (Level 3.10)
    def media_transport(self, action): return self.media.send_media_key(action)
    def volume_step(self, direction, steps=2): return self.media.volume_step(direction, steps)
    def volume_set(self, percent): return self.media.set_volume(percent)
    def volume_get(self): return self.media.get_volume()
    def volume_mute_toggle(self, mute=None): return self.media.toggle_mute(mute)

    # Display (Level 3.10)
    def brightness_get(self): return self.display.get_brightness()
    def brightness_set(self, percent=None, direction=None): return self.display.set_brightness(percent, direction=direction)

    # Hardware intelligence (read-only, Level 3.10)
    def battery_status(self): return self.hardware.battery()
    def hardware_stats(self): return self.hardware.system_stats()

    # Clipboard (Level 3.10)
    def clipboard_copy(self, text): return self.clipboard.copy(text)
    def clipboard_paste(self): return self.clipboard.paste()

    # Screen capture (Level 3.10)
    def screenshot(self, path=None): return self.capture.screenshot(path)

    # Workstation (Level 3.10)
    def lock_workstation(self): return self.workstation.lock()

    # Web research (Level 3.11)
    def web_research(self, query, max_results=5):
        if self.web is None:
            return {"success": False, "operation": "web.research",
                    "error": "Web intelligence is unavailable.", "verified": False}
        return self.web.research(query, max_results)

    # Window management (Level 3.12)
    def minimize_all_windows(self): return self.windows.minimize_all()
    def restore_windows(self): return self.windows.restore_all()
    def show_desktop(self): return self.windows.toggle_desktop()

    # Daily intelligence (Level 3.12)
    def weather(self, city): return self.daily.weather(city)
    def world_clock(self, city): return self.daily.world_clock(city)
    def calculate(self, expression): return self.daily.calculate(expression)
    def storage_status(self): return self.daily.storage()

    # Notes (Level 3.12)
    def create_note(self, text): return self.notes.create_note(text)
    def list_notes(self): return self.notes.list_notes()

    # Packages (Level 3.12, confirmation-gated)
    def package_search(self, query, max_results=5): return self.packages.search(query, max_results)
    def package_install(self, package_id): return self.packages.install(package_id)
    def package_uninstall(self, package_id): return self.packages.uninstall(package_id)

    # Cleanup (Level 3.12, confirmation-gated)
    def recycle_bin_stats(self): return self.cleanup.recycle_bin_stats()
    def empty_recycle_bin(self): return self.cleanup.empty_recycle_bin()

    # -----------------------------------------------------
    # LEVEL 3.14+ — NEW CAPABILITY DELEGATIONS
    # -----------------------------------------------------

    # GUI interaction
    def gui_action(self, action, **kwargs):
        if self.gui is None:
            return {"success": False, "operation": f"gui.{action}", "error": "GUI controller is unavailable.", "verified": False}
        from genesis_os.gui_controller import GUIAction
        try:
            gui_action = GUIAction(action) if isinstance(action, str) else action
        except ValueError:
            return {"success": False, "operation": f"gui.{action}", "error": f"Unknown GUI action: {action}", "verified": False}
        result = self.gui.execute(gui_action, **kwargs)
        # verified is NOT a synonym for success. The provider
        # signals verification by setting ``data["verified"]``
        # (e.g. paste_text's clipboard readback); a provider
        # that performs no post-state check reports
        # ``verified=False`` so the executor can either trust
        # the caller (named-target focus) or run the runtime
        # focus resolver (implicit / focused-window target).
        provider_verified = False
        if isinstance(result.data, dict):
            provider_verified = bool(result.data.get("verified", False))
        payload = {"success": result.success, "operation": f"gui.{action}", "message": result.message,
                   "data": result.data, "error": result.error, "verified": provider_verified}
        if result.metadata:
            payload["gui_metadata"] = dict(result.metadata)
        return payload

    # Enhanced document intelligence.
    #
    # Each wrapper binds ``verified`` to a real, observable post-state
    # signal computed by the helpers in ``verification_helpers.py``
    # rather than to ``result.success``. The helper functions return
    # a dict like ``{"verified": True/False, "reason": "..."}``. When
    # a real, cheap signal is not available the helper returns
    # ``verified=False`` with an explicit reason -- the rule is
    # "honest 'can't verify' beats fake 'verified'".
    def doc_inspect(self, path):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.inspect", "error": "Document intelligence is unavailable.", "verified": False}
        result = self.doc_intel.inspect(path)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_inspect(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.inspect", "path": result.path,
                "format": result.format.value if result.format else None, "message": result.message,
                "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def doc_read(self, path):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.read", "error": "Document intelligence is unavailable.", "verified": False}
        result = self.doc_intel.read(path)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_read(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.read", "path": result.path,
                "format": result.format.value if result.format else None, "message": result.message,
                "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def doc_search(self, path, query):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.search", "error": "Document intelligence is unavailable.", "verified": False}
        result = self.doc_intel.search(path, query)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_search(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.search", "path": result.path,
                "message": result.message, "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def doc_create(self, path, doc_type="txt", title=None, content=None, sections=None, headers=None, rows=None):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.create", "error": "Document intelligence is unavailable.", "verified": False}
        if doc_type == "docx":
            result = self.doc_intel.create_docx(path, title=title, content=content, sections=sections)
        elif doc_type == "txt":
            result = self.doc_intel.create_txt(path, content or "")
        elif doc_type == "csv":
            result = self.doc_intel.create_csv(path, headers=headers or [], rows=rows or [])
        elif doc_type == "json":
            result = self.doc_intel.create_json(path, data=content)
        elif doc_type == "markdown":
            result = self.doc_intel.create_markdown(path, content or "")
        elif doc_type == "pdf":
            result = self.doc_intel.create_pdf(path, title=title or "Untitled", content=content or "")
        else:
            return {"success": False, "operation": "document.create", "error": f"Unsupported doc type: {doc_type}", "verified": False}
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_create(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.create", "path": result.path,
                "message": result.message, "error": result.error, "executed": bool(result.success),
                "file_exists": bool(v["verified"]),
                "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def doc_compare(self, path1, path2):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.compare", "error": "Document intelligence is unavailable.", "verified": False}
        result = self.doc_intel.compare(path1, path2)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_compare(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.compare", "message": result.message,
                "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def doc_summarize(self, path, max_length=None):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.summarize", "error": "Document intelligence is unavailable.", "verified": False}
        result = self.doc_intel.summarize(path, max_length=max_length)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_summarize(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.summarize", "path": result.path,
                "message": result.message, "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def doc_edit(self, path, find_text, replace_text, output=None):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.edit", "error": "Document intelligence is unavailable.", "verified": False}
        result = self.doc_intel.edit(path, find_text, replace_text, output=output)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_edit(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.edit", "path": result.path,
                "format": result.format.value if result.format else None, "message": result.message,
                "data": result.data, "error": result.error, "executed": bool(result.success),
                "content_match": bool(v["verified"]),
                "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def doc_transform(self, path, output_path, output_format):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.transform", "error": "Document intelligence is unavailable.", "verified": False}
        result = self.doc_intel.transform(path, output_path, output_format)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_transform(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.transform", "path": result.path,
                "format": result.format.value if result.format else None, "message": result.message,
                "data": result.data, "error": result.error, "executed": bool(result.success),
                "output_matches": bool(v["verified"]),
                "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def doc_verify(self, path, expected_content=None, expected_format=None):
        if self.doc_intel is None:
            return {"success": False, "operation": "document.verify", "error": "Document intelligence is unavailable.", "verified": False}
        result = self.doc_intel.verify(path, expected_content=expected_content, expected_format=expected_format)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_doc_verify(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "document.verify", "path": result.path,
                "format": result.format.value if result.format else None, "message": result.message,
                "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    # Enhanced spreadsheet intelligence.
    # Same contract as document.* above: verified is bound to a real
    # post-state signal computed in verification_helpers.py.
    def sheet_inspect(self, path):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.inspect", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.inspect(path)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_inspect(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "spreadsheet.inspect", "path": result.path,
                "message": result.message, "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def sheet_read(self, path, sheet_name=None):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.read", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.read_as_dicts(path, sheet_name)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_read(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "spreadsheet.read", "path": result.path,
                "message": result.message, "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def sheet_sort(self, path, column, descending=False, output=None):
        if self.sheet_intel is None:
            return self.sort_spreadsheet(path, column, descending=descending, output=output)
        result = self.sheet_intel.sort(path, column, descending=descending, output=output)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_sort(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "spreadsheet.sort", "path": result.path,
                "message": result.message, "error": result.error, "data": result.data,
                "output_matches": bool(v["verified"]), "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def sheet_filter(self, path, sheet_name, column, condition, value, output=None):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.filter", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.filter_rows(path, sheet_name, column, condition, value, output=output)
        filter_data = dict(result.data or {})
        payload = {
            "success": bool(result.success),
            "operation": "spreadsheet.filter",
            "path": result.path,
            "message": result.message,
            "data": filter_data,
            "error": result.error,
            **filter_data,
        }
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_filter(bool(result.success), result.path or path, payload)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        payload["verified"] = v["verified"]
        payload["output_matches"] = bool(v["verified"])
        payload["post_state_matches"] = bool(v["verified"])
        payload["verification_reason"] = v["reason"]
        return payload


    def sheet_calculate(self, path, sheet_name, formula_column, formula_template):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.calculate", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.calculate(path, sheet_name, formula_column, formula_template)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_calculate_values(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "spreadsheet.calculate", "path": result.path,
                "message": result.message, "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def sheet_rank(self, path, sheet_name, rank_column, output=None):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.rank", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.rank(path, sheet_name, rank_column, output=output)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_rank_values(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "spreadsheet.rank", "path": result.path,
                "message": result.message, "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def sheet_group_by(self, path, sheet_name, column, agg_column=None, operation="count"):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.group_by", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.group_by(path, sheet_name, column, agg_column=agg_column, operation=operation)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_group_by(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "spreadsheet.group_by", "path": result.path,
                "message": result.message, "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def sheet_aggregate(self, path, sheet_name, columns, operation="sum"):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.aggregate", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.aggregate(path, sheet_name, columns, operation=operation)
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_aggregate(result.success, result.path, result.data)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        return {"success": result.success, "operation": "spreadsheet.aggregate", "path": result.path,
                "message": result.message, "data": result.data, "error": result.error, "verified": v["verified"],
                "post_state_matches": bool(v["verified"]),
                "verification_reason": v["reason"]}

    def sheet_compare(self, path1, sheet1, path2, sheet2):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.compare", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.compare_sheets(path1, sheet1, path2, sheet2)
        payload = {
            "success": bool(result.success),
            "operation": "spreadsheet.compare",
            "path": result.path,
            "message": result.message,
            "data": result.data,
            "path1": path1,
            "path2": path2,
            "error": result.error,
        }
        if _VERIFICATION_HELPERS_AVAILABLE:
            v = _verify_sheet_compare(bool(result.success), path1, payload)
        else:
            v = {"verified": False, "reason": "verification helper unavailable"}
        payload["verified"] = v["verified"]
        payload["output_matches"] = bool(v["verified"])
        payload["post_state_matches"] = bool(v["verified"])
        payload["verification_reason"] = v["reason"]
        return payload

    def sheet_add_column(self, path, sheet_name, column_name, values, output=None):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.add_column", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.add_column(path, sheet_name, column_name, values, output=output)
        return self._sheet_result_payload("spreadsheet.add_column", result)

    def sheet_update_cell(self, path, sheet_name, row, column, value, output=None):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.update_cell", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.update_cell(path, sheet_name, row, column, value, output=output)
        return self._sheet_result_payload("spreadsheet.update_cell", result)

    def sheet_create_from_dicts(self, path, data, sheet_name="Sheet1"):
        if self.sheet_intel is None:
            return {"success": False, "operation": "spreadsheet.create_from_dicts", "error": "Spreadsheet intelligence is unavailable.", "verified": False}
        result = self.sheet_intel.create_from_dicts(path, data, sheet_name=sheet_name)
        return self._sheet_result_payload("spreadsheet.create_from_dicts", result)

    @staticmethod
    def _sheet_result_payload(operation, result):
        payload = {
            "success": bool(result.success),
            "operation": operation,
            "path": result.path,
            "message": result.message,
            "data": result.data,
            "error": result.error,
            "executed": bool(result.success),
        }
        if not _VERIFICATION_HELPERS_AVAILABLE or not isinstance(result.data, dict):
            payload["verified"] = False
            payload["verification_reason"] = "verification metadata unavailable"
            return payload
        verifiers = {
            "spreadsheet.add_column": _verify_sheet_add_column,
            "spreadsheet.update_cell": _verify_sheet_update_cell,
            "spreadsheet.create_from_dicts": _verify_sheet_create_from_dicts,
        }
        verifier = verifiers.get(operation)
        if verifier is None:
            payload["verified"] = False
            payload["verification_reason"] = "no mutation verifier is registered"
            return payload
        verification = verifier(result.success, result.path, result.data)
        payload["verified"] = verification["verified"]
        payload["output_matches"] = verification["verified"]
        payload["post_state_matches"] = verification["verified"]
        payload["verification_reason"] = verification["reason"]
        return payload

    def data_inspect(self, path):
        try:
            from genesis_os.structured_data import StructuredDataEngine
            schema = StructuredDataEngine().load(path, name=str(path))
            payload = {
                "success": True,
                "operation": "data.inspect",
                "path": path,
                "data": schema.to_dict(),
                "executed": False,
            }
            if _VERIFICATION_HELPERS_AVAILABLE:
                verification = _verify_data_inspect(True, path, payload["data"])
            else:
                verification = {"verified": False, "reason": "verification helper unavailable"}
            payload["verified"] = verification["verified"]
            payload["post_state_matches"] = verification["verified"]
            payload["verification_reason"] = verification["reason"]
            return payload
        except Exception as error:
            return {
                "success": False,
                "operation": "data.inspect",
                "path": path,
                "error": str(error),
                "executed": False,
                "verified": False,
            }

    def data_transform(self, path, operation="filter", output=None, **parameters):
        try:
            import csv
            import json
            from pathlib import Path
            from genesis_os.structured_data import StructuredDataEngine
            from genesis_os.file_intelligence.path_security import PathSecurity

            validation = PathSecurity.validate(path, require_existing=True, require_file=True)
            if not validation["allowed"]:
                raise ValueError(validation["reason"])
            engine = StructuredDataEngine()
            source_name = str(path)
            engine.load(path, name=source_name)
            operation = str(operation or "filter").lower()
            if operation == "filter":
                rows = engine.filter_data(source_name, list(parameters.get("conditions", [])))
            elif operation == "sort":
                rows = engine.sort_data(
                    source_name,
                    str(parameters.get("field", parameters.get("column", ""))),
                    bool(parameters.get("ascending", True)),
                )
            elif operation == "aggregate":
                rows = engine.aggregate(
                    source_name,
                    list(parameters.get("group_by", [])),
                    list(parameters.get("aggregations", [])),
                )
            else:
                raise ValueError(f"Unsupported data operation: {operation}")
            source = Path(path)
            destination = Path(output) if output else source.with_name(
                f"{source.stem}_{operation}{source.suffix}"
            )
            if destination.resolve() == source.resolve():
                raise ValueError("Data output must not overwrite the source artifact.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            suffix = destination.suffix.lower()
            if suffix == ".json":
                destination.write_text(
                    json.dumps(rows, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            elif suffix == ".xlsx":
                from openpyxl import Workbook

                workbook = Workbook()
                sheet = workbook.active
                if rows and isinstance(rows[0], dict):
                    headers = list(rows[0].keys())
                    sheet.append(headers)
                    for row in rows:
                        sheet.append([row.get(header, "") for header in headers])
                else:
                    for row in rows:
                        sheet.append(list(row) if isinstance(row, (list, tuple)) else [row])
                workbook.save(destination)
                workbook.close()
            elif suffix in {".csv", ".txt"}:
                headers = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
                with destination.open("w", newline="", encoding="utf-8") as handle:
                    if headers:
                        writer = csv.DictWriter(handle, fieldnames=headers)
                        writer.writeheader()
                        writer.writerows(rows)
                    else:
                        writer = csv.writer(handle)
                        writer.writerows(rows)
            else:
                raise ValueError(
                    f"Unsupported data output extension: {suffix}"
                )
            payload = {
                "success": True,
                "operation": "data.transform",
                "path": str(destination),
                "source": str(source),
                "data": {"output": str(destination), "rows": rows, "row_count": len(rows)},
                "executed": True,
            }
            if _VERIFICATION_HELPERS_AVAILABLE:
                verification = _verify_data_transform(True, str(destination), payload["data"])
            else:
                verification = {"verified": False, "reason": "verification helper unavailable"}
            payload["verified"] = verification["verified"]
            payload["post_state_matches"] = verification["verified"]
            payload["verification_reason"] = verification["reason"]
            return payload
        except Exception as error:
            return {
                "success": False,
                "operation": "data.transform",
                "path": path,
                "error": str(error),
                "executed": False,
                "verified": False,
            }

    # Context pipeline
    def resolve_context(self, text, conversation_history=None):
        if self.context_pipeline is None:
            return {"resolved_text": text, "is_continuation": False, "entities": [], "confidence": 1.0}
        try:
            result = self.context_pipeline.resolve_input(text, conversation_history or [])
            return {
                "original_text": result.original_text,
                "resolved_text": result.resolved_text,
                "is_continuation": result.is_continuation,
                "continuation_context": result.continuation_context,
                "resolved_references": result.resolved_references,
                "entities": result.entities,
                "confidence": result.confidence,
            }
        except Exception as e:
            return {"resolved_text": text, "is_continuation": False, "entities": [], "confidence": 1.0, "error": str(e)}

    def execute_application_action(self, operation: str, application: str) -> dict:
        mapping = {
            "application.open": self.open_application,
            "application.close": self.close_application,
            "application.inspect": self.inspect_application,
        }
        fn = mapping.get(operation)
        if fn is None:
            return {"success": False, "operation": operation, "application": application, "error": f"Unsupported application operation: {operation}"}
        return fn(application)

    # -----------------------------------------------------
    # PHASE 7 — LIVE FILESYSTEM WATCHING
    # -----------------------------------------------------

    def start_watching(self, path: str, recursive: bool = False) -> dict:
        """Start live filesystem monitoring of *path*.

        Real watchdog events only — no fake events, no polling
        fallback fabrication. The internal callback appends to
        ``self._fs_event_log`` (cap 200) and best-effort forwards
        to session state when available.
        """
        try:
            from genesis_os.filesystem_monitor import FilesystemMonitor, HAS_WATCHDOG
        except Exception as exc:
            return {"success": False, "error": f"filesystem monitor unavailable: {exc}", "watching": False}
        if not HAS_WATCHDOG:
            return {"success": False, "error": "watchdog not installed", "watching": False}
        if not path or not isinstance(path, str):
            return {"success": False, "error": "invalid path", "watching": False}
        if not os.path.exists(path):
            return {"success": False, "error": f"path does not exist: {path}", "watching": False}

        # Stop any previous monitor before starting a new one.
        try:
            old = getattr(self, "_fs_monitor", None)
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass
        except Exception:
            pass
        self._fs_monitor = None

        monitor = FilesystemMonitor()

        def _internal_callback(evt: dict) -> None:
            try:
                if isinstance(evt, dict):
                    event_name = evt.get("event", "unknown")
                    evt_path = evt.get("path", "")
                    ts = evt.get("timestamp", None)
                else:
                    event_name = getattr(evt, "event_type", "unknown")
                    evt_path = getattr(evt, "path", "")
                    ts = getattr(evt, "timestamp", None)
                try:
                    ts = float(ts)
                except Exception:
                    ts = time.time()
                entry = {"event": event_name, "path": evt_path, "timestamp": ts}
            except Exception:
                return
            try:
                with self._fs_lock:
                    self._fs_event_log.append(entry)
                    while len(self._fs_event_log) > 200:
                        del self._fs_event_log[0]
            except Exception:
                pass
            # Best-effort forward to session state (guarded, never raises).
            try:
                sess = (
                    getattr(self, "session_state", None)
                    or getattr(self, "_session_state", None)
                    or getattr(self, "session", None)
                )
                if sess is not None:
                    if hasattr(sess, "record_filesystem_event") and callable(getattr(sess, "record_filesystem_event")):
                        try:
                            sess.record_filesystem_event(dict(entry))
                        except Exception:
                            pass
                    elif hasattr(sess, "_metadata") and isinstance(getattr(sess, "_metadata"), dict):
                        try:
                            meta = getattr(sess, "_metadata")
                            buf = meta.get("fs_events")
                            if not isinstance(buf, list):
                                buf = []
                                meta["fs_events"] = buf
                            buf.append(dict(entry))
                            while len(buf) > 200:
                                del buf[0]
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            result = monitor.start(path, _internal_callback, recursive=bool(recursive))
        except Exception as exc:
            return {"success": False, "error": str(exc), "watching": False}
        if not isinstance(result, dict) or not result.get("success"):
            if isinstance(result, dict):
                result.setdefault("watching", False)
                return result
            return {"success": False, "error": "monitor start failed", "watching": False}
        self._fs_monitor = monitor
        self._fs_watching_path = path
        return {"success": True, "path": path, "watching": True, "recursive": bool(recursive)}

    def stop_watching(self) -> dict:
        """Stop live filesystem monitoring started by start_watching()."""
        monitor = getattr(self, "_fs_monitor", None)
        watched_path = getattr(self, "_fs_watching_path", None)
        if monitor is None:
            return {"success": True, "watching": False, "path": watched_path}
        try:
            monitor.stop()
        except Exception:
            pass
        self._fs_monitor = None
        self._fs_watching_path = None
        return {"success": True, "watching": False, "path": watched_path}

    def watched_events(self, limit: int = 50) -> list:
        """Return up to *limit* most-recent watched filesystem events."""
        try:
            limit = int(limit)
        except Exception:
            limit = 50
        if limit <= 0:
            return []
        try:
            with self._fs_lock:
                items = list(self._fs_event_log)
        except Exception:
            return []
        try:
            return [dict(e) for e in items[-limit:]]
        except Exception:
            return []

    def status(self) -> dict:
        return {
            "level": 3, "version": self.VERSION,
            "application_intelligence": True, "application_execution": True, "application_verification": True,
            "file_intelligence": True, "file_operations": True, "folder_intelligence": True,
            "browser_control": True, "network_control": True, "system_intelligence": True,
            "process_intelligence": True, "document_intelligence": self.doc_intel is not None,
            "spreadsheet_intelligence": self.sheet_intel is not None,
            "gui_interaction": self.gui is not None,
            "media_control": self.media.available,
            "volume_control": True,
            "display_control": self.display.available,
            "hardware_intelligence": self.hardware.available,
            "clipboard_control": self.clipboard.available,
            "screen_capture": self.capture.available,
            "session_persistence": isinstance(self.session, PersistentSessionState),
            "enhanced_observation": self.observation is not None,
            "context_pipeline": self.context_pipeline is not None,
            "multi_turn_tracking": self.multi_turn is not None,
            "automation": True, "autonomy": False, "read_only_process_control": True,
            "confirmation_required_for_destructive_actions": True,
        }
