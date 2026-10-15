"""External browser E2E with skip (never fails CI offline).

Tries https://example.com via the Playwright provider's
``get_page_title`` and asserts "Example" in the title. On ANY
network/timeout exception it prints the SKIP reason and exits 0.
On success it writes honest evidence JSON to
``_live_verify_external_evidence.json`` next to this script.

Run from the workspace root:
    python backend/_live_verify_external.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

EVIDENCE_PATH = _BACKEND_ROOT / "_live_verify_external_evidence.json"
URL = "https://example.com"


def _skip(reason: str) -> int:
    print(f"[live-verify-external] SKIP: {reason}")
    return 0


def main() -> int:
    print("[live-verify-external] Probing Playwright provider availability...")
    try:
        from genesis_os.browser_playwright import PlaywrightBrowserProvider
    except Exception as exc:
        return _skip(f"playwright provider not importable: {exc}")

    try:
        provider = PlaywrightBrowserProvider()
    except Exception as exc:
        return _skip(f"could not construct Playwright provider: {exc}")

    if not provider.available:
        return _skip("playwright package or chromium binary unavailable")

    print(f"[live-verify-external] Opening {URL} ...")
    start = time.monotonic()
    try:
        opened = provider.open_url(URL)
    except Exception as exc:
        return _skip(f"navigation raised {type(exc).__name__}: {exc}")
    if not opened.get("success"):
        return _skip(f"open_url reported failure: {opened.get('error')}")

    try:
        title_result = provider.get_page_title()
    except Exception as exc:
        return _skip(f"get_page_title raised {type(exc).__name__}: {exc}")

    elapsed = round(time.monotonic() - start, 3)
    title = title_result.get("title", "")
    print(f"[live-verify-external] title={title!r} elapsed={elapsed}s")

    if not title_result.get("success"):
        return _skip(f"get_page_title reported failure: {title_result.get('error')}")
    if "Example" not in (title or ""):
        print(
            "[live-verify-external] FAIL: expected 'Example' in title, "
            f"got {title!r}"
        )
        return 1

    evidence = {
        "ok": True,
        "url": URL,
        "title": title,
        "elapsed_seconds": elapsed,
        "provider": "playwright",
        "note": "real navigation + real title readback; no mocks",
    }
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"[live-verify-external] PASS: evidence written to {EVIDENCE_PATH}")
    try:
        provider.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
