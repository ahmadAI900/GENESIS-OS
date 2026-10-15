# Phase 2 Second-Batch — Mid-Session Checkpoint Report

Session: Phase 2 second batch (10 capabilities), per user prompt dated this session.
Status: **PAUSED — needs scope clarification before code changes**.

---

## What I did so far (read-only)

1. Read `backend/genesis_os/agent_framework_adapter.py` (2099 lines) in full.
2. Read `backend/test_phase2_agent_framework_adapter.py` (649 lines) in full.
3. Read `backend/test_phase2_agent_framework_adapter_expansion.py` (1675 lines) in full.
4. Read `backend/genesis_os/action_executor.py` confirmation-gate block
   (lines 470–511) and `_confirmation_required_result` (lines 778–794).
5. Read `backend/genesis_os/security_model.py` risk assessments for
   `file.copy` (300), `file.move` (310), `file.delete` (395),
   `application.close` (194), `cleanup.empty_recycle_bin` (464, 523).
6. Read `backend/genesis.py:_handle_unmatched_request` (2656–) to
   understand the CLI confirmation handshake.
7. Ran the existing Phase 2 test files to get a baseline.

## What I have NOT done (waiting on clarification)

- No code changes to the adapter.
- No new tests added.
- No live-verification scripts.
- No new report file beyond this checkpoint.

---

## The Critical Safety Finding (already determined, this is the most important part of the report)

**The confirmation gate DOES cover the agent-framework tool-call path — but only as a passive block, not as a human-in-the-loop cycle. This is a real workflow gap, not a safety breach.**

Path trace:

| Step | CLI text path | Agent Framework tool-call path |
|---|---|---|
| 1. User / model proposes action | `_handle_unmatched_request` (`genesis.py:2656`) | `tool.invoke(arguments=...)` |
| 2. AI resolves capability | `LLMIntentResolver.looks_actionable` (`genesis.py:2701`) → `_describe_operation` | (model already decided; calls tool directly) |
| 3. Confirmation handshake | `_pending_llm_action` stored; waits for "yes" (`genesis.py:2671-2689`) | **None — adapter calls `executor.execute()` immediately** |
| 4. Executor gate | `executor.execute(plan)` → `requires_confirmation(plan.operation)` at `action_executor.py:482` | Same — `adapter.execute_capability` → `self.executor.execute(plan)` at `agent_framework_adapter.py:1909` |
| 5. If `confirmed` flag absent | Returns `confirmation_required` ActionResult (no OS call) | **Same** — also returns `confirmation_required` ActionResult (no OS call) |

So the **safety property holds**: a model-initiated `file.delete` tool call without `confirmed=True` does NOT reach `os_manager.delete_file`. The executor's gate at `action_executor.py:482-511` returns the structured `confirmation_required` ActionResult with `metadata.confirmation_required = True`.

But the **workflow gap the user is asking me to fix is real**:

- The CLI path *pauses for human "yes"* before ever calling `executor.execute()`.
- The agent-framework path calls `executor.execute()` *eagerly* and relies on the executor's gate to bounce it. The model has no structured "please confirm with the user" result type that is clearly distinct from a normal failure — it gets a generic `confirmation_required` failure envelope and would have to re-invoke the same tool with `confirmed=True` to actually do the work.

**The user explicitly asked for an adapter-level pre-check.** Per the prompt:

> "the adapter must not call `ActionExecutor.execute()` directly — it must return a structured 'confirmation required' result to the model ... only proceed to real execution once your test harness (or, in the live-verification step below, the real user) explicitly approves. Do not silently auto-approve for the sake of a clean demo — an unconfirmed destructive action must genuinely not execute."

This requires a **structural change** to the adapter: a risk-tier pre-check that short-circuits *before* `executor.execute()` for DESTRUCTIVE-category or unresolved-target HIGH-risk capabilities, and surfaces a clearly-distinguishable result envelope. Then on the second call with `confirmed=True` set by the runtime, it falls through to `executor.execute()`.

I have the architecture in mind and am ready to implement it. **Awaiting confirmation that this is the interpretation you want** (see "Scope conflicts" below — your prompt also has some items that conflict with the existing code).

---

## Pre-existing test failures (NOT caused by this session, will affect before/after count)

