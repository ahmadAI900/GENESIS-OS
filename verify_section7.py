"""Section 7 verification — debug logging gated."""
import io
import os
import sys
import contextlib

sys.path.insert(0, ".")

# Set up a capture
output_off = io.StringIO()
output_on = io.StringIO()

# 1. WITHOUT GENESIS_DEBUG
os.environ.pop("GENESIS_DEBUG", None)
from memory.memory import MemoryManager
m = MemoryManager()
with contextlib.redirect_stdout(output_off):
    m.learn_preference("I love apples")
    m.learn_profile("My name is Bob")

off_text = output_off.getvalue()
print("=== Without GENESIS_DEBUG ===")
print(f"output length: {len(off_text)}")
print(f"contains [DEBUG]: {'[DEBUG' in off_text}")
assert "[DEBUG" not in off_text, f"FAIL: debug printed even when GENESIS_DEBUG unset: {off_text!r}"
print("PASS: no debug output without GENESIS_DEBUG")

# 2. WITH GENESIS_DEBUG=1
os.environ["GENESIS_DEBUG"] = "1"
# Reload memory to pick up the env (the function is fine since it reads at call time, just verify behavior)
m2 = MemoryManager()
with contextlib.redirect_stdout(output_on):
    m2.learn_preference("I love apples")
    m2.learn_profile("My name is Bob")

on_text = output_on.getvalue()
print("\n=== With GENESIS_DEBUG=1 ===")
print(f"output length: {len(on_text)}")
print(f"contains [DEBUG]: {'[DEBUG' in on_text}")
assert "[DEBUG" in on_text, "FAIL: debug output suppressed even with GENESIS_DEBUG=1"
print("PASS: debug output present with GENESIS_DEBUG=1")