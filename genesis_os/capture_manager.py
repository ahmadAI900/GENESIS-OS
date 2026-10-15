"""
Genesis OS — Level 3.10
Screen Capture.

Full-screen capture through Pillow's ImageGrab (official GDI
copy of the screen), saved under the user's Pictures folder by
default.

Verification is evidence-based: the file must exist, be
non-trivial in size, and open as a real image.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path


class CaptureManager:

    VERSION = "3.10.0"

    MIN_VALID_PNG_BYTES = 1_000

    def __init__(self):
        try:
            from PIL import ImageGrab  # noqa: F401
            self._image_grab = ImageGrab
            self.available = True
        except Exception:
            self._image_grab = None
            self.available = False

    def screenshot(self, path=None) -> dict:
        """
        Capture the screen and save a PNG.

        The result is verified by re-opening the file and
        checking it decodes as an image of non-trivial size.
        """

        if not self.available:
            return {
                "success": False,
                "operation": "screen.capture",
                "available": False,
                "error": "Screen capture is unavailable on this machine.",
                "executed": False,
                "verified": False,
            }

        if path is None:
            directory = Path.home() / "Pictures" / "Genesis Screenshots"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = directory / f"screenshot_{stamp}.png"
        else:
            supplied = Path(str(path))

            if supplied.suffix:
                # A full filename was supplied.
                target = supplied
                directory = supplied.parent
            else:
                # A directory was supplied; generate the filename.
                directory = supplied
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target = directory / f"screenshot_{stamp}.png"

        directory.mkdir(parents=True, exist_ok=True)

        try:
            image = self._image_grab.grab()
            image.save(target, format="PNG")
        except Exception as error:
            return {
                "success": False,
                "operation": "screen.capture",
                "target": str(target),
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        # -----------------------------------------------------
        # EVIDENCE-BASED VERIFICATION
        # -----------------------------------------------------

        try:
            data = target.read_bytes()
        except OSError as error:
            return {
                "success": False,
                "operation": "screen.capture",
                "target": str(target),
                "error": f"The screenshot could not be read back: {error}",
                "executed": True,
                "verified": False,
            }

        decoded_ok = False
        dimensions = None

        try:
            from PIL import Image as _Image

            with _Image.open(target) as check:
                dimensions = check.size
                decoded_ok = True
        except Exception:
            decoded_ok = False

        verified = (
            len(data) >= self.MIN_VALID_PNG_BYTES
            and decoded_ok
        )

        return {
            "success": bool(verified),
            "operation": "screen.capture",
            "path": str(target),
            "size_bytes": len(data),
            "dimensions": list(dimensions) if dimensions else None,
            "sha256": hashlib.sha256(data).hexdigest()[:16],
            "executed": True,
            "verified": bool(verified),
            "verification_type": "image_decode",
            "message": (
                f"Screenshot saved to '{target}'."
                if verified
                else "The captured file could not be verified as a valid image."
            ),
        }
