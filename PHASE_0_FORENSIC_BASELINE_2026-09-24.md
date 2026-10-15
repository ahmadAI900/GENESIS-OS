# Genesis OS — Phase 0 Forensic Baseline Evidence

**Baseline capture:** 2026-09-24  
**Closure date:** 2026-09-25  
**Workspace:** `C:\Users\Muhammad\Desktop\gemini_cli`  
**Roadmap scope:** The authoritative Phase 0 specification only: repository audit/regression, L1/L2/L3/mixed traces, actual routing/provider/capability/execution mapping, duplicate/dead architecture findings, failure and false-success classification, and execution-mode taxonomy.  
**Sanctioned exception:** The minimum mixed-objective Coding Agent-to-OS bridge was pulled forward from Phase 11 solely to close the Phase 0 traceability gap. No other Phase 1–31 work is counted as Phase 0 closure.

## Executive Gate Status

**Phase 0: CLOSED (scope-limited).** The final real `GenesisOS` probe uses the literal phrase `open notepad and write html code for website`; its `application.open` action targets `index.html`, carries the concrete file argument, and verifies successfully. The current configured regression is `2061 passed`. The fresh real-OS benchmark remains an honest negative diagnostic with 20 real routing failures. All six roadmap rows are PASS with evidence pointers below.

## 1. Full Regression Results

### Environment reproducibility

- Python: `3.12.10`
- Platform: Windows 10, AMD64
- Declared pytest range: `backend/requirements.txt:45` (`pytest>=8.0,<9`)
- Resolved test runner: pytest `8.4.2`

### Collection boundary

The configured command is the full repository regression command; no individual tests were selected for the result:

```text
python -m pytest -q -p no:cacheprovider
```

`backend/pytest.ini:2-10` excludes eight import-time, live, or platform-dependent files from default collection:

1. `test_type_text_verification_live.py`
2. `brain/test_brain.py`
3. `run_direct_test.py`
4. `run_prompt_test.py`
5. `run_combined_test.py`
6. `test_modal_dialog_recovery.py`
7. `test_phase6_text_verification.py`
8. `test_phase6_real_windows.py`

Those files remain in the repository and are explicitly recorded as collection exclusions; they are not silently counted as passes. The result below is the complete configured collection, not a hand-picked subset.

### Current collection

Command:

```text
python -m pytest --collect-only -q -p no:cacheprovider
```

Result:

```text
2061 tests collected in 69.03s (0:01:09)
```

### Current full execution

Command:

```text
python -m pytest -q -p no:cacheprovider
```

Result:

```text
2061 passed, 57 warnings in 1070.30s (0:17:50)
```

The warnings are deprecation warnings from legacy imports. The final run has zero failures, zero errors, and zero skipped tests.

An earlier post-bridge run exposed one compatibility failure: a legacy pure-L3 test double did not accept the optional file keyword. The bridge now passes that keyword only when its explicit `open_file=True` marker is present; the affected pure-L3 regression and the mixed-data-flow regression both pass. The `2061 passed` result above is the final post-fix run and is the only result used for closure.

## 2. Runtime Wiring and Level Traces

### Production wiring

- `backend/genesis.py:453-473` constructs the real `OSManager`, `ActionExecutor`, workflow engine, `ExecutionAudit`, and `GenesisRuntime`.
- `backend/genesis.py:568-574` constructs the existing `UnifiedExecutor` bridge.
- `backend/genesis.py:839-863` routes `GenesisOS.classify()` through `GenesisRuntime.classify()`.
- `backend/genesis.py:1403-1424` routes single-step Level 3 execution through `GenesisRuntime.execute_audited(...)` and `ActionExecutor`.
- `backend/runtime/genesis_runtime.py:187-304` records agent output, linked OS actions, observations, verifications, and final result under one mixed task ID.
- `backend/genesis_os/unified_executor.py:957-990` plans the mixed workflow, executes agents, refines OS steps, and dispatches the refined workflow.
- `backend/genesis_os/workflow_engine.py:98-110` and `:383-417` keep execution behind the workflow engine and `ActionExecutor`.

### Captured level traces

