"""Direct test: what does UIA actually read from Notepad after typing?"""
import subprocess
import time
import ctypes

# Open Notepad
subprocess.Popen(["notepad.exe"], shell=True)
time.sleep(2)

from genesis_os.gui_controller import GUIController

controller = GUIController()

# Focus
focus = controller.focus_window("Notepad")
print(f"Focus: {focus.success}")

# Clear
import pyautogui
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

# Read pre-state
pre = controller.read_focused_text()
print(f"Pre-state: readable={pre.data.get('readable')}, method={pre.data.get('method')}, text={pre.data.get('text')!r}")

# Type
test_text = "Hello Genesis"
type_result = controller.type_text(test_text, focus_title_pattern="Notepad")
print(f"Type: success={type_result.success}, verified={type_result.data.get('verified')}")

# Wait
time.sleep(0.5)

# Read post-state
post = controller.read_focused_text()
print(f"Post-state: readable={post.data.get('readable')}, method={post.data.get('method')}")
print(f"  text={post.data.get('text')!r}")
print(f"  element_name={post.data.get('element_name')!r}")
print(f"  title={post.data.get('title')!r}")

# Also try via UIAutomationProvider directly
from genesis_os.ui_automation_provider import UIAutomationProvider
provider = UIAutomationProvider()
uia_read = provider.read_focused_text()
print(f"\nDirect UIA read: readable={uia_read.data.get('readable')}, method={uia_read.data.get('method')}")
print(f"  text={uia_read.data.get('text')!r}")

# Cleanup — force-kill Notepad (matches production app_manager.py).
# NEVER use WM_CLOSE here: it triggers a "Save?" modal on modified
# untitled buffers, and if that modal is not dismissed the GUI stack
# can hang indefinitely on subsequent COM/UIA calls.
subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)
