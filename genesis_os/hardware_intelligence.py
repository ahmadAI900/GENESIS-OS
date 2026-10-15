"""
Genesis OS — Level 3.10
Hardware Intelligence.

Read-only machine intelligence through psutil and the
platform APIs:

    - battery percentage / charging state
    - CPU and memory pressure
    - system uptime

This module NEVER modifies anything.
"""

from __future__ import annotations

import platform
import time


class HardwareIntelligence:

    VERSION = "3.10.0"

    def __init__(self):
        try:
            import psutil  # noqa: F401
            self._psutil = psutil
            self.available = True
        except Exception:
            self._psutil = None
            self.available = False

    # =========================================================
    # BATTERY
    # =========================================================

    def battery(self) -> dict:
        """
        Report battery level, charging state, and — when the
        hardware exposes it — remaining time estimates.
        """

        if not self.available:
            return {
                "success": False,
                "operation": "hardware.battery",
                "available": False,
                "error": "Hardware intelligence is unavailable.",
                "verified": False,
            }

        try:
            sensor = self._psutil.sensors_battery()
        except Exception as error:
            return {
                "success": False,
                "operation": "hardware.battery",
                "error": str(error),
                "verified": False,
            }

        if sensor is None:
            return {
                "success": True,
                "operation": "hardware.battery",
                "available": False,
                "battery_present": False,
                "message": (
                    "This machine does not expose a battery "
                    "(desktop or AC-only system)."
                ),
                "executed": False,
                "verified": True,
                "post_state_matches": True,
                "verification_type": "hardware_query",
            }

        percent = max(0.0, min(100.0, float(sensor.percent)))
        plugged = bool(sensor.power_plugged)

        if plugged:
            health = "Charging" if percent < 100 else "Fully charged"
        elif percent <= 20:
            health = "Low battery"
        else:
            health = "On battery"

        return {
            "success": True,
            "operation": "hardware.battery",
            "battery_percent": round(percent, 1),
            "plugged_in": plugged,
            "status": health,
            "executed": False,
            "verified": True,
            "verification_type": "hardware_query",
            "message": (
                f"Battery is at {round(percent)}% "
                f"({'plugged in' if plugged else 'on battery'})."
            ),
        }

    # =========================================================
    # SYSTEM PRESSURE
    # =========================================================

    def system_stats(self) -> dict:
        """
        Snapshot of CPU, memory, and uptime.
        """

        if not self.available:
            return {
                "success": False,
                "operation": "hardware.stats",
                "available": False,
                "error": "Hardware intelligence is unavailable.",
                "verified": False,
            }

        try:
            cpu_percent = float(self._psutil.cpu_percent(interval=0.25))
            memory = self._psutil.virtual_memory()
            boot_time = self._psutil.boot_time()

            uptime_seconds = int(time.time() - boot_time)

            hours, remainder = divmod(uptime_seconds, 3600)
            minutes = remainder // 60

            return {
                "success": True,
                "operation": "hardware.stats",
                "cpu_percent": round(cpu_percent, 1),
                "memory_percent": round(float(memory.percent), 1),
                "memory_used_gb": round(memory.used / (1024 ** 3), 2),
                "memory_total_gb": round(memory.total / (1024 ** 3), 2),
                "uptime_hours": hours,
                "uptime_minutes": minutes,
                "platform": f"{platform.system()} {platform.release()}",
                "executed": False,
                "verified": True,
                "post_state_matches": True,
                "verification_type": "hardware_query",
                "message": (
                    f"CPU {round(cpu_percent)}%, memory "
                    f"{round(memory.percent)}% "
                    f"({round(memory.used / (1024 ** 3), 1)}/"
                    f"{round(memory.total / (1024 ** 3), 1)} GB), "
                    f"up {hours}h {minutes}m."
                ),
            }

        except Exception as error:
            return {
                "success": False,
                "operation": "hardware.stats",
                "error": str(error),
                "verified": False,
            }