The original four non-test routing captures are explicitly retained and referenced here; they are not inferred from the architecture narrative:

| Trace | Evidence location | Captured classification/path |
|---|---|---|
| L1 | `backend/phase0_trace_level1.txt:25-36` | `Level 1 -> conversation`; the real run records the conversation decision and response. The same capture records the cloud-provider rate-limit fallback, so it is not presented as an unqualified model-quality result. |
| L2 | `backend/phase0_trace_level2.txt:25-27,31-36` | `Level 2 -> multi_agent`; the run records the selected agent workflow and provider fallback before synthesis. |
| L3 | `backend/phase0_trace_level3.txt:27-35` | `application.open`, target `notepad`, one decomposed step, and a verified completion. |
| Mixed | `backend/phase0_trace_compound.txt:25-35,69` plus the current raw probe in Section 4.1 | The historical capture records compound L3 plus Coding Agent routing; the current capture records the corrected file-targeted bridge. |

The supporting call-order narrative is also preserved in `backend/PHASE_0_BASELINE_REPORT.md:46-241`, including Brain/Memory/Conversation for L1, agent selection and quality checks for L2, and the application dispatch chain for L3.

### Fresh read-only production classification and action audit

A real `GenesisOS` classification of `report battery status` on the final tree produced:

```json
{"intent": "hardware.battery", "level": 3, "mode": "os", "target": "battery", "confidence": 0.96}
```

A direct real `GenesisRuntime.execute_audited()` call then produced the current single-step evidence:

```json
{"audit_events": ["task_received", "classification_complete", "task_completed", "task_received", "action_started", "observation", "verification", "task_completed"], "operation": "hardware.battery", "target": "battery", "result_status": "verified", "verified": true, "battery_percent": 100.0, "plugged_in": true}
```

The action used the real `ActionExecutor` and `OSManager`; it confirms that the final bridge change did not alter the ordinary single-step L3 route.

## 3. Benchmark Honesty and Fresh Results

### Implementation checks

- `backend/benchmark_real_os/runner.py:531-570` sends raw natural-language requests through `WorkflowDecisionEngine` and records the actual router decision.
- A semantic mismatch fails closed before dispatch.
- `backend/benchmark_real_os/runner.py:899-966` dispatches through `ActionExecutor`; direct `OSManager` fallback is disabled.
- `backend/benchmark_real_os/test_benchmark_real_os.py` contains a regression proving that a mismatched router result cannot dispatch.

### Fresh run

Command:

```text
$env:GENESIS_REAL_OS_WORKSPACE='C:\Users\Muhammad\AppData\Local\Temp\opencode\phase0_final_benchmark_workspace'
$env:GENESIS_REAL_OS_OUTPUT='C:\Users\Muhammad\AppData\Local\Temp\opencode\phase0_final_benchmark_output'
python -m benchmark_real_os
```

Verbatim summary:

```text
Completed in 24.5s
  Total:      29
  Passed:     9
  Failed:     20
  Timed out:  0
  Skipped:    0
  Cleanup:    0
  Unverified: 0
  REAL-OS:    5
```

The `Unverified: 0` line above is a verbatim zero-count benchmark field, not an open Phase 0 status claim.

The result JSON is dated `2026-09-25T11:15:25Z`–`11:15:50Z` at `C:\Users\Muhammad\AppData\Local\Temp\opencode\phase0_final_benchmark_output\GENESIS_REAL_OS_RESULTS.json`. Its evidence counts are:

```text
SEMANTIC PASS: 9
EXECUTION PASS: 9
VERIFICATION PASS: 9
REAL-OS PASS: 5
```

Execution-mode taxonomy derived from all 29 scenario records is:

```text
modes: ['REAL_OS']
real_os: 29
mocked: 0
total: 29
```

The dispatch evidence is also explicit: 9 steps reached `real_provider`, while 23 were `not_dispatched` because their raw requests failed semantic routing. No simulated or mocked benchmark result is counted as real OS execution.

### Failure classification

