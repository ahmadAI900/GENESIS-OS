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
        # `confirmed` is ACCEPTED BUT IGNORED (Item 3B-3b); it is not an
        # authority. Connecting to a network is Tier 1 at the executor's
        # blast-radius gate and requires a valid AuthorizationGrant before
        # this is reached. The Wi-Fi password itself is written in
        # plaintext into the WLAN profile below -- see the TODO there.
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
        # The PSK is written into the profile XML because netsh requires it.
        # The file lives in a TemporaryDirectory that is removed on the
        # way out of this function, so it does not persist; it is never
        # logged, never echoed into the result, and never placed on a
        # command line (verified: the password appears in neither the
        # returned dict nor any netsh argv).
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

                # `netsh wlan connect` returning 0 means the REQUEST was
                # accepted, NOT that the interface associated -- it is
                # asynchronous and routinely returns 0 for a network that
                # then fails to join. Verification therefore reads the
                # real post-state instead of the exit code.
                connected, observed_ssid, detail = self._interface_state(ssid)
                requested = connect.returncode == 0

                return {
                    "success": connected,
                    "operation": "network.connect_wifi",
                    "ssid": ssid,
                    "connected_ssid": observed_ssid,
                    # Executed: netsh accepted the request. Verified: the
                    # interface is actually associated with this SSID.
                    "executed": requested,
                    "verified": connected,
                    "verification_type": "interface_state",
                    "verification_detail": detail,
                    "error": (
                        None if connected
                        else (
                            connect.stderr
                            or (detail if not requested is False else None)
                            or "netsh accepted the connection request but the "
                               "wireless interface is not connected to this SSID."
                        )
                    ),
                    "message": (
                        f"Connected to Wi-Fi network '{ssid}'."
                        if connected
                        else f"Wi-Fi connection to '{ssid}' could not be confirmed."
                    ),
                }
        except Exception as exc:
            return {"success": False, "operation": "network.connect_wifi", "error": str(exc), "executed": False, "verified": False}

    def _interface_state(self, ssid: str):
        """Read the real wireless post-state from ``netsh``.

        Returns ``(connected, observed_ssid, detail)``. ``connected`` is
        True only when an interface reports ``State: connected`` AND its
        ``SSID`` matches the network we asked for -- a connected
        interface on some OTHER network is not a successful connection to
        this one.

        Fails closed: any error, timeout, or unparsable output yields
        ``connected=False`` rather than crediting the connection.
        """
        try:
            proc = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=15, check=False,
            )
        except Exception as exc:
            return False, None, f"could not read interface state: {exc}"

        if proc.returncode != 0:
            return False, None, (
                proc.stderr or "netsh wlan show interfaces did not succeed"
            )

        state = None
        observed = None
        for line in (proc.stdout or "").splitlines():
            stripped = line.strip()
            if ":" not in stripped:
                continue
            label, _, value = stripped.partition(":")
            label = label.strip().lower()
            value = value.strip()
            if label == "state":
                state = value.lower()
            elif label == "ssid" and observed is None and value:
                observed = value

        if state is None:
            return False, None, "interface state could not be parsed"

        if state != "connected":
            return False, observed, f"interface state is {state!r}, not connected"

        if observed is None:
            return False, None, "interface is connected but reports no SSID"

        if observed.strip().casefold() != str(ssid).strip().casefold():
            return False, observed, (
                f"interface is connected to {observed!r}, not {ssid!r}"
            )

        return True, observed, f"interface is connected to {observed!r}"
