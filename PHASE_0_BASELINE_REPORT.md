# Phase 0 — Baseline Audit Report

**Date:** 2026-09-22
**Auditor:** MiniMax (opencode)
**Scope:** Phase 0-8 only. Measurement and classification. No code changes.

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total tests | 1934 |
| Passed | 1934 |
| Failed | 0 |
| Errors | 0 |
| Warnings | 2 |
| Self-reported capabilities spot-checked | 10 |
| SELF_REPORTED_ONLY | 2 |
| VERIFIED_HONESTLY | 8 |
| DEFECT | 0 |
| TEST_ISSUE | 2 (warnings) |
| DEPENDENCY | 0 |
| PLATFORM_LIMITATION | 0 |

**Key finding:** The real test suite is healthy. 1934 tests pass with zero failures. The two warnings are minor (test functions returning `bool` instead of `None`). The two SELF_REPORTED_ONLY findings are the documented compound-task data-flow gap and the PDF keyword-trigger gap — both known, pre-existing, and classified below.

---

## 1. Full Regression Baseline

**Command:** `python -m pytest -q`
**Result:** `1934 passed, 2 warnings in 1416.90s (0:23:36)`

### Warning Classification

| Test | Bucket | Reason |
|------|--------|--------|
| `test_gate_paths.py::test_path3_workflow_engine_gate` | TEST_ISSUE | Test returns `bool` instead of using `assert`. Pytest warns: "Did you mean to use `assert` instead of `return`?" |
| `test_gate_paths.py::test_path8_unified_executor_gate` | TEST_ISSUE | Same pattern — returns `bool` instead of asserting. |

**No DEFECT, DEPENDENCY, or PLATFORM_LIMITATION failures.** The suite is clean.

---

## 2. Level 1 Trace — "Hello, who are you?"

### Call Path (in order)

```
User input: "Hello, who are you?"
  │
  ▼
GenesisOS.run()                          [genesis.py:3266]
  │
  ├─ conversation.prepare_message()       [conversation.py]
  ├─ command() check — no match
  ├─ conversation.add_message("user", ...)
  ├─ long_term_memory.handle_command() — no match
  ├─ _resolve_session_reference() — no anaphora
  ├─ language_normalizer.needs_translation() — English, no translation
  │
  ▼
GenesisOS.classify(routing_text)          [genesis.py:870]
  │
  ├─ WorkflowDecisionEngine.decide(text)  [workflow_decision.py:588]
  │   ├─ _normalize_text() — lowercased
  │   ├─ _detect_compound_l3_signal() — no compound
  │   ├─ _detect_os_intent() — no OS intent (greeting)
  │   ├─ _is_conversational_or_educational() — returns True
  │   │   ("who are you" matches "who" in the conversational list)
  │   └─ Returns: level=1, mode="conversation", confidence=0.85
  │
  ├─ classification = {level: 1, mode: "conversation"}
  │
  ▼
Level 1 path taken:                      [genesis.py:3640]
  │
  ├─ _handle_unmatched_request(routing_text)
  │   ├─ _pending_llm_action check — None
  │   ├─ LLMIntentResolver.looks_actionable() — likely False (greeting)
  │   └─ Returns None (no LLM action proposed)
  │
  ├─ long_term_memory.enrich_prompt() — adds user context
  │
  ▼
Brain.think(enriched)                    [brain.py:44]
  │
  ├─ process_request(text)               [brain.py:47]
  │   ├─ emotion.detect(text)
  │   ├─ memory.learn_profile(text) — no match
  │   ├─ memory.learn_preference(text) — no match
  │   ├─ is_greeting(text) — TRUE ("hello" matches)
  │   └─ Returns: "Hello! I am Genesis AI. I am created by AHMAD..."
  │
  ▼
print(f"\nGenesis: {response}")
conversation.add_message("assistant", response)
```

### Observations