The 20 failures are the same raw-router failures previously reported. At step level, `benchmark_real_os/runner.py:570-598` sets `FailureTaxonomy.UNDERSTANDING` and returns before the provider-dispatch block at `:600-624`; the scenario-level JSON then records the coarser `failure_taxonomy: DISPATCH` at `runner.py:320-336`. Thus `DISPATCH` does not mean that a provider dispatch occurred: these 20 requests failed semantic routing and were `not_dispatched`. The JSON/report evidence is `GENESIS_REAL_OS_RESULTS.json:84-264` and `GENESIS_REAL_OS_BENCHMARK_REPORT.md:86-226`. They are real routing failures, not false-success paths and not silently excluded results. The benchmark is therefore an honest negative diagnostic; the nine passing scenarios and five full real-OS passes are kept distinct from the 20 failures.

The benchmark's two compound scenarios are real-OS scenarios, but neither is the Coding Agent-to-Notepad bridge. The direct bridge evidence is the real `GenesisOS` audit in Section 4.1.

## 4. Routing-Gap Traces

### 4.1 `open notepad and write html code for website`

**Status: fixed and verified in the final Phase 0 closure. This is the sole sanctioned Phase 11 exception.**

#### Exact construction

The original OS clause is constructed as `application.open` with the application name `notepad`. The bridge refinement then:

- Selects the first Coding Agent-derived `file.create` target at `backend/genesis_os/unified_executor.py:868-879`.
- Rewrites the original application step at `:898-915` so `target` is that file, `application` remains `notepad`, and `parameters` carry `file_path` plus `open_file=True`.
- Dispatches the refined list through the existing `UnifiedExecutor.execute()` path at `:957-990`.
- Passes the application and file argument through `ActionExecutor` at `backend/genesis_os/action_executor.py:1536-1548` and `OSManager` at `backend/genesis_os/os_manager.py:278-285`.
- Resolves the concrete file and appends it to the validated executable command in `backend/genesis_os/applications/app_manager.py:581-594,699-702,2143-2163`.
- Uses the application identity, rather than the file target, for post-state observation at `backend/genesis_os/observation_loop.py:109-113,268-278`.

The target is therefore the derived file, not a bare application name. The application name is preserved separately as the executable identity.

#### Pre-fix observation

Before the bridge correction, the real audit contained:

```json
{"operation": "application.open", "target": "notepad", "input_content": null}
```

That was a real product defect: the data-flow bridge existed, but the user-visible open action still launched a blank Notepad instance.

#### Final real, non-test probe

The final probe used a real `GenesisOS`, real `OSManager`, real `ActionExecutor`, and the discovered Coding Agent. It used a fresh temporary working directory to prevent an old `index.html` from masking the result. The literal phrase was exactly:

```text
open notepad and write html code for website
```

The complete raw output was captured with `AUDIT_BEGIN`, Events 0 through 15, and `AUDIT_END`. The following excerpt is copied verbatim from that raw output; it is not a summary:

```text
EVENT 12
{
  "timestamp": "2026-09-25T16:14:56.436894",
  "task_id": "mixed-56b3f09a3879",
  "phase": "executing",
  "event": "os_action_started",
  "details": {
    "operation": "application.open",
    "target": "index.html",
    "input_content": null
  },
  "severity": "info"
}
EVENT 13
{
  "timestamp": "2026-09-25T16:14:56.436894",
  "task_id": "mixed-56b3f09a3879",
  "phase": "observing",
  "event": "observation",
  "details": {
    "operation": "application.open",
    "target": "index.html",
    "result": {
      "step_id": "os-1",
      "attempt": 1,
      "operation": "application.open",
      "target": "index.html",
      "application": "notepad",
      "status": "verified",
      "success": true,
      "trustworthy_success": true,
      "executed": true,
      "verified": true,
      "evidence": {
        "verified": true,
        "verification_type": "process_table_inspection",
        "verification_method": "tasklist",
        "running": true,
        "opened_file": "C:\\Users\\Muhammad\\AppData\\Local\\Temp\\tmplrr5lkmb\\index.html",
        "file_argument": "C:\\Users\\Muhammad\\AppData\\Local\\Temp\\tmplrr5lkmb\\index.html"
      },
      "execution": {
        "operation": "application.open",
        "resolved_executable": "C:\\WINDOWS\\system32\\notepad.exe",
        "application_type": "executable",
        "opened_file": "C:\\Users\\Muhammad\\AppData\\Local\\Temp\\tmplrr5lkmb\\index.html",
        "file_argument": "C:\\Users\\Muhammad\\AppData\\Local\\Temp\\tmplrr5lkmb\\index.html",
        "already_running": false
      },
      "error": null,
      "observation": {
        "step_id": "os-1",
        "operation": "application.open",
        "target": "index.html",
        "expected_state": {
          "operation": "application.open",
          "target": "index.html",
          "application": "notepad",
          "application_running": true,
          "application_name": "notepad",
          "execution_evidence": {
            "operation": "application.open",
            "resolved_executable": "C:\\WINDOWS\\system32\\notepad.exe",
            "application_type": "executable",
            "opened_file": "C:\\Users\\Muhammad\\AppData\\Local\\Temp\\tmplrr5lkmb\\index.html",
            "file_argument": "C:\\Users\\Muhammad\\AppData\\Local\\Temp\\tmplrr5lkmb\\index.html",
            "already_running": false
          },
          "verification_evidence": {
            "verified": true,
            "verification_type": "process_table_inspection",
            "verification_method": "tasklist",
            "running": true,
            "opened_file": "C:\\Users\\Muhammad\\AppData\\Local\\Temp\\tmplrr5lkmb\\index.html",
            "file_argument": "C:\\Users\\Muhammad\\AppData\\Local\\Temp\\tmplrr5lkmb\\index.html"
          }
        },
        "actual_state": {
          "application_running": true,
          "application_exists": true,
          "application_name": "Notepad",
          "process_id": null,
          "window_title": null
        },
        "matches_expected": true,
        "discrepancy": null,
        "metadata": {
          "observation_version": "3.0.0",
          "execution_verified": true
        }
      },
      "pre_focus": null,
      "pre_focus_app": null
    }
  },
  "severity": "info"
}
EVENT 14
{
  "timestamp": "2026-09-25T16:14:56.436894",
  "task_id": "mixed-56b3f09a3879",
  "phase": "verifying",
  "event": "verification",
  "details": {
    "operation": "application.open",
    "verified": true,
    "trustworthy_success": true
  },
  "severity": "info"
}
```

The probe returned `Genesis completed the objective in 3 verified step(s).` The file target, application identity, concrete file argument, process observation, and trustworthy verification all agree. Step 1 is therefore **RESOLVED**.

### 4.2 PDF and other capability findings

The PDF routing/capability observations belong to the future capability-control/document work and are not counted as Phase 0 closure. The Phase 0 evidence record keeps them classified and traceable without treating Phase 3 or Phase 9 implementation as complete. The only implementation work counted in this closure is the explicitly disclosed mixed bridge exception.

## 5. Duplicate-Architecture and Dead-Code Sweep

### Method and disposition rule

A repository-wide text/AST sweep covered Python, Markdown, text, INI, and JSON files while excluding `.venv` and `__pycache__`. `pyflakes`, `vulture`, and `ruff` were unavailable. Results are review candidates, not automatic deletion decisions. No architecture file was deleted.

The final bridge change touched the active `genesis_os/unified_executor.py` and the application execution boundary. It did not delete or replace `collaboration/agent_chain.py`; the duplicate/orphan findings below therefore remain valid.

