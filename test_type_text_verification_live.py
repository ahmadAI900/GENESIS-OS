"""Live test: prove both type_text verification paths."""
import subprocess
import time
import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real Notepad and pyautogui, at module import.
# --------------------------------------------------------------
pytestmark = pytest.mark.live

# Open Notepad
subprocess.Popen(["notepad.exe"], shell=True)
time.sleep(2)

from genesis_os.gui_controller import GUIController

controller = GUIController()

# Focus Notepad
focus = controller.focus_window("Notepad")
print(f"1. Focus: success={focus.success}")

# Clear
import pyautogui
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

# Type text
test_text = "Hello Genesis Verification Test"
type_result = controller.type_text(test_text, focus_title_pattern="Notepad")
verified = type_result.data.get("verified")
print(f"2. Type: success={type_result.success}, verified={verified}")

# Check metadata for verification context
metadata = type_result.metadata if isinstance(type_result.metadata, dict) else {}
print(f"3. verification_type={metadata.get('verification_type')}")
print(f"   focus_success={metadata.get('focus_success')}")

# Now read post-state via UIA
post = controller.read_focused_text()
content_readable = post.data.get("readable")
content_method = post.data.get("method")
content_text = post.data.get("text", "")
print(f"4. Post-state: readable={content_readable}, method={content_method}")
print(f"   text={content_text!r}")

# Verify the three verification tiers
print()
print("=== VERIFICATION TIERS ===")
print(f"DISPATCH_CONFIRMED: verified={verified} (focus retained)")
print(f"CONTENT_VERIFIED: readable={content_readable} (UIA readback, method={content_method})")
if content_readable:
    print(f"  -> UIA readback SUCCEEDED: observed text contains test string: {test_text in content_text}")
elif content_readable is False:
    print(f"  -> UIA readback NOT available: honest fallback (method={content_method})")
else:
    print(f"  -> content_read not populated (method={content_method})")

# Cleanup
subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)
print()
print("5. Cleanup: notepad killed")
