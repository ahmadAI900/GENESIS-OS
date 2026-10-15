"""
Genesis OS — Level 3.12
Daily Intelligence.

Everyday operating-system intelligence:

    - weather          (wttr.in public service, no API key,
                        read-only network fetch)
    - world clock      (stdlib zoneinfo)
    - quick calculator (strict AST arithmetic evaluator —
                        NEVER eval())
    - storage          (psutil disk usage across drives)

Every function is read-only or pure computation.
"""

from __future__ import annotations

import ast
import operator
import platform
from datetime import datetime


class DailyIntelligence:

    VERSION = "3.12.0"

    # =========================================================
    # WEATHER
    # =========================================================

    def weather(self, city: str) -> dict:
        """
        Current weather through the public wttr.in service
        (no API key required). Honest failure when offline.
        """

        if not isinstance(city, str) or not city.strip():
            return self._failure("web.weather", "A location is required.")

        query = city.strip().replace(" ", "+")

        try:
            import requests

            response = requests.get(
                f"https://wttr.in/{query}?format=3",
                timeout=8,
                headers={"User-Agent": "GenesisOS/3.12"},
            )

        except Exception as error:
            return {
                "success": False,
                "operation": "web.weather",
                "location": city.strip(),
                "error": f"Weather lookup failed: {error}",
                "executed": True,
                "verified": False,
            }

        if response.status_code != 200:
            return {
                "success": False,
                "operation": "web.weather",
                "location": city.strip(),
                "error": (
                    f"The weather service returned "
                    f"HTTP {response.status_code} for '{city}'."
                ),
                "executed": True,
                "verified": False,
            }

        report = response.text.strip()

        if not report:
            return {
                "success": False,
                "operation": "web.weather",
                "location": city.strip(),
                "error": "The weather service returned an empty report.",
                "executed": True,
                "verified": False,
            }

        return {
            "success": True,
            "operation": "web.weather",
            "location": city.strip(),
            "report": report,
            "executed": True,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "live_service_response",
            "message": report,
        }

    # =========================================================
    # WORLD CLOCK
    # =========================================================

    _CITY_ZONES = {
        "london": "Europe/London",
        "paris": "Europe/Paris",
        "berlin": "Europe/Berlin",
        "madrid": "Europe/Madrid",
        "rome": "Europe/Rome",
        "moscow": "Europe/Moscow",
        "istanbul": "Europe/Istanbul",
        "dubai": "Asia/Dubai",
        "karachi": "Asia/Karachi",
        "lahore": "Asia/Karachi",
        "islamabad": "Asia/Karachi",
        "delhi": "Asia/Kolkata",
        "mumbai": "Asia/Kolkata",
        "kolkata": "Asia/Kolkata",
        "dhaka": "Asia/Dhaka",
        "kathmandu": "Asia/Kathmandu",
        "beijing": "Asia/Shanghai",
        "shanghai": "Asia/Shanghai",
        "hong kong": "Asia/Hong_Kong",
        "singapore": "Asia/Singapore",
        "tokyo": "Asia/Tokyo",
        "seoul": "Asia/Seoul",
        "sydney": "Australia/Sydney",
        "melbourne": "Australia/Melbourne",
        "auckland": "Pacific/Auckland",
        "new york": "America/New_York",
        "washington": "America/New_York",
        "toronto": "America/Toronto",
        "chicago": "America/Chicago",
        "denver": "America/Denver",
        "los angeles": "America/Los_Angeles",
        "san francisco": "America/Los_Angeles",
        "vancouver": "America/Vancouver",
        "mexico city": "America/Mexico_City",
        "sao paulo": "America/Sao_Paulo",
        "buenos aires": "America/Argentina/Buenos_Aires",
        "cairo": "Africa/Cairo",
        "lagos": "Africa/Lagos",
        "nairobi": "Africa/Nairobi",
        "johannesburg": "Africa/Johannesburg",
        "riyadh": "Asia/Riyadh",
        "tehran": "Asia/Tehran",
        "jakarta": "Asia/Jakarta",
        "bangkok": "Asia/Bangkok",
    }

    def world_clock(self, city: str) -> dict:
        """
        Current date/time in a supported city using stdlib
        zoneinfo — no network needed.
        """

        if not isinstance(city, str) or not city.strip():
            return self._failure("time.world_clock", "A city name is required.")

        key = city.strip().lower()
        zone_name = self._CITY_ZONES.get(key)

        if zone_name is None:
            # Attempt direct IANA conversion: "Europe/Prague".
            guess = city.strip().title().replace(" ", "_")
            if "/" in city or self._zone_exists(guess):
                zone_name = guess

        if zone_name is None:
            return {
                "success": False,
                "operation": "time.world_clock",
                "city": city.strip(),
                "error": (
                    f"Genesis does not know the timezone for "
                    f"'{city}'. Try a major city."
                ),
                "verified": False,
            }

        try:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(zone_name))

        except Exception as error:
            return {
                "success": False,
                "operation": "time.world_clock",
                "city": city.strip(),
                "error": str(error),
                "verified": False,
            }

        stamp = now.strftime("%A, %d %B %Y · %H:%M")

        return {
            "success": True,
            "operation": "time.world_clock",
            "city": city.strip(),
            "timezone": zone_name,
            "local_time": now.strftime("%H:%M"),
            "local_date": now.strftime("%Y-%m-%d"),
            "executed": False,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "timezone_query",
            "message": f"{city.strip().title()}: {stamp}",
        }

    @staticmethod
    def _zone_exists(name: str) -> bool:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(name)
            return True
        except Exception:
            return False

    # =========================================================
    # CALCULATOR — STRICT ARITHMETIC ONLY
    # =========================================================

    _OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def calculate(self, expression: str) -> dict:
        """
        Evaluate a PURE ARITHMETIC expression safely.

        The expression is parsed with the ast module and every
        node type is allow-listed. Names, calls, attributes and
        any non-arithmetic syntax are rejected BEFORE anything
        executes. This is not eval() and can never become one.
        """

        if not isinstance(expression, str) or not expression.strip():
            return self._failure("math.evaluate", "An expression is required.")

        cleaned = expression.strip().rstrip("?").strip()

        # Replace common words/symbols users type.
        normalized = (
            cleaned.replace("×", "*")
            .replace("÷", "/")
            .replace("^", "**")
            .replace(",", "")
        )

        try:
            tree = ast.parse(normalized, mode="eval")
            value = self._safe_eval(tree.body)
        except self._MathError as error:
            return {
                "success": False,
                "operation": "math.evaluate",
                "expression": cleaned,
                "error": str(error),
                "executed": False,
                "verified": False,
            }
        except ZeroDivisionError:
            return {
                "success": False,
                "operation": "math.evaluate",
                "expression": cleaned,
                "error": "Division by zero.",
                "executed": False,
                "verified": False,
            }
        except Exception as error:
            return {
                "success": False,
                "operation": "math.evaluate",
                "expression": cleaned,
                "error": f"That is not valid arithmetic: {error}",
                "executed": False,
                "verified": False,
            }

        if isinstance(value, float) and value.is_integer():
            value = int(value)

        return {
            "success": True,
            "operation": "math.evaluate",
            "expression": cleaned,
            "result": value,
            "executed": False,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "pure_computation",
            "message": f"{cleaned} = {value}",
        }

    class _MathError(Exception):
        pass

    def _safe_eval(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise self._MathError("Only numbers are allowed.")

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self._OPERATORS:
                raise self._MathError("Only + - * / // % ** are allowed.")
            left = self._safe_eval(node.left)
            right = self._safe_eval(node.right)
            return self._OPERATORS[op_type](left, right)

        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in self._OPERATORS:
                raise self._MathError("Only unary +/- is allowed.")
            return self._OPERATORS[op_type](self._safe_eval(node.operand))

        raise self._MathError(
            "Only plain arithmetic expressions are allowed."
        )

    # =========================================================
    # STORAGE
    # =========================================================

    def storage(self) -> dict:
        """
        Disk space per fixed drive.
        """

        try:
            import psutil
        except Exception:
            return {
                "success": False,
                "operation": "hardware.storage",
                "available": False,
                "error": "Storage intelligence is unavailable.",
                "verified": False,
            }

        drives = []

        if platform.system() == "Windows":
            import string
            from ctypes import windll

            bitmask = windll.kernel32.GetLogicalDrives()
            letters = [
                letter
                for index, letter in enumerate(string.ascii_uppercase)
                if bitmask & (1 << index)
            ]
        else:
            letters = ["/"]

        for letter in letters:
            mount = f"{letter}:\\" if platform.system() == "Windows" else letter

            try:
                usage = psutil.disk_usage(mount)
            except Exception:
                continue

            drives.append({
                "drive": letter if platform.system() == "Windows" else mount,
                "total_gb": round(usage.total / 1024 ** 3, 1),
                "used_gb": round(usage.used / 1024 ** 3, 1),
                "free_gb": round(usage.free / 1024 ** 3, 1),
                "free_percent": round(100 * usage.free / usage.total, 1),
            })

        if not drives:
            return {
                "success": False,
                "operation": "hardware.storage",
                "error": "No readable drives were found.",
                "verified": False,
            }

        primary = drives[0]

        return {
            "success": True,
            "operation": "hardware.storage",
            "drives": drives,
            "primary_free_gb": primary["free_gb"],
            "primary_total_gb": primary["total_gb"],
            "executed": False,
            "verified": True,
            "post_state_matches": True,
            "verification_type": "hardware_query",
            "message": (
                f"Drive {primary['drive']}: {primary['free_gb']} GB free "
                f"of {primary['total_gb']} GB "
                f"({primary['free_percent']}% free)."
            ),
        }

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