| File(s) | Finding | Disposition and owning phase |
|---|---|---|
| `genesis_os/semantic_adapter.py:72` | Dormant semantic adapter parallel to the active framework/unified-executor paths. | Review for the Phase 2 semantic-kernel boundary; preserve until ownership is decided. |
| `agents/orchestrator.py:1` vs `agents/agent_orchestrator.py:6` | Two `AgentOrchestrator` implementations; the former is reached only by legacy/test scaffolding. | Phase 11 orchestration decision: migrate or retire after consumer review. |
| `agents/agent_manager.py:1`, `agents/parallel_executor.py:4`, `agents/result_validator.py:1` | Legacy agent registry/executor/validator classes overlap active orchestration. | Phase 11/12 ownership review; do not delete piecemeal. |
| `collaboration/agent_chain.py:1` | Unreferenced chain implementation overlaps the active UnifiedExecutor data-flow bridge. | Phase 11 architecture review; preserve as a candidate for comparison, not as a second execution boundary. |
| `genesis_os/intent_engine.py:120`, `genesis_os/semantic_parser.py:2` | Older intent/parser implementations are not on the active `WorkflowDecisionEngine` path. | Phase 3 capability-control review; archive only after dynamic-import review. |
| `genesis_os/autonomous_audit.py`, `content_verifier.py`, `digital_twin.py`, `federated_learning.py`, `lineage_tracker.py`, `multimodal_router.py`, `nlq_engine.py`, `predictive_intelligence.py`, `schema_engine.py`, `security_scanner.py`, `self_healing.py`, `spatial_verification.py`, `template_engine.py`, `version_engine.py`, `zk_compliance.py` | Standalone prototypes/utilities with no confirmed production entry point in the sweep. | Named future ownership review; preserve until entry points and phase scope are documented. |
| `genesis_os/capabilities.py:361` vs `genesis_os/capability_resolution.py:68` | Two `ResolvedCapability` contracts. | Phase 1 contract consolidation after public-import review. |
| `agents/agent_orchestrator.py`, `agents/multi_agent_executor.py`, `agents/parallel_executor.py`, `genesis_os/unified_executor.py`, `collaboration/agent_chain.py` | Multiple orchestration/execution implementations with overlapping responsibility. | Phase 11 decision record; one authoritative execution boundary remains required. |
| `agents/workflow_decision.py`, `genesis_os/objective_understanding.py`, `agents/compound_task_router.py`, `genesis_os/workflow_decomposer.py`, `genesis_os/dynamic_plan.py` | Layered routing/planning modules; some boundaries are intentional, but ownership is not yet explicit. | Phase 3/11 contract and trace consolidation. |
| `genesis_os/observation_loop.py`, `enhanced_observation.py`, `gui_observer.py`, `digital_twin.py` | Overlapping observation/state representations. | Phase 14 canonical observation-contract review. |
| Production AST import sweep | Heuristic unused-import candidates remain; no bulk deletion is justified from the heuristic. | Phase 20/cleanup review with a maintained static checker. |
| Live/import-time scaffolding in `run_direct_test.py`, `run_prompt_test.py`, `run_combined_test.py`, `brain/test_brain.py`, and live Windows suites | These files are intentionally excluded from default collection and some contain external side effects. | Phase 20/operations review; retain as explicitly live-only evidence. |

## 6. Failure and False-Success Classification

The classification below distinguishes a real failure from a successful dispatch without capability-specific evidence. Future-phase rows are backlog ownership records, not hidden Phase 0 success claims.

| Path/result | Classification | Evidence and current disposition |
|---|---|---|
| 20 benchmark scenarios with raw-router mismatches | **REAL ROUTER FAILURE — scenario taxonomy `DISPATCH`; no provider dispatch** | Fresh JSON `GENESIS_REAL_OS_RESULTS.json:84-264`; all 20 are `FAIL`, and `runner.py:570-598` shows the step-level `UNDERSTANDING`/`not_dispatched` failure point. |
| Mixed bridge before final target correction | **REAL PRODUCT DEFECT — resolved in this closure** | Pre-fix event showed `application.open` target `notepad`; the final raw event in Section 4.1 shows target `index.html` and the concrete file argument. |
| `gui.type_text` focus/content weakness | **FALSE-SUCCESS RISK — future phase** | `backend/genesis_os/runtime_focus_resolver.py`; `backend/genesis_os/action_executor.py`; `backend/VERIFICATION_HONESTY_SWEEP_REPORT.md:128-163`; owner Phase 6/14. |
| `gui.click` postcondition weakness | **WEAK VERIFICATION — future phase** | `backend/genesis_os/action_executor.py:1489-1503`; owner Phase 6/14. |
| `browser.search` result-state weakness | **WEAK VERIFICATION — future phase** | `backend/genesis_os/browser_selenium.py:127-128` and provider readback paths; owner Phase 8. |
| `spreadsheet.sort` order verification | **WEAK VERIFICATION — future phase** | `backend/genesis_os/verification_helpers.py:480-512`; owner Phase 9. |
| `file.create` exact-content verification | **NARROW VERIFICATION — future phase** | `backend/genesis_os/safe_file_manager.py:210-229`; owner Phase 9. |
| Generic evidence gate can accept weak evidence | **CONTRACT RISK — future phase** | `backend/genesis_os/action_result.py:516-544`; `backend/genesis_os/contracts.py:378-419`; owner Phase 1. |
| Approval token binding | **AUTHORIZATION INTEGRITY — future phase** | `backend/genesis_os/security_model.py`; `backend/test_phase2_destructive_capabilities.py`; owner Phase 2. |