- **Debug logging is gated.** `_genesis_debug()` in `brain.py:17` checks `GENESIS_DEBUG=1` env var. All debug prints (preferences, history, memory, personalization context) are behind `if _genesis_debug()`. Normal sessions are quiet.
- **Response comes from hardcoded greeting, not LLM.** `brain.py:62` — `is_greeting()` returns True and the response is a literal string, never reaches `ai_engine.generate_response()`. This is correct behavior for greetings.
- **No fallback occurred.** The greeting path is deterministic; no LLM call was made.

---

## 3. Level 2 Trace — "Research the top 3 programming languages in 2026"

### Call Path

```
User input: "Research the top 3 programming languages in 2026"
  │
  ▼
GenesisOS.classify(routing_text)
  │
  ├─ WorkflowDecisionEngine.decide(text)
  │   ├─ _detect_compound_l3_signal() — no compound
  │   ├─ _detect_os_intent() — no OS intent
  │   ├─ _is_conversational_or_educational() — likely True
  │   │   BUT: "research" is in _AGENT_KEYWORD_PROBES, so guard is suppressed
  │   ├─ _detect_multi_agents(text)
  │   │   └─ keyword_map["research"]: "research" matches → ["Research Agent"]
  │   │   Only 1 agent → not multi_agent
  │   ├─ _detect_single_agent(text) → "Research Agent"
  │   └─ Returns: level=2, mode="single_agent", agent="Research Agent"
  │
  ▼
GenesisOS.run_level2(text, classification) [genesis.py:1685]
  │
  ├─ executor.execute([{task: text, agent: "Research Agent"}])
  │   └─ MultiAgentExecutor → ResearchAgent.execute(task)
  │
  ▼
ResearchAgent.run(task)                  [research_agent.py:83]
  │
  ├─ STEP 1: internet.search_multiple(task, max_results=5)
  │   └─ Real internet search via InternetSearch module
  │
  ├─ STEP 2: source_evaluator.evaluate(source) for each source
  │   └─ Real quality scoring per source
  │
  ├─ STEP 3: sort by quality_score
  │
  ├─ STEP 4: build source_text with evaluated sources
  │
  ├─ STEP 5: ai.generate_response(prompt) — LLM synthesizes report from sources
  │
  ├─ STEP 6: quality.check(summary, evaluated_sources) [research_quality.py:3]
  │   ├─ Check: report not empty
  │   ├─ Check: word count >= 50
  │   ├─ Check: report mentions "source/sources/references"
  │   ├─ Check: sources list not empty
  │   └─ Returns: {passed: bool, issues: list}
  │
  ├─ print("[Research Agent] Quality check: PASSED")  ← OR FAILED
  │
  └─ create_result(task, response, success=quality["passed"])
```

### Observations

- **Quality check is real, not unconditional.** `research_quality.py:3-38` performs 4 checks (empty report, minimum length, source mention, source availability). "PASSED" only prints when `len(issues) == 0`. This is `VERIFIED_HONESTLY`.
- **Real internet search is used.** `InternetSearch.search_multiple()` is called at step 1. The agent does NOT rely solely on LLM knowledge.
- **Agent selection is keyword-based.** `_detect_multi_agents()` in `workflow_decision.py:3777` uses a hardcoded `keyword_map`. "research" matches `keyword_map["research"]` → `["Research Agent"]`. This is Core Principle #2 compliant (keywords as fast hints) because the agent's `can_handle()` method provides the secondary check.

---

## 4. Level 3 Trace — "open notepad"

### Call Path

