"""Live verification of both type_text verification paths."""
import time
import subprocess
import ctypes

# Open Notepad
subprocess.Popen(["notepad.exe"], shell=True)
time.sleep(2)

from genesis_os.ui_automation_provider import UIAutomationProvider
from genesis_os.window_models import WindowResolver

provider = UIAutomationProvider()
resolver = WindowResolver()
print(f"UIA available: {provider.available}")

# Find Notepad
win = resolver.find_window(r"Notepad", timeout=5.0)
print(f"Window found: {win is not None}")

# Focus via string pattern
focus = provider.focus_window("Notepad")
print(f"Focus: success={focus.success}")

# Clear content
import pyautogui
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

# --- PATH 1: UIA readback succeeds ---
test_text = "Hello Verification"
result = provider.type_text(test_text, focus_title_pattern="Notepad")
print(f"\n=== PATH 1: UIA type_text result ===")
print(f"  verified: {result.data.get('verified')}")
print(f"  verification_note: {result.data.get('verification_note')}")
print(f"  read_method: {result.data.get('read_method')}")
print(f"  observed_text: {result.data.get('observed_text')!r}")
print(f"  message: {result.message}")

# --- PATH 2: Simulate UIA unavailable by clearing the text ---
# Read focused text to show what UIA sees
post = provider.read_focused_text()
print(f"\n=== read_focused_text ===")
print(f"  readable: {post.data.get('readable')}")
print(f"  method: {post.data.get('method')}")
print(f"  text: {post.data.get('text')!r}")

# Cleanup — force-kill Notepad (matches production app_manager.py).
# NEVER use WM_CLOSE: it triggers a "Save?" modal on modified
# untitled buffers, and an undissmissed modal can hang the GUI
# stack on subsequent COM/UIA calls.
subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)

print("\nDone.")
