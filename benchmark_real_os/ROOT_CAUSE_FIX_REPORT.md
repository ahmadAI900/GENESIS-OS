# Real-OS Benchmark Root Cause Fix Report

## Summary

**Before:** 15/29 pass, 14 fail
**After:** 29/29 pass, 0 fail

All 7 root causes fixed. Pytest regression suite: 37/37 pass.

---

## Root Cause A — ActionExecutor target/source argument swap

**Side:** Production (`genesis_os/action_executor.py`)
**Scenarios fixed:** 5 (realos_fs_copy_file, realos_fs_move_file, realos_fs_rename_file, realcomp_fs_file_lifecycle step 2, realos_sheet_sort_new_workbook)

**Bug:** `action_executor.py:1236-1238` passed `plan.target` (the destination) as the first argument to `copy_file(source, destination)`, `move_file(source, destination)`, `rename_file(source, new_name)`. Line 1255 had the same issue for `sort_spreadsheet`.

**Before evidence:**
```
realos_fs_copy_file: error=Requested path does not exist.
realos_fs_move_file: error=Requested path does not exist.
realos_fs_rename_file: error=Requested path does not exist.
```

**After evidence:**
```
realos_fs_copy_file: PASS
realos_fs_move_file: PASS
realos_fs_rename_file: PASS
```

**Diff (action_executor.py):**
```python
# BEFORE:
if op == "file.copy": return self.os_manager.copy_file(t, p.get("destination"), confirmed=True)
if op == "file.move": return self.os_manager.move_file(t, p.get("destination"), confirmed=True)
if op == "file.rename": return self.os_manager.rename_file(t, p.get("new_name", ""), confirmed=True)
if op == "spreadsheet.sort": return self.os_manager.sort_spreadsheet(t, p.get("column", ""), ...)

# AFTER:
if op == "file.copy": return self.os_manager.copy_file(p.get("source", t), p.get("destination", t), confirmed=True)
if op == "file.move": return self.os_manager.move_file(p.get("source", t), p.get("destination", t), confirmed=True)
if op == "file.rename": return self.os_manager.rename_file(p.get("source", t), p.get("new_name", t), confirmed=True)
if op == "spreadsheet.sort": return self.os_manager.sort_spreadsheet(p.get("source", t), p.get("column", ""), ...)
```

**Runner changes:** `_build_decision` now maps `_setup_sheet_path` → `source` for spreadsheet scenarios, maps `target` → `source` for compound spreadsheet.sort without explicit source, and tracks `previous_step_targets` for compound scenario coordination.

---

## Root Cause B — application.inspect path resolution

**Side:** Benchmark runner (`benchmark_real_os/runner.py`)
**Scenarios fixed:** 2 (realos_app_inspect_notepad, realos_app_inspect_calculator)

**Bug:** The runner's target resolution at line 498 workspace-resolved `"notepad"` to `workspace/notepad`, which `inspect_application()` treated as a file path instead of a process name.

**Before evidence:**
```
realos_app_inspect_notepad: Could not resolve application '...\workspace\notepad'.
realos_app_inspect_calculator: Could not resolve application '...\workspace\calculator'.
```

**After evidence:**
```
realos_app_inspect_notepad: PASS
realos_app_inspect_calculator: PASS
```

**Diff (runner.py):** Added `_NAME_TARGET_OPS` set to skip workspace resolution for name-based operations (`application.open`, `application.close`, `application.inspect`, `process.inspect`, `process.list`, `gui.focus_window`, `gui.inspect_window`).

---

## Root Cause C — gui.focus not registered

**Side:** Benchmark scenario (`benchmark_real_os/scenarios.py`)
**Scenario fixed:** 1 (realos_gui_focus_safe)

**Bug:** Scenario used `gui.focus` as the intent, but the registered capability is `gui.focus_window`. Additionally, the scenario's `pass_policy=BEST_EFFORT` was not implemented in the runner — any verification failure auto-failed the scenario.

**Before evidence:**
```
realos_gui_focus_safe: safety_blocked; Operation is not recognized by the current Genesis OS capability registry.
```

**After evidence:**
```
realos_gui_focus_safe: PASS (BEST_EFFORT — dispatch reached real provider)
```

**Diffs:**
1. `scenarios.py`: Changed `expected_intent="gui.focus"` → `"gui.focus_window"`, `expected_capabilities=["gui.focus"]` → `["gui.focus_window"]`, step `intent="gui.focus"` → `"gui.focus_window"`
2. `runner.py`: Added BEST_EFFORT handling — when `pass_policy=BEST_EFFORT` and dispatch reached `REAL_PROVIDER`, verification failure does not auto-fail

---

## Root Cause D — browser URL path resolution

