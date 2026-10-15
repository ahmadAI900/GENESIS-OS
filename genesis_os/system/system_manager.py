"""Genesis OS — conservative system controls."""
from __future__ import annotations
import os
import platform
import webbrowser


class SystemManager:
    VERSION = "3.8.0"

    SETTINGS = {
        "wifi": "ms-settings:network-wifi",
        "network": "ms-settings:network",
        "bluetooth": "ms-settings:bluetooth",
        "display": "ms-settings:display",
        "sound": "ms-settings:sound",
        "apps": "ms-settings:appsfeatures",
        "privacy": "ms-settings:privacy",
        "windows update": "ms-settings:windowsupdate",
        "accounts": "ms-settings:accounts",
    }

    def status(self):
        return {"success": True, "operation": "system.status", "platform": platform.platform(),
                "os": os.name, "system": platform.system(), "release": platform.release(),
                "executed": False, "verified": True, "post_state_matches": True,
                "verification_type": "system_query"}

    def open_settings(self, target: str):
        key = str(target).strip().lower()
        uri = self.SETTINGS.get(key)
        if uri is None:
            return {"success": False, "operation": "system.open_settings", "error": "Unknown settings target."}
        try:
            if os.name == "nt":
                os.startfile(uri)
            else:
                webbrowser.open(uri)
            return {"success": True, "operation": "system.open_settings", "target": key,
                    "executed": True, "verified": False,
                    "verification_type": "dispatch_only",
                    "verification_reason": "Settings dispatch was not independently observed.",
                    "message": f"Dispatched {key} settings."}
        except Exception as exc:
            return {"success": False, "operation": "system.open_settings", "error": str(exc), "executed": False, "verified": False}
