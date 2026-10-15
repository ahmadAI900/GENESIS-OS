# Phase 2 Second-Batch — Session A: Pre-existing Bug Fixes

Session: **A (bug fixes only)**.
Status: **COMPLETE — 1494/1494 tests pass, no safety regression, no new capabilities wired.**

This is the *preparation* session for the user's second-batch scope. Per explicit instruction, this session does **not** wire `browser.click`, does **not** add the adapter-level risk-tier pre-check, and does **not** wire `file.delete` / `cleanup.empty_recycle_bin` / `application.close`. Those are Session B (next session).

---

## Scope of this session

Per user approval, fixed three categories of pre-existing failures in `test_phase2_agent_framework_adapter_expansion.py`:

1. **Cat A — schema `required` keys** (2 tests): `browser.open_tab`, `browser.close_tab` had `required: []` even though they have meaningful inputs. Fix: add `session_id` to `required` for both.

2. **Cat B — adapter `_build_action_plan` target=None** (12 tests): nine capabilities (`browser.extract`, `browser.get_title`, `browser.get_url`, `browser.switch_tab`, `browser.open_tab`, `browser.close_tab`, `browser.get_tabs`, `browser.select`, `browser.verify`) plus the safety sweep and the two `document.search` / `spreadsheet.sort` cases. Fix: each adapter `_build_action_plan` block now forwards a real `target` — selector for `extract` / `select`, session_id for the rest — derived from the arguments. For `document.search` the operation name itself was wrong (the registry ships it as `document.search_intel`); fixed that too, with one matching addition to `ActionExecutor.SUPPORTED_OPERATIONS` and one matching dispatch entry. For `spreadsheet.sort` the test mock was missing the `sort_spreadsheet` alias that production `OSManager` exposes; added that.

3. **Cat C — `gui.paste_text` stale test** (1 test): the test asserted the provider was called; the post-state-observation contract now requires the runtime focus resolver to refuse implicit-target dispatches when no safe focused window exists. Fix: assert `status in {unresolved_target, confirmation_required, verification_failed}`, `verified is False`, and `provider.calls == []` (the resolver correctly refused the dispatch).

**No changes** to `safety_policy`, the confirmation gate (`action_executor.py:482-511`), `TARGETLESS_OPERATIONS` (`action_plan.py:215-222`), or the executor's pre-safety validation. The user explicitly forbade changes to those.

---

## Test count reconciliation — exact, no estimates

### Before this session

Baseline (just the two Phase 2 test files):

```
test_phase2_agent_framework_adapter.py           : 16 passed
test_phase2_agent_framework_adapter_expansion.py : 15 failed, 57 passed
                                                : 72 collected, 15 failed, 57 passed
COMBINED                                        : 88 collected, 15 failed, 73 passed
```

The 15 failures were the pre-existing issues categorised in `PHASE_2_SECOND_BATCH_EVIDENCE.md` (Cat A 2, Cat B 11+1, Cat C 1) — none of them was a safety_policy misclassification; all were adapter, schema, or test-harness bugs at layers below the gate.

### After this session

```
test_phase2_agent_framework_adapter.py           : 16 passed
test_phase2_agent_framework_adapter_expansion.py : 72 passed
                                                : 72 collected, 0 failed, 72 passed
COMBINED                                        : 88 collected, 0 failed, 88 passed
```

### Full backend suite (after)

```
$ python -m pytest --no-header
====================== 1494 passed in 368.11s (0:06:08) =======================
```

**1494 passed, 0 failed.**

### Safety tests — explicit non-regression check

```
test_phase2_agent_framework_adapter.py::TestAdapterDoesNotBypassSafety::test_no_confirmed_flag_injected_into_any_plan PASSED
test_phase2_agent_framework_adapter_expansion.py::TestExpansionDoesNotBypassSafety::test_no_confirmed_flag_injected_into_any_plan PASSED
```

Both previously-passing safety tests still pass. The expansion safety test (`TestExpansionDoesNotBypassSafety::test_no_confirmed_flag_injected_into_any_plan`) was in the 15-failures set and now passes; this is *not* a regression of a previously-passing test, it is a fix.

### Related test suites — non-regression check

```
test_intent_gate_and_confirmation_prompt.py + test_verification_honesty_sweep.py
+ test_phase1_gui_focus_verification.py + test_level3_4_document_edit_transform_verify.py
= 140 passed in 17.66s
```

The `_RecordingOSManagerExpanded` test mock and the surrounding fixtures were touched (added `sort_spreadsheet` alias, added `session_id` to two test cases), but no public test contract was changed.

---

## Exact code changes (file:line)

### `backend/genesis_os/agent_framework_adapter.py`

| # | Line | Change |
|---|---|---|
| 1 | 804-848 | Cat A: `_ADAPTER_SCHEMAS["browser.open_tab"]` and `["browser.close_tab"]` now declare `"required": ["session_id"]`; description text updated to reflect that the adapter always supplies `session_id` even when the caller omits it. |
| 2 | 1480-1494 | Cat B: `browser.extract` — `target=None` → `target=selector` (selector is the natural primary identifier for the element the action targets). |
| 3 | 1515-1527 | Cat B: `browser.get_title` — `target=None` → `target=session_id`. |
| 4 | 1529-1541 | Cat B: `browser.get_url` — `target=None` → `target=session_id`. |
| 5 | 1543-1557 | Cat B: `browser.switch_tab` — `target=None` → `target=session_id`. |
| 6 | 1559-1572 | Cat B: `browser.open_tab` — `target=None` → `target=session_id`. |
| 7 | 1574-1589 | Cat B: `browser.close_tab` — `target=None` → `target=session_id`. |
| 8 | 1591-1603 | Cat B: `browser.get_tabs` — `target=None` → `target=session_id`. |
| 9 | 1655-1684 | Cat B: `browser.select` — `target=None` → `target=selector or session_id` (selector is the natural primary identifier for the `<select>` element; session_id is the fallback if the caller omits the selector). |
| 10 | 1701-1733 | Cat B: `browser.verify` — `target=None` → `target=session_id`. |
| 11 | 1167-1182 | B1: `document.search` — `operation="document.search"` → `operation="document.search_intel"` (the registered name; the public alias stays attached to the descriptor via `describe_capability`). |

