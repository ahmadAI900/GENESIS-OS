"""
Live runtime probe: does 'write hello world' (standalone, Notepad already
open with focus on it) actually dispatch pyautogui.typewrite, or does it
take the requires_runtime_resolution path?
"""
import os
import sys

# Force debug visibility
os.environ["PYTHONUNBUFFERED"] = "1"

sys.path.insert(0, r"C:\Users\Muhammad\Desktop\gemini_cli\backend")

# Patch pyautogui.typewrite to log every invocation before delegating.
import builtins
_real_import = builtins.__import__

def _guarded_import(name, *args, **kwargs):
    mod = _real_import(name, *args, **kwargs)
    if name == "pyautogui" or name.startswith("pyautogui."):
        if hasattr(mod, "typewrite"):
            orig = mod.typewrite
            def _logged(*a, **kw):
                print(f"[PROBE] pyautogui.typewrite CALLED with text={a!r} kwargs={kw!r}")
                return orig(*a, **kw)
            mod.typewrite = _logged
    return mod

builtins.__import__ = _guarded_import

from genesis import GenesisOS

g = GenesisOS()
text = "write hello world"
classification = g.classify(g._resolve_session_reference(text))
print(f"[PROBE] classification={classification}")
resp = g._handle_level3_request(text, classification)
print(f"[PROBE] _handle_level3_request returned: {resp!r}")