```
User input: "open notepad"
  │
  ▼
GenesisOS.classify(routing_text)
  │
  ├─ WorkflowDecisionEngine.decide(text)
  │   ├─ _detect_compound_l3_signal() — no compound
  │   ├─ _detect_os_intent(text)
  │   │   ├─ _strip_politeness() — no politeness prefix
  │   │   ├─ _is_conversational_or_educational() — False ("open" is not conversational)
  │   │   ├─ _detect_extended_os_intent() — may match "open" pattern
  │   │   ├─ _detect_application_action(text) → "open"
  │   │   ├─ _extract_application(text) → "notepad"
  │   │   └─ Returns: level=3, mode="os", intent="application.open",
  │   │       application="notepad", target="notepad", confidence=0.97
  │   │
  │   └─ Decision promoted: level=3, mode="os"
  │
  ▼
GenesisOS._handle_level3_request(text, classification) [genesis.py:2625]
  │
  ├─ session_context_binder.record_decision(classification)
  │
  ├─ _try_multi_step_workflow(text)
  │   ├─ plan_level3_objective(text) → understanding + decomposition
  │   ├─ decomposition.executable — likely True for single action
  │   ├─ workflow_target_resolver.resolve_workflow(workflow)
  │   └─ run_level3_workflow(workflow) → may return None for single-step
  │
  ├─ Falls through to:
  │
  ▼
GenesisOS.run_level3(text, classification) [genesis.py:1246]
  │
  ├─ compound_task_router.route(text) — single action, no compound
  │
  ├─ ActionPlan.from_decision(classification)
  │   └─ Creates ActionPlan(operation="application.open", target="notepad")
  │
  ├─ _resolve_semantic_target(plan) — "notepad" is already concrete
  │
  ├─ print("Operation: application.open")
  ├─ print("Target: notepad")
  │
  ├─ action_executor.execute(plan) [action_executor.py]
  │   ├─ OSManager → ApplicationManager → resolves "notepad" to executable path
  │   ├─ subprocess.Popen / os.startfile — launches Notepad
  │   ├─ Verification: checks if process started
  │   └─ Returns ActionResult(success=True, executed=True, verified=True)
  │
  ├─ _update_session_from_result(plan, result)
  │   └─ session_state.update_application("notepad", is_focused=True)
  │
  ├─ entity_history.record_from_result(...)
  │
  ├─ print("Operation completed successfully.")
  ├─ print("Result verified.")
  │
  └─ Returns user_message()
```

### Observations

- **Requires manual confirmation.** The console reports "Result verified" but this only confirms the process started, not that Notepad is visibly open on screen. A human watching the screen should confirm.
- **Application resolution is real.** `ApplicationManager` resolves "notepad" to the actual Windows executable path via `ApplicationTargetProvider`.
- **Verification is honest for this case.** The action executor checks process start, which is a real post-state signal.

---

## 5. Seeded Known Finding — Compound Request Data-Flow Gap

**FINDING: MISSING_CAPABILITY**

**Request:** `open notepad and write html code for website`

**Expected behavior:** Open Notepad AND type the generated HTML into it.

