"""Genesis OS — conservative Windows Wi-Fi controls."""
from __future__ import annotations
import os
import subprocess
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET


class NetworkManager:
    VERSION = "3.8.0"

    def list_wifi(self) -> dict:
        if os.name != "nt":
            return {"success": False, "operation": "network.list_wifi", "error": "Wi-Fi discovery is currently implemented for Windows."}
        try:
            result = subprocess.run(["netsh", "wlan", "show", "networks", "mode=bssid"],
                                    capture_output=True, text=True, timeout=15, check=False)
            return {"success": result.returncode == 0, "operation": "network.list_wifi",
                    "output": result.stdout, "error": result.stderr if result.returncode else None,
                    "executed": True, "verified": result.returncode == 0}
        except Exception as exc:
            return {"success": False, "operation": "network.list_wifi", "error": str(exc)}

    def connect_wifi(self, ssid: str, password: str, *, confirmed=False) -> dict:
        if not confirmed:
            return {"success": False, "operation": "network.connect_wifi", "status": "confirmation_required",
                    "requires_confirmation": True, "confirmation_message": f"Confirm connecting this computer to Wi-Fi network '{ssid}'."}
        if os.name != "nt":
            return {"success": False, "operation": "network.connect_wifi", "error": "Wi-Fi connection is currently implemented for Windows."}
        if not isinstance(ssid, str) or not ssid.strip() or not isinstance(password, str):
            return {"success": False, "operation": "network.connect_wifi", "error": "SSID and password are required."}
        root = ET.Element("WLANProfile", xmlns="http://www.microsoft.com/networking/WLAN/profile/v1")
        ET.SubElement(root, "name").text = ssid
        ssid_config = ET.SubElement(root, "SSIDConfig")
        ET.SubElement(ssid_config, "SSID")
        ssid_node = ssid_config.find("SSID")
        ET.SubElement(ssid_node, "name").text = ssid
        conn = ET.SubElement(root, "connectionType"); conn.text = "ESS"
        conn_mode = ET.SubElement(root, "connectionMode"); conn_mode.text = "auto"
        msm = ET.SubElement(root, "MSM")
        sec = ET.SubElement(msm, "security")
        auth = ET.SubElement(sec, "authEncryption")
        ET.SubElement(auth, "authentication").text = "WPA2PSK"
        ET.SubElement(auth, "encryption").text = "AES"
        ET.SubElement(auth, "useOneX").text = "false"
        shared = ET.SubElement(sec, "sharedKey")
        ET.SubElement(shared, "keyType").text = "passPhrase"
        ET.SubElement(shared, "protected").text = "false"
        # TODO: Security risk — storing password in plaintext XML.
        # Use a hashed keyMaterial instead of the actual password.
        ET.SubElement(shared, "keyMaterial").text = password
        try:
            with tempfile.TemporaryDirectory() as td:
                profile = Path(td) / "genesis_wifi.xml"
                ET.ElementTree(root).write(profile, encoding="utf-8", xml_declaration=True)
                add = subprocess.run(["netsh", "wlan", "add", "profile", f"filename={profile}", "user=current"],
                                     capture_output=True, text=True, timeout=15, check=False)
                if add.returncode != 0:
                    return {"success": False, "operation": "network.connect_wifi", "error": add.stderr or add.stdout}
                connect = subprocess.run(["netsh", "wlan", "connect", f"name={ssid}"],
                                         capture_output=True, text=True, timeout=20, check=False)
                return {"success": connect.returncode == 0, "operation": "network.connect_wifi", "ssid": ssid,
                        "executed": True, "verified": connect.returncode == 0,
                        "error": connect.stderr if connect.returncode else None,
                        "message": connect.stdout.strip() if connect.stdout else "Wi-Fi connection requested."}
        except Exception as exc:
            return {"success": False, "operation": "network.connect_wifi", "error": str(exc), "executed": False, "verified": False}
