# HARDENING_LEDGER

Re-baseline inspection of **this** code, performed 2026-10-15.

- **Repository:** `C:\Users\Muhammad\Desktop\gemini_cli\backend`
- **Branch:** `main`
- **Commit inspected:** `3908ee9e9c62d315946e17c9645a19add673d921`
  ("Item 8: arming tests create their own temp .env and run on any clean checkout")
- **Working tree at start of inspection:** clean — 0 modified, 0 untracked.
- **No product code was modified. Nothing was pushed. This file is the only file created.**

A prior inspection existed (`GENESIS_FULL_REPOSITORY_REPORT_2026-10-14.md`), but it was
written against an older tree. Every row below was re-opened and re-read in the current
code; statuses are NOT carried over from the old report.

## Status vocabulary

| Status | Meaning |
|---|---|
| `EXISTS` | The defect described is present in the current code, at the quoted line. |
| `FIXED` | The specific defect no longer exists. Where a prior fix exists, the line shows the code that now prevents it. |
| `DIFFERENT` | The code does something, but not what the prior inspection described. |

---

## Fast gate — both orderings

Command (the repo's own gate, `pytest.ini` documents it as `python -m pytest -m "not live"`):

```
python -m pytest -m "not live" -q --no-header -p no:cacheprovider --tb=line -rf
python -m pytest -m "not live" -q --no-header -p no:cacheprovider -p alt_order_plugin --tb=line -rf
```

| Ordering | passed | failed | skipped | deselected | wall clock |
|---|---|---|---|---|---|
| A — default | 2709 | 0 | 35 | 485 | 352.55s (0:05:52) |
| B — `-p alt_order_plugin` | 2708 | **1** | 35 | 485 | 383.45s (0:06:23) |

The two orderings **do not agree**. The single failure is:

```
FAILED test_browser_degraded_mode.py::test_recovery_after_the_ttl_clears_the_degraded_flag
```

**Pre-existing and unrelated to every item below.** It is an order-dependency in the browser
probe-cache TTL: `test_browser_degraded_mode.py:228` sets the cache TTL with
`monkeypatch.setattr`, but product code `_store_probe_result` assigns `_probe_cache_at`
directly, and `monkeypatch.undo()` at `test_browser_degraded_mode.py:230` therefore reverts
only the test's own setup, not the product's assignment. It is reproducible on the
unmodified baseline commit and is unaffected by anything in this ledger.

### Honest limits of this gate

These numbers cover the **fast tier only**. Stated explicitly so no subset is reported as the
whole:

- **485 tests were deselected** by `-m "not live"` and were **not run**. They require a real
  GUI session, browser, or live provider.
- **35 tests were skipped**. Their reasons were not enumerated in this pass; they include the
  recorder-canary tests (`require -p record_probe --record`) and `test_phase3_precondition_enforcement.py`
  (12, `single-precondition capability`).
- **0 xfail**, **0 xpassed**.
- Collection is **3229** tests; 2744 run in the fast tier.
- The **full** gate (`python -m pytest`, no marker filter) has **not** been run for this ledger.

---

## Ledger

### CRITICAL

| ID | Title | File:line | Status | Severity | Proposed fix (one sentence) |
|---|---|---|---|---|---|
| H-01 | `unwatch_all()` self-deadlocks: it holds a non-reentrant `Lock` and calls `unwatch()`, which re-acquires the same lock | `genesis_os/filesystem_monitor.py:52, 243, 255-257` | EXISTS | Critical | Use `threading.RLock()` for `self._lock` (or inline the pop loop in `unwatch_all`) so the nested acquisition cannot deadlock. |
| H-02 | `action_executor` computes a risk assessment with the browser security context, then discards it — the gate that actually fires never receives the context | `genesis_os/action_executor.py:726` (dead) vs `:357` (used, no context) | EXISTS | Critical | Consume `assessment` at the dispatch gate (or merge it into `early_assessment`) so the `browser.click` signal-word escalation can fire. |
| H-03 | `unified_executor` injects `confirmed=True` itself, pre-approving the very mutation the confirmation gate exists to catch | `genesis_os/unified_executor.py:489` (`setdefault`), also `:666, 691, 738, 843, 860` | EXISTS | Critical | Remove the injection and let the real approval channel/AuthorizationGrant path set authorization. |
| H-04 | `grant_from_consumed_record` re-hashes **caller-supplied** `operation`/`arguments` and never validates them against the record's own `capability_id`/`arguments_hash`, so a consumed approval can be re-pointed at a different operation and target | `genesis_os/authorization_grant.py:154-162` | EXISTS | Critical | Assert `record["capability_id"] == operation` and `record["arguments_hash"] == _approval_arguments_hash(operation, args)` before minting, and refuse otherwise. |
| H-05 | `mint_grant` self-approves: it issues a token and immediately calls `ApprovalStore.approve(...)`, so the grant materialises with no human decision of its own | `genesis_os/approval_channel.py:527-528` | EXISTS | Critical | Remove the unconditional `approve(...)` call and require the human decision captured by `request_approval` to be the only path that approves. |
| H-06 | `_LAST_CONSUMED_APPROVAL` is process-global mutable state shared across concurrent dispatches — a stale or raced record can authorise an unrelated plan | `genesis_os/agent_framework_adapter.py:580-581, 586, 599`, read at `:2609-2612` | EXISTS | Critical | Return the consumed record from `_consume_approval_token` and thread it through per-call instead of stashing it on the module. |

### HIGH

| ID | Title | File:line | Status | Severity | Proposed fix (one sentence) |
|---|---|---|---|---|---|
| H-07 | `APPLICATION_OPERATIONS` is a curated literal and is then immediately overwritten by `CAPABILITIES`, discarding the authored operation set | `genesis_os/action_plan.py:303` (literal at `:266-301`) | EXISTS | High | Delete the `APPLICATION_OPERATIONS = CAPABILITIES` line so the authored set at `:266-301` survives. |
| H-08 | `LockWorkStation()`'s BOOL return value is discarded; `result = True` is hardcoded, so a refused lock still reports `success=True, verified=True` | `genesis_os/workstation_control.py:36-37, 47` | EXISTS | High | Capture the return value (`result = ctypes.windll.user32.LockWorkStation()`) and derive `accepted` from it. |
| H-09 | `json` is not imported at module scope in the providers module; `_generate_native()` references bare `json.dumps`/`json.loads` and will raise `NameError` on any native-tool-call path | `ai/providers.py:437, 451` (function at `:413`); local `import json as _json` only at `:128` | EXISTS | High | Add a module-scope `import json` and use one spelling consistently. |
| H-10 | `network.connect_wifi` writes the Wi-Fi PSK in plaintext into the WLAN profile and marks the connection `verified` solely from the `netsh` exit code, with no post-connection state check | `genesis_os/network_manager.py:52` (in-code TODO at `:50-51`), `:63-64` | EXISTS | High | Store a hashed `keyMaterial`/use `netsh wlan set profileparameter` so the PSK is not written in cleartext, and verify by reading back the connected SSID rather than the exit code. |

### MEDIUM

| ID | Title | File:line | Status | Severity | Proposed fix (one sentence) |
|---|---|---|---|---|---|
| H-11 | `spreadsheet.sort` accepts `.xlsm` but loads with `load_workbook(src)` and saves with `wb.save(dst)` without `keep_vba=True`, so macros are dropped from a macro-enabled workbook | `genesis_os/spreadsheet_manager.py:55, 66` (dispatch at `:29`) | EXISTS | Medium | Pass `keep_vba=True` to `load_workbook` when the suffix is `.xlsm` (and keep it on save). |
| H-12 | The benchmark's OS layer is a mock whose hardcoded `verified=True` is what the verification metric counts, so benchmark verification rates are self-fulfilling | `benchmark/runner.py:105, 121, 190` (acknowledged at `:667, 679`) | EXISTS | Medium | Mark mock-backed results as `verification_type: "mock"` and exclude them from the reported verification metric. |
| H-13 | Long-term memory's `learn_from_turn` is defined but never called anywhere in product code — the learning path is dead code | `memory/long_term_memory.py:437` (only definition; 0 call sites repo-wide) | EXISTS | Medium | Call it from the turn-completion path in the runtime, or delete the method if learning is intentionally not wired up. |
| H-14 | The two arming tests skipped whenever no `.env` existed, so a clean checkout silently ran two fewer checks | `test_genesis_arming.py:95-111` | FIXED | — | No action required; fixed at `3908ee9` — see below. |
| H-15 | The startup banner claimed no approval channel existed, which was untrue | `genesis.py` (startup message region) | FIXED | — | No action required; fixed in `10e34b3` — the message now states the confirmation is recorded as the decision source, **not** as authorisation. |
| H-16 | `GenesisOS` methods were reported nested inside `announce_boundary_state`, which would have made them uncallable | `genesis.py:326` (class); `classify` `:946`, `run_level3` `:1356`, `command` `:2440`, `run` `:3300` | FIXED | — | No action required. AST-verified in the current code: all four are direct members of `GenesisOS`, `announce_boundary_state` does not exist, and **no** method is nested inside another. |
| H-17 | Agent modules that failed to import were skipped silently, leaving a reduced roster with no signal | `agents/agent_discovery.py:26-27, 65, 69, 113, 118` | FIXED | — | No action required; fixed in `10e34b3` — `import_failures`/`init_failures` are recorded by name and printed as `ERROR`, and the startup banner shows `DEGRADED (N failure(s))`. |
| H-18 | `anthropic` was installed and imported by production code but undeclared | `requirements.txt:11`, `requirements.lock.txt:54` | FIXED | — | No action required; fixed in `10e34b3` — `anthropic>=0.116,<1` declared, lockfile pins `anthropic==0.116.0` (268 distributions, 0 unpinned). |
| H-19 | The approval audit log was hardcoded inside the source tree, so running the suite mutated the tree it audits | `genesis_os/approval_channel.py:115-164`; `conftest.py:260-275` | FIXED | — | No action required; fixed in `10e34b3` — `_audit_path()` resolves `$GENESIS_APPROVAL_AUDIT_LOG` then workspace then temp, and **raises** rather than returning any path inside `backend/`. |
| H-20 | A relative or nonexistent workspace root was resolved against whatever CWD the process happened to have, so the effective boundary could differ from the configured one | `genesis_os/workspace_boundary.py` (`workspace_root()`) | FIXED | — | No action required; fixed in `10e34b3` — raises `BoundaryConfigurationError` for relative and nonexistent roots. |
| H-21 | Tests wrote to the production `genesis_os/approval_audit.jsonl` | `test_approval_channel.py:515, 536, 546, 562-597`; `conftest.py:260-275` | FIXED | — | No action required. **Verified in this pass:** all 46 `test_approval_channel.py` tests leave the in-tree log byte-identical (806,371 bytes, mtime `2026-10-14 23:04:52` before and after). |

### LOW

| ID | Title | File:line | Status | Severity | Proposed fix (one sentence) |
|---|---|---|---|---|---|
| H-22 | The in-tree `genesis_os/approval_audit.jsonl` (806 KB, 2,006 entries) still exists as a stale artifact of the pre-fix era | `genesis_os/approval_audit.jsonl` | DIFFERENT | Low | Delete the file; it is untracked and gitignored, so it can never be committed, but its presence invites confusion. |
| H-23 | 384 bare `except Exception:` handlers across the product directories swallow failures, which is what lets defects like H-02 reach production unseen | `genesis_os/`, `ai/`, `agents/`, and 14 other product packages (e.g. `genesis_os/action_executor.py:712-713`) | EXISTS | Low | Narrow the bare handlers to the specific exception each call can raise, and log the rest instead of `pass`. |
| H-24 | `action_executor` extracts live element text from the browser purely to feed the (discarded) risk assessment, doing real I/O for no effect | `genesis_os/action_executor.py:682-724` | EXISTS | Low | Remove the extraction, or wire its result into the gate as part of fixing H-02. |

---

## Notes on verification method

- Findings H-01, H-09 and H-14 were confirmed by **execution**, not inspection alone:
  - H-01: with one watcher registered, `unwatch_all()` blocks permanently — a
    `faulthandler` dump places the blocked thread at `filesystem_monitor.py:243`,
    called from `:257`.
  - H-09: `import ai.providers` then `hasattr(module, "json")` is `False`; an AST
    walk places both bare `json` loads inside `_generate_native()` (def at `:413`).
  - H-14: the two tests were run with the real `.env` temporarily moved aside; both
    **PASSED** rather than skipping.
- H-21 was confirmed by byte-comparing the in-tree log before and after the test run.
- H-22 is `DIFFERENT` rather than `FIXED` because the *behaviour* is fixed (no test writes
  there) while the *file* persists. Its mtime (`2026-10-14 23:04:52`) predates every run in
  this pass, so nothing in this session wrote it.
- **Correction to an earlier statement in this session:** I previously reported the in-tree
  audit log as deleted, based on a `Path.stat()` that raised `FileNotFoundError`. The file is
  present now, with its original timestamps. No test wrote it during this pass. I could not
  establish what restored the timestamps, and am flagging the discrepancy rather than
  asserting a cause.

## Not covered by this pass

- The **live tier** (485 deselected tests) was not exercised.
- The **35 skips** were not individually enumerated.
- The **full** gate was not run.
- Test-quality defects, flaky-test triage, and performance were out of scope.