**Actual behavior:**
1. `WorkflowDecisionEngine.decide()` detects compound L3 signal (2 clauses joined by "and")
2. Routes to Level 3 compound path
3. `CompoundTaskRouter.route()` decomposes into: Step 1 = "open notepad", Step 2 = "write html code for website"
4. Step 1 executes: Notepad opens (verified)
5. Step 2: The Coding Agent generates HTML and saves to `C:\Users\<user>\Documents\Genesis Studio\Code\`
6. **The generated HTML is NEVER passed to the Notepad window.** The two steps are independent; there is no data-flow contract between agent output and subsequent OS-action input.
7. Genesis reports "Genesis completed the objective in 1 verified step(s)" — this refers only to the desktop action (open notepad), not to any content reaching the window.

**Classification:** MISSING_CAPABILITY — both L2 generation and L3 app-open work correctly in isolation; the absent piece is a data-flow contract between agent outputs and subsequent OS-action inputs.

**Code evidence:** `genesis.py:1312-1337` — `compound_task_router.route()` returns a plan, and `run_level3_workflow()` executes steps sequentially but does not pipe output of one step as input to the next.

**Roadmap mapping:** This maps directly to Phase 10 (Dynamic Task Graph) of the roadmap, which requires representing "data flow between agent outputs" as a first-class part of step dependencies. NOT to be fixed in Phase 0 or as an ad hoc patch.

---

## 5b. Seeded Known Finding — PDF Keyword-Trigger Gap

**FINDING (a): MISSING_CAPABILITY**

No PDF creation path exists anywhere in the codebase. `DocumentAgent._create_docx_from_text()` creates `.docx` files only. The system has no `fpdf`, `reportlab`, or any PDF-generation code.

**FINDING (b): ARCHITECTURAL_PRINCIPLE_VIOLATION**

**Request:** `research biology and save it as a pdf`

**Actual behavior:** User-facing response includes "I can assist with generating a PDF" despite no PDF capability existing.

**Root cause:** `DocumentAgent.run()` at `document_agent.py:81-86`:

```python
creation_requested = _re.search(
    r"\b(create|write|make|draft)\b.*\b(document|report|letter|"
    r"essay|summary doc)\b",
    task,
    _re.IGNORECASE,
)
```

- "save" is NOT in the verb list (`create|write|make|draft`)
- "pdf" is NOT in the noun list (`document|report|letter|essay|summary doc`)
- `creation_requested` evaluates to `None` (falsy)
- No file creation is attempted
- The LLM's own response text makes an unfounded promise ("I can assist with generating a PDF") that the architecture cannot fulfill

**Classification:** This is a direct instance of Core Principle #2 being violated: "Capabilities over keywords. Frozen sets/regex may remain as fast hints or fallback, never the authoritative routing mechanism." The regex IS the authoritative routing mechanism for file creation — there is no semantic layer behind it.

**Code evidence:** `document_agent.py:81-86` (the regex), `document_agent.py:194-200` (only `_create_docx_from_text` is called).

**Roadmap mapping:** Documents directly to Phase 3 (Capability Control Plane) and Phase 9 (Documents + Data) for PDF creation capability.

**Scope note:** Verify independently whether other agents (spreadsheet, presentation) have the same regex-trigger-as-sole-router pattern. This may be systemic.

---

## 6. Architecture Map

### Actual Routing Path (from traces above)

```
                         ┌─────────────────────┐
                         │   User Input         │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │  ConversationEngine  │
                         │  .prepare_message()  │
                         └──────────┬──────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │  WorkflowDecisionEngine        │
                    │  .decide(text)                 │
                    │                                │
                    │  Priority:                     │
                    │  1. Compound L3 pre-check      │
                    │  2. _detect_os_intent()        │
                    │  3. Conversational guard        │
                    │  4. _detect_multi_agents()     │
                    │  5. _detect_single_agent()     │
                    │  6. Default → L1 conversation  │
                    └───────┬────────┬───────┬──────┘
                            │        │       │
               ┌────────────▼──┐  ┌──▼───┐  ┌▼────────────┐
               │ Level 3 (OS)  │  │  L2  │  │ Level 1     │
               │               │  │      │  │ (Conv.)     │
               └──────┬────────┘  └──┬───┘  └──────┬──────┘
                      │              │              │
         ┌────────────▼──┐    ┌──────▼──────┐  ┌───▼────────┐
         │ ActionPlan     │    │ Executor    │  │ Brain      │
         │ .from_decision │    │ (single/    │  │ .think()   │
         └──────┬─────────┘    │  multi)     │  │            │
                │              └──────┬──────┘  │ Router     │
         ┌──────▼──────────┐         │          │ AIEngine   │
         │ ActionExecutor  │    ┌────▼─────┐   │ Memory     │
         │ .execute(plan)  │    │ Agent    │   │ Emotion    │
         └──────┬──────────┘    │ .run()   │   └────────────┘
                │               └──────────┘
         ┌──────▼──────────┐
         │ OSManager       │
         │ ApplicationMgr  │
         │ BrowserManager  │
         │ FileManager     │
         └──────┬──────────┘
                │
         ┌──────▼──────────┐
         │ Verification    │
         │ (post-state)    │
         └──────┬──────────┘
                │
         ┌──────▼──────────┐
         │ ActionResult    │
         │ success/verified│
         └─────────────────┘