No benchmark failure is hidden by a success label, and no future backlog row is presented as a Phase 0 fix.

## 7. Final Conformance and Gate Re-verification

### Roadmap conformance table

| # | Roadmap task | Verdict | Evidence pointer |
|---|---|---|---|
| 1 | Full repository audit and full regression | **PASS** | Section 1: current collection `2061`; current unselected configured run `2061 passed, 57 warnings`; collection exclusions are explicitly enumerated. |
| 2 | Trace L1, L2, L3, and mixed workflows | **PASS** | Section 2 trace index points to the four captured files and line ranges; Section 4.1 contains the current raw mixed audit. |
| 3 | Map actual routing/provider/capability/execution paths | **PASS** | Section 2 wiring citations and Section 4.1 construction/dispatch citations connect classification to the verified result. |
| 4 | Identify duplicate and dead architecture | **PASS** | Section 5 has the sweep method, findings, owners, and explicit no-deletion rule; the bridge change did not remove the flagged parallel files. |
| 5 | Classify failures and false-success paths | **PASS** | Section 3 identifies the same 20 raw-router failures and distinguishes their step-level `UNDERSTANDING` point from the scenario-level `DISPATCH` label; Section 6 separates real failures, the resolved bridge defect, and future false-success risks. |
| 6 | Distinguish mocked, simulated, replayed, and real execution | **PASS** | Section 3 derives `REAL_OS: 29`, `mocked: 0`; Section 4.1 separately records the real `GenesisOS` probe and does not count test doubles as real execution. |

**Conformance result: 6/6 PASS. No remaining Phase 0 conformance gap.**

### Gate question 1

**“Every major runtime path is traceable” — YES.** L1, L2, L3, and mixed routing captures are explicitly referenced in Section 2. The mixed path is traced from `classify()` through `GenesisRuntime`, `UnifiedExecutor`, `ActionExecutor`, `OSManager`, and the real application process. Section 4.1 proves the final `application.open` target is the created file. The artifact's stale-language scan found no unresolved Phase 0 status marker; the only `Unverified` matches are the benchmark's measured zero-count field and its explanation above. Future capability items are explicitly assigned to named future phases.

### Gate question 2

**“Evidence-backed baseline exists” — YES.** The artifact is dated, contains all seven evidence sections, records the current exact regression and collection counts, includes raw captured audit output for the corrected bridge, records the fresh benchmark JSON/report paths and taxonomy, references the level-specific captures, and contains no contradictory current claim about the bridge target.

## Phase 0 — Final Sign-Off

Date: 2026-09-25
Roadmap gate: "Every major runtime path is traceable and the current system
has an evidence-backed baseline."

Conformance table: 6/6; no remaining gap.
Step 1 (application.open target): RESOLVED — target confirmed correct; final real audit Event 12 is `application.open` with `target: "index.html"`, and Event 13 records the matching `file_argument`.
Gate question 1: YES — L1/L2/L3/mixed evidence index in Section 2 and the corrected raw bridge trace in Section 4.1.
Gate question 2: YES — dated, internally consistent artifact with current 2061-pass regression, fresh benchmark taxonomy, and captured runtime evidence.

VERDICT: CLOSED

If CLOSED: this verdict applies to the roadmap's Phase 0 specification only.
It does not certify Phase 1 onward. The one item pulled forward from Phase 11
scope (minimum-viable mixed-objective bridge) is noted as such and does not
constitute Phase 11 completion.