### `backend/genesis_os/action_executor.py`

| # | Line | Change |
|---|---|---|
| 1 | 124 | `SUPPORTED_OPERATIONS` now includes `"document.search_intel"` alongside the legacy `"document.search"`. The Pydantic `ActionPlan.validate()` uses this set to allow operations; both names are now valid. |
| 2 | 1447-1452 | New dispatch branch: `if op == "document.search_intel": return self.os_manager.doc_search(t, p.get("query", ""))`. Comment notes that the legacy `"document.search"` branch above is preserved for backward compatibility. |

### `backend/test_phase2_agent_framework_adapter_expansion.py`

| # | Line | Change |
|---|---|---|
| 1 | 718-747 | B2: new `sort_spreadsheet` method on the mock that records its own `method: "sort_spreadsheet"` call entry and delegates to `sheet_sort`. Mirrors the production `OSManager.sort_spreadsheet` (line 296) which is what the executor's dispatch at `action_executor.py:1255` calls. |
| 2 | 1352 | `_EXPECTED_OSM_METHODS["spreadsheet.sort"]` updated from `"sheet_sort"` to `"sort_spreadsheet"` (matches the executor's actual dispatch target). |
| 3 | 1305-1308 | `browser.open_tab` and `browser.close_tab` test cases now include `session_id: "default"` (the schema now requires it). |
| 4 | 1516-1563 | Cat C: `TestGuiPasteText::test_gui_paste_text_routes_through_real_executor` updated to assert the post-state-observation contract: `status in {unresolved_target, confirmation_required, verification_failed}`, `verified is False`, `provider.calls == []` (the resolver correctly refused the implicit-target dispatch), and `metadata.executor_version == "3.6.0"` (proves the call went through the real executor). |

---

## What was NOT changed (explicit non-changes per user instruction)

- `backend/genesis_os/security_model.py` — risk assessments untouched.
- `backend/genesis_os/action_executor.py:482-511` — confirmation gate untouched.
- `backend/genesis_os/action_plan.py:215-222` — `TARGETLESS_OPERATIONS` untouched (the user explicitly forbade adding browser ops to this set as a shortcut; the real-target fix in the adapter is the correct shape).
- `backend/genesis_os/execution_safety.py` — safety_policy untouched.
- The `ActionPlan.target = None` bug was **not** fixed by adding to `TARGETLESS_OPERATIONS`. Per user: "do not add these operations to TARGETLESS_OPERATIONS as a shortcut; give them real targets instead, since they genuinely have one." Each op now has a real target.

---

## What is intentionally NOT in this session (deferred to Session B)

Per user instruction: "Do NOT proceed to browser.click, the risk-tier pre-check, or the 3 destructive capabilities in this session — that's session B, separate, after this is confirmed clean."

- `browser.click` wiring (the only genuinely-new non-destructive cap)
- Adapter-level risk-tier pre-check (DESTRUCTIVE / HIGH-with-unresolved-target)
- `file.delete`, `cleanup.empty_recycle_bin`, `application.close` (the 3 destructive caps) — with `application.close` only gated when unsaved changes are actually present (real precondition check, not blanket-destructive)
- Any new live-verify scripts

---

## What I learned about the codebase that informs Session B

1. **The executor's safety_policy check is name-strict.** A capability id that exists in the dispatch table but not in the registry's `capability_id` field will be rejected as "not recognized by the current Genesis OS capability registry" (`execution_safety.py:183`). The adapter must use the *registered* operation name, not the public alias. (This bit me once already; Session B must be careful to do the same for any new wires.)

2. **The executor's `ActionPlan.validate()` allowlist (`action_executor.py:85-132`) is a separate gate from the registry.** A capability can be in the dispatch table but not in this allowlist and still be rejected with `invalid_plan`. Session B should always grep `SUPPORTED_OPERATIONS` before adding new ops.

3. **The runtime focus resolver (`action_executor.py:329-344`) refuses to dispatch `gui.type_text` / `gui.paste_text` when no safe focused window exists.** This is the post-state-observation contract — implicit-target GUI text input never produces `verified=True` without real focus observation. Session B should be aware of this for any new wires that might want to use the same path.

4. **The test mock `_RecordingOSManagerExpanded` now mirrors production `OSManager`'s method names exactly** (the `sort_spreadsheet` alias closes the last known gap). Session B can add new mock methods in the same shape.

5. **Confirmation gate (`action_executor.py:482-511`) is unchanged and correctly covers BOTH paths** (CLI text via `_handle_unmatched_request` → executor, and agent-framework tool call via `aexecute_capability` → executor). The user's structural concern — that the adapter should have its own pre-check so destructive ops are visibly distinct from generic failures — remains valid for Session B.