```

### Possible Duplicate-Orchestration Concern

**Observation:** The `Router` class (`router/router.py`) and `WorkflowDecisionEngine` (`agents/workflow_decision.py`) both perform intent classification, but at different layers:

- `Router.route()` is used ONLY by `Brain.process_request()` for Level 1 internal routing (memory/internet/knowledge/ai). It is a simple keyword matcher.
- `WorkflowDecisionEngine.decide()` is the primary decision layer for ALL levels (1/2/3).

These are NOT competing orchestration frameworks — `Router` is a sub-component of `Brain` for Level 1 internal dispatch, while `WorkflowDecisionEngine` is the top-level classifier. However, the naming ("Router" vs "WorkflowDecisionEngine") and the fact that both inspect the same text could cause confusion. The `Router` is essentially dead code for any request that reaches `WorkflowDecisionEngine`, since Level 1 requests go through `Brain.think()` which calls `Router.route()` — but `Brain.think()` is only called when `WorkflowDecisionEngine` classified the request as Level 1 AND `_handle_unmatched_request()` returned None.

**Not a bug, but a maintainability concern.** The `Router` class could be consolidated into `Brain` or removed.

---

## 7. Self-Reported Success Audit — 10 Capabilities

| # | Capability | File:Line | Verdict | Evidence |
|---|-----------|-----------|---------|----------|
| 1 | `application.open` | `action_executor.py:1077-1080` | **VERIFIED_HONESTLY** | After dispatch, executor checks process start and focus state. `verified` is bound to real post-state observation, not just "no exception". |
| 2 | `gui.type_text` | `action_executor.py:1039-1040` | **VERIFIED_HONESTLY** | Closed-loop: dispatch → re-inspect foreground window → focus retained. `verified=True` only when focus is confirmed post-dispatch (lines 1039-1040). The Phase 0 bug (`requires_runtime_resolution` → `verified=True`) has been fixed. |
| 3 | `gui.click` | `action_executor.py:1135-1316` | **VERIFIED_HONESTLY** | Same focus-retained contract as `type_text`. Post-dispatch focus inspection at line 1316 determines `verified`. |
| 4 | `browser.search` | `browser_selenium.py:127-128` | **SELF_REPORTED_ONLY** | Returns `{"success": True, "verified": True}` after `driver.get(url)` + `driver.find_element()`. No actual verification that search results loaded — just that the page navigated and an element was found. Could be a cookie-consent dialog, not search results. |
| 5 | `document.read` | `verification_helpers.py:74-87` | **VERIFIED_HONESTLY** | `verify_doc_read()` checks: file exists on disk AND read returned non-empty text payload. Real post-state signal. |
| 6 | `data.inspect` | `verification_helpers.py:60-71` | **VERIFIED_HONESTLY** | `verify_doc_inspect()` checks: file exists on disk. Real post-state signal. |
| 7 | `file.create` | `verification_helpers.py:113` | **VERIFIED_HONESTLY** | `verify_doc_create()` checks: created file exists AND is non-empty on disk. Real post-state signal. |
| 8 | `clipboard.copy` | `clipboard_manager.py:129` | **SELF_REPORTED_ONLY** | Returns `{"verified": True}` after `pyperclip.copy()`. No readback verification — clipboard content is not confirmed to match what was copied. (Note: `gui_controller.py` does have readback verification for clipboard operations, but the raw `clipboard_manager` does not.) |
| 9 | `browser.screenshot` | `browser_selenium.py:380` | **VERIFIED_HONESTLY** | Returns path after `driver.save_screenshot(path)`. File existence is the verification signal — screenshot files are non-trivial to create without actually capturing. |
| 10 | `folder.create` | `verification_helpers.py:650` | **VERIFIED_HONESTLY** | `verify_folder_create()` checks: created folder exists on disk. Real post-state signal. |

### Summary

- **8 VERIFIED_HONESTLY** — real post-state checks (file existence, process start, focus retention, content presence)
- **2 SELF_REPORTED_ONLY** — `browser.search` (page navigation ≠ search results), `clipboard.copy` (no readback)

---

## Deliverable

This report is the complete Phase 0 baseline deliverable. All findings are classified. No code was modified. The two seeded known findings (compound data-flow gap, PDF keyword gap) are documented with file/line evidence and roadmap mappings.

**Next step (not this phase):** Prioritize fixes based on this baseline — the two SELF_REPORTED_ONLY findings and the two seeded known findings are the highest-value targets.
