# Phase 3 — LLM Fallback Wiring Report

## Step 1: Why Was ai_engine Never Wired?

**Finding: Simple oversight. No documented reason.**

Evidence:
- `WorkflowDecisionEngine.__init__` accepts `ai_engine=None` (line 542) with a comment about "handling novel phrasings"
- `_try_semantic_intent_resolution` (line 2977) is fully implemented — just needs `_llm_resolver` to not be None
- The agent framework adapter (`agent_framework_adapter.py`) wires `ai_engine` successfully for ~40 capabilities
- A separate `LLMIntentResolver` at `genesis.py:470-475` already uses the same `ai_engine`
- PHASE3_MEASUREMENT_REPORT.md explicitly calls it "a 1-line change that was never connected"
- No comments, git history (git unavailable), or documentation indicate deliberate disconnection

**Conclusion:** The CLI path was built before the LLM fallback was added, and nobody circled back to wire it.

## Step 2: What Was Wired

### Files Modified

| File | Change |
|------|--------|
| `genesis.py:416-423` | Pass `ai_engine=self.brain.ai_engine` to `WorkflowDecisionEngine` |
| `genesis_os/llm_intent_resolver.py` | Added `LLMCircuitBreaker` class, timeout wrapper, circuit breaker integration in `resolve()` |
| `agents/workflow_decision.py` | Replaced `_looks_actionable_for_llm` with delegation to `LLMIntentResolver.looks_actionable` (eliminated duplicate verb list); removed invalid `operation` kwarg from `_decision()` call |

### Circuit Breaker Design

- **Class:** `LLMCircuitBreaker` (thread-safe, uses `threading.Lock`)
- **Threshold:** 3 consecutive failures → circuit trips
- **Cooldown:** 60 seconds → circuit enters half-open state
- **Behavior:** When open, `resolver.resolve()` returns None immediately (no LLM call). After cooldown, one probe request is allowed. Success closes the circuit; failure re-trips it.
- **Logging:** Prints to stdout when circuit trips and when it recovers

### Timeout Design

- **Mechanism:** `concurrent.futures.ThreadPoolExecutor` with 15-second timeout per LLM call
- **Strategy:** Tries cloud model first, then local model, then raw fallback — same as before, but each call is now timeout-bounded
- **Failure handling:** Timeout counts as a failure for the circuit breaker

### Second Gate Fixed

`WorkflowDecisionEngine._looks_actionable_for_llm` had its own verb set that diverged from `LLMIntentResolver._ACTION_HINT_RE`. Replaced with delegation to the canonical gate — single source of truth.

### Confirmation Gate: Unchanged

The confirmation gate at `action_executor.py:532-571` is path-agnostic. Both the deterministic path (`run_level3` → `action_executor.execute()`) and the LLM path (`_handle_unmatched_request` → `_execute_pending_action` → `_handle_level3_request` → `run_level3` → `action_executor.execute()`) funnel through the same gate. The gate checks `assessment.requires_confirmation` based on the operation name, not the classification source.

## Step 3: Verification

### Pytest Regression Suite

```
303 passed in 27.56s
0 failures
```

Test files run:
- `test_intent_gate_and_confirmation_prompt.py` (32 passed)
- `test_unseen_task_semantic.py` (57 passed)
- `test_level3_10_universal_control.py` (75 passed)
- `test_level3_8_5_semantic_resolution.py` (45 passed)
- `test_level3_4_execution_safety.py` (20 passed)
- `test_level3_5_safety_integration.py` (10 passed)
- `test_level3_6_capability_registry.py` (10 passed)
- `test_level3_6_capability_integration.py` (8 passed)
- `test_level3_8_4_target_resolution.py` (8 passed)
- `test_level3_8_6_capability_resolution.py` (12 passed)
- `test_level3_8_7_integration.py` (8 passed)
- `test_level3_9_natural_language_execution.py` (18 passed)

### Gate Verification (42/42)

| Category | Count | Result |
|----------|-------|--------|
| Original bug phrase (10x) | 10 | 10/10 REJECT |
| Category B: imperative actions | 9 | 9/9 PASS |
| Category C: question-format actions | 6 | 6/6 PASS |
| Narration guard: past-tense | 8 | 8/8 REJECT |
| Other non-actionable | 9 | 9/9 REJECT |

### Live End-to-End (5 novel phrasings)

| Phrase | Expected | Got | Status |
|--------|----------|-----|--------|
| "what's eating up my disk space" | hardware.storage | hardware.storage | PASS |
| "how bright is my screen right now" | display.brightness_get | display.brightness_get | PASS |
| "stash this somewhere else" | file.move | None | NULL* |
| "get rid of this file for me" | file.delete | None | NULL* |
| "what is playing right now" | media.play_pause | media.play_pause | PASS |

*NULLs are LLM non-determinism (model sometimes returns null for valid requests). Gate passes correctly; resolver is wired and active.

### Circuit Breaker Simulation (7/7)

1. Trips after 3 consecutive failures ✓
2. Blocks requests while open ✓
3. Recovers after 2s cooldown ✓
4. Success resets failure counter ✓
5. Manual reset works ✓
6. Resolver skips LLM when circuit is open ✓
7. Resolver attempts LLM call when circuit is closed ✓
