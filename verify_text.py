"""Live verification of type_text content verification paths."""
import time
import subprocess
import ctypes

# Open Notepad
subprocess.Popen(["notepad.exe"], shell=True)
time.sleep(2)

from genesis_os.gui_controller import GUIController
from genesis_os.window_models import WindowResolver

controller = GUIController()
resolver = WindowResolver()

# Find and focus Notepad
win = resolver.find_window(r"Notepad", timeout=5.0)
print(f"Window found: {win is not None}")
if win:
    print(f"  title: {win.title}")
    print(f"  hwnd: {win.hwnd}")

# Focus it
focus = controller.focus_window("Notepad")
print(f"Focus: success={focus.success}")

# Clear content
import pyautogui
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

# Read pre-state
pre = controller.read_focused_text()
print(f"Pre-state: readable={pre.data.get('readable')}, method={pre.data.get('method')}, text={pre.data.get('text')!r}")

# Type text
test_text = "Hello Verification"
result = controller.type_text(test_text, focus_title_pattern="Notepad")
print(f"Type result: success={result.success}")
print(f"  data keys: {list(result.data.keys()) if isinstance(result.data, dict) else 'N/A'}")

# Wait
time.sleep(0.5)

# Read post-state
post = controller.read_focused_text()
print(f"Post-state: readable={post.data.get('readable')}, method={post.data.get('method')}")
print(f"  text: {post.data.get('text')!r}")

# Verify
if post.data.get("readable") and post.data.get("text"):
    observed = post.data["text"]
    if test_text in observed:
        print(f"RESULT: CONTENT_VERIFIED - '{test_text}' found in observed text")
    else:
        print(f"RESULT: CONTENT_MISMATCH - expected '{test_text}' in '{observed}'")
else:
    print(f"RESULT: DISPATCH_CONFIRMED - content not readable via UIA")

# Cleanup — force-kill Notepad (matches production app_manager.py).
# NEVER use WM_CLOSE: it triggers a "Save?" modal on modified
# untitled buffers, and an undissmissed modal can hang the GUI
# stack on subsequent COM/UIA calls.
subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)
