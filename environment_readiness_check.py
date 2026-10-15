"""
Genesis OS — Environment Readiness Check ("Phase 0.5")

Distinct from PHASE_0_BASELINE_REPORT.md (which measured code behavior).
This script measures the ENVIRONMENT the code runs in: every dependency,
credential, and runtime prerequisite. A missing piece here silently
degrades capabilities without ever raising an exception (exactly how
openpyxl went unnoticed) or silently swaps which AI model actually
answers (the OpenRouter 429 -> Ollama fallback pattern seen in nearly
every prior live test).

Run from inside backend/:
    python environment_readiness_check.py

Produces ENVIRONMENT_READINESS_REPORT.md in the same folder.
"""
import sys
import os
import subprocess
import importlib
import json

REPORT_LINES = []


def log(line=""):
    print(line)
    REPORT_LINES.append(line)


def section(title):
    log(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ---------------------------------------------------------
# 1. Package-level import check (every requirements.txt entry)
# ---------------------------------------------------------
PACKAGES = {
    "openai": "openai",
    "python-dotenv": "dotenv",
    "python-docx": "docx",
    "openpyxl": "openpyxl",
    "python-pptx": "pptx",
    "pypdf": "pypdf",
    "Pillow": "PIL",
    "psutil": "psutil",
    "requests": "requests",
    "langdetect": "langdetect",
    "ddgs": "ddgs",
    "pyperclip": "pyperclip",
    "playwright": "playwright",
    "selenium": "selenium",
    "webdriver-manager": "webdriver_manager",
    "pyautogui": "pyautogui",
    "pytest": "pytest",
}
WINDOWS_PACKAGES = {
    "pywin32": "win32com",
    "comtypes": "comtypes",
    "pycaw": "pycaw",
    "screen-brightness-control": "screen_brightness_control",
}


def check_packages():
    section("1. PACKAGE IMPORT CHECK")
    missing = []
    all_pkgs = dict(PACKAGES)
    if sys.platform == "win32":
        all_pkgs.update(WINDOWS_PACKAGES)

    for display_name, import_name in all_pkgs.items():
        try:
            importlib.import_module(import_name)
            log(f"  [OK]      {display_name}")
        except ImportError as e:
            log(f"  [MISSING] {display_name}  ->  {e}")
            missing.append(display_name)

    if missing:
        log(f"\n  ACTION REQUIRED: pip install {' '.join(missing)}")
    else:
        log("\n  All packages import cleanly.")
    return missing


# ---------------------------------------------------------
# 2. Functional checks — importing is not the same as working
# ---------------------------------------------------------
def check_playwright_binaries():
    section("2a. Playwright browser binaries (functional, not just import)")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                browser.close()
                log("  [OK] Chromium binary launches successfully (headless).")
                return True
            except Exception as e:
                log(f"  [FAIL] Chromium package present but binary not installed/launchable: {e}")
                log("  ACTION REQUIRED: playwright install chromium")
                return False
    except ImportError:
        log("  [SKIP] playwright package itself not installed (see section 1).")
        return False


def check_windows_audio_control():
    section("2b. Windows audio control (pycaw functional check)")
    if sys.platform != "win32":
        log("  [SKIP] Not on Windows.")
        return None
    try:
        from pycaw.pycaw import AudioUtilities
        devices = AudioUtilities.GetSpeakers()
        log(f"  [OK] pycaw can enumerate audio devices: {devices}")
        return True
    except Exception as e:
        log(f"  [FAIL] pycaw imports but cannot enumerate real devices: {e}")
        return False


def check_win32_window_control():
    section("2c. Windows window control (win32gui functional check)")
    if sys.platform != "win32":
        log("  [SKIP] Not on Windows.")
        return None
    try:
        import win32gui
        count = []
        win32gui.EnumWindows(lambda hwnd, _: count.append(hwnd), None)
        log(f"  [OK] win32gui enumerated {len(count)} real windows.")
        return True
    except Exception as e:
        log(f"  [FAIL] win32gui present but non-functional: {e}")
        return False


# ---------------------------------------------------------
# 3. AI backend health — the most important check
# ---------------------------------------------------------
def check_ai_backends():
    section("3. AI BACKEND HEALTH (this determines if quality tests are trustworthy)")
    try:
        from ai.ai_engine import AIEngine
    except ImportError as e:
        log(f"  [FAIL] Could not import AIEngine: {e}")
        return {"ollama": False, "cloud": False}

    engine = AIEngine()
    status = {"ollama": False, "cloud": False, "cloud_error": None}

    # Ollama check
    try:
        result = engine.generate_response("Say OK and nothing else.", force_backend="local") \
            if hasattr(engine, "generate_response") else None
        if result:
            log(f"  [OK] Ollama responded: {str(result)[:80]!r}")
            status["ollama"] = True
    except TypeError:
        # generate_response may not support force_backend kwarg; note and move on
        log("  [INFO] Could not force a local-only call to verify Ollama in isolation "
            "(API doesn't support it) — inspect ai/ai_engine.py's router for a "
            "local-only test path if you want this fully isolated.")
    except Exception as e:
        log(f"  [FAIL] Ollama call raised: {e}")

    # Cloud check — the important one, given the 429 pattern seen repeatedly
    try:
        result = engine.generate_response("Say OK and nothing else.")
        result_str = str(result)
        log(f"  Response received: {result_str[:150]!r}")
        # We can't directly know which backend answered without engine internals;
        # rely on printed [AI Router] lines which this call will emit to stdout.
        log("  >>> CHECK THE CONSOLE OUTPUT ABOVE for [AI Router] lines. <<<")
        log("  >>> If you see 'Falling back to Ollama', cloud is NOT healthy "
            "right now and every 'quality' judgment made during this session "
            "reflects the local fallback model, not your real cloud model. <<<")
    except Exception as e:
        log(f"  [FAIL] AI engine call raised entirely: {e}")

    return status


# ---------------------------------------------------------
# 4. .env presence check (without printing secret values)
# ---------------------------------------------------------
def check_env_file():
    section("4. .env / credentials presence (values redacted)")
    if not os.path.exists(".env"):
        log("  [MISSING] No .env file found in backend/.")
        return
    with open(".env", "r", encoding="utf-8", errors="ignore") as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    for line in lines:
        key = line.split("=")[0] if "=" in line else line
        has_value = "=" in line and len(line.split("=", 1)[1].strip()) > 0
        log(f"  {key} = {'<set>' if has_value else '<EMPTY>'}")


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------
if __name__ == "__main__":
    log(f"Python: {sys.version}")
    log(f"Platform: {sys.platform}")

    missing_pkgs = check_packages()
    playwright_ok = check_playwright_binaries()
    audio_ok = check_windows_audio_control()
    window_ok = check_win32_window_control()
    check_env_file()
    check_ai_backends()

    section("SUMMARY")
    log(f"Missing packages: {len(missing_pkgs)} ({', '.join(missing_pkgs) if missing_pkgs else 'none'})")
    log(f"Playwright browser functional: {playwright_ok}")
    log(f"Windows audio control functional: {audio_ok}")
    log(f"Windows window control functional: {window_ok}")
    log("\nSee console output above for AI backend health — this cannot be "
        "auto-summarized reliably without engine internals, read the "
        "[AI Router] lines directly.")

    with open("ENVIRONMENT_READINESS_REPORT.md", "w", encoding="utf-8") as f:
        f.write("# Genesis OS — Environment Readiness Report\n\n```\n")
        f.write("\n".join(REPORT_LINES))
        f.write("\n```\n")
    log("\nReport written to ENVIRONMENT_READINESS_REPORT.md")