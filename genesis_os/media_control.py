"""
Genesis OS — Level 3.10
Media & Audio Control.

Universal desktop media control through two complementary
mechanisms, chosen per operation:

    1. Windows virtual media keys (VK_MEDIA_*) injected through
       SendInput — works with ANY running media application
       without requiring its API.

    2. Windows Core Audio API (pycaw) for PRECISE endpoint
       volume percentage and mute state — the same interface
       the system tray uses.

No shell commands, no arbitrary process injection, no keylogging.
Only synthetic media/volume key events and the official audio
endpoint API are used.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Any, Dict, Optional


# ============================================================
# WINDOWS VIRTUAL KEY CODES
# ============================================================

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [
            # The union must include MOUSEINPUT: it is the
            # largest member and defines the real INPUT size
            # that SendInput validates against.
            ("mi", _MOUSEINPUT),
            ("ki", _KEYBDINPUT),
            ("hi", _HARDWAREINPUT),
        ]

    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _U),
    ]


def _press_key(vk_code: int) -> bool:
    """
    Inject one extended-key press+release. Returns whether the
    OS accepted both events.
    """

    inputs = (_INPUT * 2)()

    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ki.wVk = vk_code
    inputs[0].ki.dwFlags = KEYEVENTF_EXTENDEDKEY

    inputs[1].type = INPUT_KEYBOARD
    inputs[1].ki.wVk = vk_code
    inputs[1].ki.dwFlags = (
        KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP
    )

    sent = ctypes.windll.user32.SendInput(
        2,
        ctypes.pointer(inputs),
        ctypes.sizeof(_INPUT),
    )

    return sent == 2


class MediaController:

    VERSION = "3.10.0"

    def __init__(self):
        import os as _os
        self.available = _os.name == "nt"
        self._lock = threading.RLock()

    # =========================================================
    # MEDIA TRANSPORT (universal — any media app in focus)
    # =========================================================

    def send_media_key(self, action: str) -> dict:
        """
        Dispatch a media transport key.

        Supported actions: play_pause, next, previous, stop.
        """

        with self._lock:
            key_map = {
                "play_pause": VK_MEDIA_PLAY_PAUSE,
                "next": VK_MEDIA_NEXT_TRACK,
                "previous": VK_MEDIA_PREV_TRACK,
                "stop": VK_MEDIA_STOP,
            }

            normalized = str(action or "").strip().lower()

            vk = key_map.get(normalized)

            if vk is None:
                return self._failure(
                    "media.transport",
                    f"Unsupported media action '{action}'.",
                )

            try:
                sent = _press_key(vk)
            except Exception as error:
                return {
                    "success": False,
                    "operation": "media.transport",
                    "error": str(error),
                    "executed": False,
                    "verified": False,
                }

            return {
                "success": sent,
                "operation": "media.transport",
                "media_action": normalized,
                "mechanism": "virtual_media_key",
                "executed": sent,
                "verified": False,
                "verification_type": "dispatch_only",
                "message": (
                    f"Sent media key '{normalized}' to the active "
                    f"media application."
                    if sent
                    else "The media key could not be delivered."
                ),
            }

    # =========================================================
    # VOLUME — RELATIVE STEPS (virtual keys)
    # =========================================================

    def volume_step(self, direction: str, steps: int = 2) -> dict:
        """
        Nudge system volume up or down using the official
        volume virtual keys. Default: 2 steps of 2% each.
        """

        with self._lock:
            normalized = str(direction or "").strip().lower()

        vk = {
            "up": VK_VOLUME_UP,
            "down": VK_VOLUME_DOWN,
        }.get(normalized)

        if vk is None:
            return self._failure("volume.step", "Direction must be 'up' or 'down'.")

        steps = max(1, min(int(steps or 1), 25))

        before = self.get_volume()

        try:
            ok = all(_press_key(vk) for _ in range(steps))
        except Exception as error:
            return {"success": False, "operation": "volume.step",
                    "error": str(error), "executed": False, "verified": False}

        after = self.get_volume()

        changed = (
            isinstance(before, dict)
            and isinstance(after, dict)
            and before.get("volume_percent") != after.get("volume_percent")
        )

        verified = bool(ok and changed)

        return {
            "success": ok,
            "operation": "volume.step",
            "direction": normalized,
            "steps": steps,
            "before": before.get("volume_percent") if isinstance(before, dict) else None,
            "after": after.get("volume_percent") if isinstance(after, dict) else None,
            "executed": ok,
            "verified": verified,
            "post_state_matches": verified,
            "verification_type": "audio_endpoint_readback",
            "message": (
                f"Volume {normalized}: "
                f"{before.get('volume_percent') if isinstance(before, dict) else '?'}% -> "
                f"{after.get('volume_percent') if isinstance(after, dict) else '?'}%."
            ),
        }

    def toggle_mute(self, mute: Optional[bool] = None) -> dict:
        """
        Toggle (or set explicitly when mute is True/False) the
        system mute state.
        """

        with self._lock:
            current = self.get_volume()

        currently_muted = (
            bool(current["muted"])
            if isinstance(current, dict) and current.get("muted") is not None
            else None
        )

        if mute is not None and currently_muted == mute:
            return {
                "success": True,
                "operation": "volume.mute",
                "muted": currently_muted,
                "already_in_desired_state": True,
                "verified": True,
                "post_state_matches": True,
                "message": (
                    "Volume is already "
                    f"{'muted' if mute else 'unmuted'}."
                ),
            }

        try:
            sent = _press_key(VK_VOLUME_MUTE)
        except Exception as error:
            return {"success": False, "operation": "volume.mute",
                    "error": str(error), "executed": False, "verified": False}

        after = self.get_volume()

        new_muted = (
            bool(after["muted"])
            if isinstance(after, dict) and after.get("muted") is not None
            else None
        )

        verified = (
            new_muted is not None
            and (currently_muted is None or new_muted != currently_muted)
            and (mute is None or new_muted == mute)
        )

        return {
            "success": sent,
            "operation": "volume.mute",
            "was_muted": currently_muted,
            "muted": new_muted,
            "executed": sent,
            "verified": verified,
            "post_state_matches": verified,
            "verification_type": "audio_endpoint_readback",
            "message": (
                f"Volume {'muted' if new_muted else 'unmuted'}."
                if new_muted is not None
                else "Mute toggled."
            ),
        }

    # =========================================================
    # VOLUME — PRECISE PERCENTAGE (Core Audio / pycaw)
    # =========================================================

    @staticmethod
    def _endpoint():
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        device = AudioUtilities.GetSpeakers()

        # Modern pycaw exposes the endpoint volume interface
        # directly on the AudioDevice.
        endpoint_volume = getattr(device, "EndpointVolume", None)

        if endpoint_volume is not None:
            return endpoint_volume, IAudioEndpointVolume

        # Legacy pycaw activation path.
        from comtypes import CLSCTX_ALL

        interface = device.Activate(
            IAudioEndpointVolume._iid_,
            CLSCTX_ALL,
            None,
        )
        return interface, IAudioEndpointVolume

    def get_volume(self) -> dict:
        """
        Read the master audio endpoint volume and mute state
        through the official Windows Core Audio API.
        """

        with self._lock:
            try:
                interface, _ = self._endpoint()
                scalar = interface.GetMasterVolumeLevelScalar()
                muted = bool(interface.GetMute())
                percent = int(round(float(scalar) * 100))
                return {
                    "success": True,
                    "operation": "volume.get",
                    "volume_percent": max(0, min(100, percent)),
                    "muted": muted,
                    "available": True,
                    "verified": True,
                    "post_state_matches": True,
                    "verification_type": "audio_endpoint_query",
                }
            except Exception as error:
                return {
                    "success": False,
                    "operation": "volume.get",
                    "available": False,
                    "error": str(error),
                    "verified": False,
                }

    def set_volume(self, percent: int) -> dict:
        """
        Set master volume to an exact percentage through the
        official Windows Core Audio API.
        """

        try:
            level = int(str(percent).strip().rstrip("%").strip())
        except (TypeError, ValueError):
            return self._failure("volume.set", "Volume must be a number.")

        if not 0 <= level <= 100:
            return self._failure(
                "volume.set",
                "Volume must be between 0 and 100.",
            )

        before = self.get_volume()

        try:
            interface, IAudioEndpointVolume = self._endpoint()
            interface.SetMasterVolumeLevelScalar(level / 100.0, None)
        except Exception as error:
            return {"success": False, "operation": "volume.set",
                    "target": level, "error": str(error),
                    "executed": False, "verified": False}

        after = self.get_volume()

        applied = (
            isinstance(after, dict)
            and after.get("volume_percent") == level
        )

        return {
            # Item 13D (C7): same separation as display_control, and the
            # same rule as ActionResult.trustworthy_success -- "a raw
            # execution attempt is NOT enough". `success` says the call
            # was dispatched; `verified` says the endpoint confirmed the
            # level; `trustworthy_success` is the one a consumer must
            # read to decide whether to tell the user it worked.
            "success": applied,
            "operation": "volume.set",
            "before": before.get("volume_percent") if isinstance(before, dict) else None,
            "target": level,
            "after": after.get("volume_percent") if isinstance(after, dict) else None,
            "executed": True,
            "verified": applied,
            "trustworthy_success": applied,
            "verification_type": "audio_endpoint_readback",
            "message": f"Volume set to {level}%." if applied else (
                "Volume was set but the readback did not confirm it."
            ),
        }

    # =========================================================
    # INTERNALS
    # =========================================================

    @staticmethod
    def _failure(operation, reason):
        return {
            "success": False,
            "operation": operation,
            "error": reason,
            "message": reason,
            "executed": False,
            "verified": False,
        }
