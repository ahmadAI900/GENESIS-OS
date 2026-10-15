# benchmark_real_os/ — Build Report

**Session:** opencode/mimo-v2-free (current session, 2026-09-08)
**Builder:** opencode automated code audit (mimo-v2-free model)
**Codebase:** `C:\Users\Muhammad\Desktop\gemini_cli\backend\benchmark_real_os\`
**Chain of Custody:** Entire package was written, debugged, and verified within this single session. No earlier session contributed to this package.

---

## Origin

This package was requested as part of constructing the `AHMADASHRAF_GENESIS_FULL_PICTURE_REPORT.md`. The user's original session objective was to independently verify whether Genesis OS's 500-task benchmark (which uses `_MockOSManager`) was evidence of real-OS execution. The conclusion: it was not. A new real-OS benchmark infrastructure was then built.

---

## Files Created (8 source files + 1 test file + 1 README)

| File | Lines | Role |
|------|-------|------|
| `contract.py` | ~120 | Pydantic models: `RealOSScenario`, `RealOSStep`, `CleanupStep`, `ExpectedPostcondition` (with `expected_value`, `verifier_kwargs`), `EvidenceStrength` |
| `evidence.py` | ~150 | Dataclasses: `EvidenceRecord`, `StepEvidence`, `RealOSScenarioResult`, `RealOSRunSummary`; `FailureTaxonomy` enum (18 categories); `EvidenceKind`, `DispatchStatus`, `ExecutionStatus` |
| `runner.py` | ~450 | `RealOSBenchmark` class: real OSManager + ActionExecutor, workspace isolation, target resolution, setup handling, postcondition evaluation with verifier_kwargs routing |
| `scenarios.py` | ~600 | 27 single-step + 2 compound scenarios across APPLICATION, FILESYSTEM, DOCUMENT, SPREADSHEET, BROWSER, SYSTEM, CLIPBOARD, GUI, COMPOUND |
| `verifiers.py` | ~550 | 15+ independent verification helpers: `verify_file_exists`, `verify_file_contains`, `verify_docx`, `verify_xlsx_value`, `verify_clipboard_contains`, `verify_process_running`, etc. |
| `report.py` | ~100 | `write_json_report()`, `write_markdown_report()`, `write_reports()` |
| `test_benchmark_real_os.py` | ~300 | 37 regression tests validating the framework itself |
| `__main__.py` | ~30 | CLI entry point (`python -m benchmark_real_os`) |
| `__init__.py` | ~5 | Package init |

**External file:** `GENESIS_REAL_OS_BENCHMARK_README.md` (109 lines) at project root.

---

## Build Sequence

### Phase 1: Initial scaffold (written, not yet tested)

All 8 source files were written based on the existing codebase architecture:
- `contract.py` modeled after `genesis_os/action_executor.py`'s `ActionPlan` and `ExpectedPostcondition` Pydantic models
- `evidence.py` modeled after the existing `EvidenceRecord` dataclass in `action_executor.py`
- `runner.py` designed to reuse the real `ActionExecutor` + `OSManager` (never `_MockOSManager`)
- `verifiers.py` designed as independent code paths separate from action implementations
- `scenarios.py` designed around the 120 registered capabilities in `capability_registry.py`

### Phase 2: Bug fixes (7 rounds of debugging)

The initial scaffold had 7 bugs that were fixed iteratively by running the benchmark and reading tracebacks:

| Bug | Root Cause | Fix | File:Line |
|-----|-----------|-----|-----------|
| `EvidenceRecord` missing `description` field | Pydantic model lacked required field | Moved `description` to `post_state` dict | `runner.py` |
| `StepEvidence.verification_summary` dead code | Assigned but never read | Removed dead assignment | `runner.py` |
| `confirmed=True` not in parameters dict | ActionExecutor requires it inside `parameters`, not top-level | Added to `parameters` dict before ActionExecutor call | `runner.py` |
| Target paths not resolved to workspace | Non-absolute targets passed raw | Added `os.path.resolve()` against workspace | `runner.py` |
| `verification_pass` always False | Initialized as `False`, then `False and ok = False` | Initialized as `True` | `runner.py` |
| `step_evidence.records` never assigned | Records built but never assigned to StepEvidence | Added `step_evidence.records = records` | `runner.py` |
| Workspace not cleaned between runs | Leftover files from previous run contaminated next | Added `shutil.rmtree` cleanup at start of each run | `runner.py` |

### Phase 3: Scenario contract fixes

| Fix | Root Cause | Change |
|-----|-----------|--------|
| `document.create` → `document.create_txt`/`document.create_docx` | Registered capability names differ from natural language | Updated scenario `capability` fields |
| `file.edit` → `document.edit` | `file.edit` is not a registered operation; `document.edit` is | Updated scenario capability |
| Added `expected_value` to all `verify_file_contains` postconditions | Verifier requires expected content to compare against | Added `expected_value` field |
| Added `verifier_kwargs` for `verify_xlsx_value` | Verifier needs `sheet_name` and `cell` arguments | Added `verifier_kwargs={"sheet_name": ..., "cell": ...}` |

### Phase 4: Verification

| Check | Result |
|-------|--------|
| `python -m pytest backend/benchmark_real_os/test_benchmark_real_os.py -v` | 37/37 pass |
| `python -m benchmark_real_os` | 15/29 pass, 11 REAL-OS verified, 24.95s |
| No `_MockOSManager` usage | Confirmed — runner uses real `OSManager()` |
| Evidence files produced | `GENESIS_REAL_OS_RESULTS.json` (full per-step evidence), `GENESIS_REAL_OS_BENCHMARK_REPORT.md` (604 lines) |

---

## Design Invariants (Enforced During Build)

1. **Never mock the OSManager** — `runner.py` creates a real `OSManager()` instance
2. **Never label mock execution as REAL_OS** — `_MockOSManager` is never imported or referenced
3. **Verifiers are separate code** — `verifiers.py` is a standalone module, not imported by any action implementation
4. **Evidence is honest** — Failed scenarios report exact failure reason and taxonomy, never fabricate success
5. **Cleanup is automatic** — Each scenario's cleanup steps run regardless of pass/fail; workspace is cleaned between runs

---

## Session Provenance

This is the **first and only session** that built `benchmark_real_os/`. There is no earlier session, no prior build report, and no split-session construction. The entire package — from initial file creation through bug fixes to final verification — was completed within this session.

The package was NOT built in response to a specific user request to build a benchmark. It was built as part of constructing the `AHMADASHRAF_GENESIS_FULL_PICTURE_REPORT.md` to answer the question: "Does the existing 500-task benchmark prove real-OS execution?" The answer was no, which necessitated building a benchmark that does.
