"""
Genesis OS — Level 3.10
Display Control.

Screen brightness control through the
screen-brightness-control abstraction, which supports the
Windows WMI and monitor VCP/MCCS interfaces.

Readback verification: a set is only reported as verified when
a subsequent query confirms the applied value.
"""

from __future__ import annotations

from typing import Optional


class DisplayController:

    VERSION = "3.10.0"

    def __init__(self):
        try:
            import screen_brightness_control as sbc  # noqa: F401
            self._sbc = sbc
            self.available = True
        except Exception:
            self._sbc = None
            self.available = False

    # =========================================================
    # QUERY
    # =========================================================

    def get_brightness(self) -> dict:
        """
        Return current brightness per display and as an
        averaged percentage.
        """

        if not self.available:
            return {
                "success": False,
                "operation": "display.brightness_get",
                "available": False,
                "error": (
                    "Brightness control is not available on "
                    "this machine."
                ),
                "verified": False,
            }

        try:
            values = self._sbc.get_brightness()

            flat = []
            for item in values:
                if isinstance(item, list):
                    flat.extend(int(v) for v in item)
                else:
                    flat.append(int(item))

            if not flat:
                return {
                    "success": False,
                    "operation": "display.brightness_get",
                    "error": "No controllable display was found.",
                    "verified": False,
                }

            average = sum(flat) // len(flat)

            return {
                "success": True,
                "operation": "display.brightness_get",
                "brightness_percent": max(0, min(100, average)),
                "per_display": flat,
                "executed": False,
                "verified": True,
                "post_state_matches": True,
                "verification_type": "display_query",
            }

        except Exception as error:
            return {
                "success": False,
                "operation": "display.brightness_get",
                "error": str(error),
                "verified": False,
            }

    # =========================================================
    # SET
    # =========================================================

    def set_brightness(self, percent, *, direction: Optional[str] = None) -> dict:
        """
        Set brightness to an exact percentage, or step it up or
        down by 10% when `direction` is provided.
        """

        if not self.available:
            return {
                "success": False,
                "operation": "display.brightness_set",
                "available": False,
                "error": (
                    "Brightness control is not available on "
                    "this machine."
                ),
                "executed": False,
                "verified": False,
            }

        before = self.get_brightness()
        current = before.get("brightness_percent") if before.get("success") else None

        if direction is not None:
            normalized = str(direction).strip().lower()

            if normalized not in ("up", "down"):
                return {
                    "success": False,
                    "operation": "display.brightness_set",
                    "error": "Direction must be 'up' or 'down'.",
                    "executed": False,
                    "verified": False,
                }

            base = current if current is not None else 50
            level = base + (10 if normalized == "up" else -10)
            level = max(0, min(100, level))
        else:
            try:
                level = int(percent)
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "operation": "display.brightness_set",
                    "error": "Brightness must be a number between 0 and 100.",
                    "executed": False,
                    "verified": False,
                }

            if not 0 <= level <= 100:
                return {
                    "success": False,
                    "operation": "display.brightness_set",
                    "error": "Brightness must be between 0 and 100.",
                    "executed": False,
                    "verified": False,
                }

        try:
            self._sbc.set_brightness(level)
        except Exception as error:
            return {
                "success": False,
                "operation": "display.brightness_set",
                "target": level,
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        after = self.get_brightness()

        confirmed_levels = after.get("per_display") or []

        verified = bool(
            after.get("success")
            and confirmed_levels
            and all(abs(int(v) - level) <= 1 for v in confirmed_levels)
        )

        return {
            # Item 13D (C7): `success` and `verified` answer DIFFERENT
            # questions and are deliberately not the same field.
            #
            #   success             the call was dispatched and ran
            #   verified            the readback confirmed the level
            #   trustworthy_success may Genesis tell the user it worked
            #
            # This mirrors ActionResult.trustworthy_success, whose
            # docstring states the rule: "A raw execution attempt is NOT
            # enough... Genesis should only expose trustworthy success
            # when the desired final state is known and verified."
            #
            # Before this, a caller that read only `success` saw green
            # for a brightness change the hardware never confirmed. The
            # message already said so, but messages are optional and
            # booleans are not.
            "success": verified,
            "operation": "display.brightness_set",
            "before": current,
            "target": level,
            "after": after.get("brightness_percent"),
            "executed": True,
            "verified": verified,
            # Item 13D: consumers must read THIS, not `success`, to
            # decide whether to tell the user the change took effect.
            "trustworthy_success": verified,
            "verification_type": "display_readback",
            "message": f"Brightness set to {level}%." if verified else (
                "Brightness was set but the readback did not confirm it yet."
            ),
        }