`backend/test_phase2_agent_framework_adapter_expansion.py` has **15 pre-existing failures** from a prior session, all of the same shape: the executor's *safety policy* (stage 4, before the confirmation gate) returns `safety_blocked` for capabilities like `document.search`, `spreadsheet.sort`, `browser.extract`, `browser.get_title`, `browser.get_url`, `browser.switch_tab`, `browser.open_tab`, `browser.close_tab`, `browser.get_tabs`, `browser.select`, `browser.verify`, `gui.paste_text`, and the OSManager method is therefore never called. Example error:

```
AssertionError: OSManager.doc_search was not called for 'document.search'; calls=[]
```

These exist independent of anything I'll do. I will report the **exact before/after counts** including these failures. If you want me to also fix them as part of this session, say so; otherwise I'll leave them and call them out as pre-existing.

Baseline (just the two Phase 2 test files):
- `test_phase2_agent_framework_adapter.py`: 16 tests, 16 passed
- `test_phase2_agent_framework_adapter_expansion.py`: 72 tests, 15 failed, 57 passed
- Combined: **88 collected, 15 failed, 73 passed in 7.09s**

The full backend suite timed out at 5 minutes (Playwright browser tests are slow on Windows). I'll run it with a longer timeout for the final count.

---

## Scope conflicts in the user's prompt

The user's non-destructive list overlaps with the existing `EXPANDED_CAPABILITIES` set:

| User's "new" cap | Status in existing code |
|---|---|
| `file.copy` | **Already wired** in `agent_framework_adapter.py:195, 990-1008, 1716-1731`. Tests at `test_phase2_agent_framework_adapter_expansion.py:1301-1306, 1339, 1384, 1466-1490`. |
| `spreadsheet.inspect` | **Already wired** (line 168, 431-443, 1266-1274, 1364, 1429). |
| `spreadsheet.sort` | **Already wired** (line 170, 464-496, 1290-1309, 1366, 1429). |
| `document.summarize` | **Already wired** (line 163, 335-355, 1193-1205, 1363, 1406). |
| `browser.click` | **Excluded by design**. `agent_framework_adapter.py:68-70` says: "browser.click, browser.type, browser.upload (still honest-fallback-only, pending the provider `element_found` signal fix)". Not registered, not in `EXPANDED_CAPABILITIES`, has no executor dispatch. The user prompt itself says: "Do not re-verify those five — they're done" referring to first batch, but `browser.click` was never in the first batch. |
| `browser.extract_text` | Not registered. Canonical ID is `browser.extract` (already wired in `EXPANDED_CAPABILITIES`). |
| `file.move` | **Already wired** AND the user also lists it in the *destructive* set. It's a MEDIUM-risk MODIFYING operation in the security model (`security_model.py:310`, `requires_confirmation=True` but `risk_level=MEDIUM`, not DESTRUCTIVE). |

The user's destructive set:

| User's destructive cap | RiskAssessment |
|---|---|
| `file.delete` | HIGH, DESTRUCTIVE, `requires_explicit_auth=True` (`security_model.py:395`). Genuinely destructive. |
| `file.move` | MEDIUM, MODIFYING, `requires_confirmation=True` (`security_model.py:310`). Not in DESTRUCTIVE category. |
| `cleanup.empty_recycle_bin` | HIGH, DESTRUCTIVE, `requires_explicit_auth=True` (`security_model.py:464, 523`). Genuinely destructive. |
| `application.close` | MEDIUM, REVERSIBLE, `requires_confirmation=False` (`security_model.py:194`). Reversible by reopening. The user note "only risky if unsaved changes are present — check the existing capability's own precondition logic" — let me check: `OSManager.close_application` and `app_manager.close_application` only call `taskkill /F` (per `agent_framework_adapter.py:71-73` and `app_manager.py:831-976`). There IS no unsaved-changes guard in the existing code. |

---

## Question for the user (single, focused)

Given the four items in the non-destructive list are already wired, and `browser.click` / `browser.extract_text` have canonical/exclusion conflicts, and `file.move` is in both lists:

**Should I (a) treat all 6 of the user's "non-destructive" entries as new wire-ups, re-checking them end-to-end and writing new tests for the previously-broken ones (which would also incidentally fix the 15 pre-existing failures for the in-scope capabilities), and (b) treat the 4 destructive entries as the new wire-ups, applying the new adapter-level risk-tier pre-check before letting them reach `executor.execute()`?**

Or **skip the already-wired ones and only do `browser.click`, `browser.extract_text`, `file.delete`, `cleanup.empty_recycle_bin`, `application.close`** (which contradicts the destructive-set composition since `file.move` is already done)?

I'll wait for your answer before making any code changes.