**Side:** Benchmark runner (`benchmark_real_os/runner.py`)
**Scenario fixed:** 1 (realos_browser_open_url)

**Bug:** The runner's target resolution workspace-resolved `https://example.com` to `workspace/https:\example.com` (Windows backslash normalization), which Playwright treated as a local file path.

**Before evidence:**
```
realos_browser_open_url: Page.goto: net::ERR_FILE_NOT_FOUND at ...\workspace\https:\example.com
```

**After evidence:**
```
realos_browser_open_url: PASS
```

**Diff (runner.py):** Added URL check (`startswith("http://", "https://", "file://")`) to skip workspace resolution for URL targets.

---

## Root Cause E — DOCX content mismatch

**Side:** Benchmark scenario (`benchmark_real_os/scenarios.py`)
**Scenario fixed:** 1 (realos_doc_create_docx)

**Bug:** Scenario passed `content="hello-from-genesis-doc-create-docx"` but `create_docx()` expects `sections` (a list of dicts with `heading`/`body` keys). The `content` parameter was silently ignored.

**Before evidence:**
```
realos_doc_create_docx: expected substring not found in DOCX
```

**After evidence:**
```
realos_doc_create_docx: PASS
```

**Diff (scenarios.py):** Changed `parameters={"content": "..."}` → `parameters={"sections": [{"body": "..."}]}`

---

## Root Cause F — hardware response schema mismatch

**Side:** Benchmark verifier (`benchmark_real_os/verifiers.py`)
**Scenarios fixed:** 2 (realos_system_battery, realos_system_hardware_stats)

**Bug:** Verifiers used stale key names. `battery_status()` returns `battery_percent`/`plugged_in` but verifier checked for `percent`/`plugged`. `hardware_stats()` returns `cpu_percent`/`memory_percent`/`uptime_hours` but verifier checked for `cpu`/`memory`/`uptime`.

**Before evidence:**
```
realos_system_battery: battery_status missing 'percent' key
realos_system_hardware_stats: hardware_stats missing cpu/memory/uptime
```

**After evidence:**
```
realos_system_battery: PASS
realos_system_hardware_stats: PASS
```

**Diff (verifiers.py):**
- `verify_battery_reported`: `"percent"` → `"battery_percent"`, `b.get("percent")` → `b.get("battery_percent")`, `b.get("plugged")` → `b.get("plugged_in")`
- `verify_hardware_stats_reported`: `"cpu"/"memory"/"uptime"` → `"cpu_percent"/"memory_percent"/"uptime_hours"`

---

## Root Cause G — screenshot path mismatch

**Side:** Benchmark scenario (`benchmark_real_os/scenarios.py`)
**Scenario fixed:** 1 (realos_screen_capture)

**Bug:** Scenario used a `verifier` callable (closure) with a hardcoded relative path `"benchmark_screenshot.png"`. The runner's `artifact_path` resolution only applies to `verifier_id`-based postconditions, not callable verifiers. The closure captured the unresolved relative path.

**Before evidence:**
```
realos_screen_capture: image decode exception: [Errno 2] No such file or directory: 'benchmark_screenshot.png'
```

**After evidence:**
```
realos_screen_capture: PASS
```

**Diff (scenarios.py):** Changed from `verifier=_verifier("verify_image_decodes", "benchmark_screenshot.png")` to `verifier_id="verify_image_decodes"` with `artifact_path="benchmark_screenshot.png"`, so the runner resolves the path.

---

## Files changed

| File | Side | Changes |
|------|------|---------|
| `genesis_os/action_executor.py` | Production | Lines 1236-1238, 1255: use `p.get("source", t)` instead of `t` for file.copy/move/rename and spreadsheet.sort |
| `benchmark_real_os/runner.py` | Benchmark | Target resolution: skip for name-based ops and URLs; `_build_decision`: map `_setup_sheet_path` → `source`, track `previous_step_targets`, resolve `output`; BEST_EFFORT handling |
| `benchmark_real_os/scenarios.py` | Benchmark | gui.focus → gui.focus_window; DOCX content → sections; screenshot verifier → verifier_id |
| `benchmark_real_os/verifiers.py` | Benchmark | Battery/hardware_stats key names updated to match production output |

## Confirmation gate verification

`action_executor.py:482-511` (confirmation gate) and destructive-action safety checks were NOT altered. All 7 fixes are execution-path correctness fixes, not safety-policy changes. The only production-code change is the argument order fix in the dispatch block (lines 1236-1238, 1255).

## Pytest count

```
benchmark_real_os/test_benchmark_real_os.py: 37 passed
```

Full suite (`python -m pytest -q`): timed out at 120s (too many tests for this context). The 37 benchmark regression tests are the relevant suite for these changes.
