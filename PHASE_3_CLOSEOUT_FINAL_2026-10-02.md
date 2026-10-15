# Phase 3 — Final Closeout (Capability Control Plane)

**Date:** 2026-10-02
**Supersedes:** all earlier Phase 3 closeouts (archived)
**Corpus:** `phase3_v4_SEALED.json` / `phase3_v4_SEAL_DIGEST.txt` (unchanged, sealed)
**Results:** `phase3_final4_{cloud,control}_RESULT.json`

---

## 1. VERDICT: NOT CLOSED

| Configuration | Strict | 95% Wilson CI | FP | 95% Wilson CI |
|---|---|---|---|---|
| Cloud `openai/gpt-oss-120b` | **36/57 = 63.2%** | 50.2–74.5 | **4/20 = 20.0%** | 8.1–41.6 |
| Deterministic control | 10/57 = 17.5% | 9.8–29.4 | 1/20 = 5.0% | 0.9–23.6 |

Pre-registered bar, unchanged: strict ≥75% **and** FP ≤5% **and** margin ≥20.
Strict **63.2% < 75% FAIL** · FP **20.0% > 5% FAIL** · margin **+45.7 ≥ 20 PASS**.
Context (5 items, reported separately): **0/5**.

This is the final scheduled remeasurement for Phase 3. It is identical to the
previous final4 measurement in every headline figure.

---

## 2. Step 1 — Backend reachability: resolved with evidence

**Question:** is the default backend order `('local','cloud',None)` with a 22s
budget a production defect that makes cloud unreachable?

**Citations.** `genesis.py:519` and `agents/workflow_decision.py:585` construct
`LLMIntentResolver` with no `GENESIS_LLM_MODES` and no budget overrides, so the
production path does inherit the default at
`genesis_os/llm_intent_resolver.py:290`.

**MEASURED — and it corrects an earlier claim in this phase.** Under production
defaults on this CPU-only host:

```
modes ('local','cloud',None)  call 12.0s  total 22.0s
attempt 1  local  12.0s  TimeoutError
attempt 2  cloud   0.8s  ok
total wall 12.8s      cloud reached: True   result: file.open
```

Cloud was **never unreachable**. An earlier report in this phase asserted it
"consumes the entire budget and cloud is never reached"; that was an inference
that was never tested and it was **wrong**. The per-call timeout bounds each
attempt, so the total budget cannot be consumed by one backend.

**The genuine, narrower defect is latency**: on a host with a slow or absent
local provider every request pays a fixed ~12s dead wait before cloud is tried.
This is now pinned by four regression tests, including
`test_cloud_is_reached_within_budget_when_local_is_slow`, which simulates a
timing-out local backend and asserts the cloud backend is still attempted.

**Documented configuration for any future live run** (so it need not be
rediscovered):

```
GENESIS_LLM_MODES=cloud            # skips local entirely
GENESIS_LLM_CALL_TIMEOUT=60        # per-call seconds
GENESIS_LLM_TOTAL_BUDGET=120       # whole-resolve seconds
GENESIS_LLM_INFLIGHT_CAP=2         # bound concurrent live workers
```

---

## 3. Step 2 — document/file and spreadsheet/file: DECISION (B), formally accepted as residual

**The trigger-level gap is already closed.** The previous lexical trigger asked
"is the matched domain's vocabulary absent?". It was replaced by an
evidence-based test — a candidate is decisive when the request names a concrete
target/application **or** names the operation that capability performs. Measured
**11/11** on the trigger cases including both previously-unresolved classes, and
specifically including the case the lexical trigger could not see at all
(vocabulary present, evidence weak).

**Why it still fails end-to-end, with evidence.** Live under a pinned cloud
backend:

| Request | Detector output | Result |
|---|---|---|
| `turn this manuscript into a fixed page layout` | **`None`** | L1, no decision |
| `work out which column of this sheet totals highest` | **`None`** | `spreadsheet.aggregate` |

The deterministic detector produces **no candidate at all** for these. There is
therefore nothing for arbitration to challenge, and coverage falls entirely to
the pre-existing semantic path. **This is a no-deterministic-candidate coverage
gap, not a trigger gap** — a different defect from the one the directive
described, which described the *old* trigger's behaviour.

**Decision: (B), accepted as residual.** Structurally, fixing it requires
broadening the no-candidate path (`_grounded_os_decision` and the normal
semantic path) rather than the arbitration trigger, and doing so without
reintroducing lexical heuristics would mean a new semantic-coverage mechanism —
which is a redesign, not a fix, and is explicitly out of scope for this
directive. Failure examples, mechanism and scope are recorded here as a known,
owned limitation rather than left as a third "still open" report.

**Owner:** the next semantic-coverage work item. Not a benchmark problem.

---

## 4. Step 3 — Complexity sanity pass: clean

Read-through of `arbitrate_capabilities()`, `_arbitrate_os_decision()` and
`_deterministic_evidence()` for the four defect classes seen in this phase:

- **Decorators:** audited by AST. Only `_deterministic_evidence` and
  `deterministic_evidence_is_decisive` are `classmethod` (correct); all other
  probe methods are instance methods (correct).
- **Tuple/argument construction:** no 1-tuple assignments anywhere in the three
  functions.
- **Silent no-op:** `_arbitrate_os_decision` uses the decisive trigger and does
  **not** reference the retired lexical trigger; it calls both
  `grounded_capability` and `arbitrate_capabilities`. A direct injection test
  confirms the feature actually fires (`file.move` → `folder.move`) and that both
  `_capability_arbitration` and `_arbitration_eligibility` are recorded, so it
  cannot be quietly disabled.
- `_shortlist_catalog` verified **byte-identical** to its intended construction,
  all 27 domains and all 141 capability ids present, idempotent across calls.

---

## 5. Step 4 — Live validation (corrected environment)

Provider pinned before construction: `['GroqProvider']`, model
`openai/gpt-oss-120b`, health available (9.4s), `modes=('cloud',)`,
call 60s, budget 120s.

| Case | Result | Time |
|---|---|---|
| folder/file | `folder.move` (correct) | 1.7s |
| gui/clipboard-style | `clipboard.copy` (correct) | 1.0s |
| document/file residual | **L1, no decision** | 1.1s |
| spreadsheet/file residual | `spreadsheet.aggregate` | 1.8s |
| **Phase 0 forensic guard** | **`gui.type_text`** | 0.6s |

**Reported honestly:** every one of these wordings produced **no deterministic
candidate**, so arbitration was not reached on them; they resolve through the
pre-existing semantic path. A separate injection test (Step 3) proves the
arbitration path itself fires. Phase 0 held live, not only in regression tests.

---

## 6. Step 5 — Full regression

```
python -m pytest -q -p no:cacheprovider
2281 passed, 60 warnings in 791.64s
```

Requirement ≥2,254 — **met**, zero failures. Baseline 2,254 + 27 new tests.

---

## 7. Step 6 — final4 remeasurement (the one remaining run)

Scored exactly once. Cloud only; local skipped, per the established 0%-margin
finding and because nothing in Steps 1–3 touched local behaviour.

**Validity:** 0 errors, 0 rate limits, 82/82 items scored, 34 real round-trips,
84.1s wall. 23 sub-second no-answers: 15 correct negative blocks, 5
gate-blocked positives, **3 unexplained** — recorded as a validity caveat.

### Failure taxonomy — targeted classes

| Class | Previous final4 | This run | Movement |
|---|---|---|---|
| `deterministic_outranked_llm` | 6/57 | **5/57** | −1 |
| `no_l3_decision_after_round_trip` | 6/57 | **5/57** | −1 |
| `wrong_capability_by_model` | 5 | 6 | +1 |
| `gate_or_deterministic_decline` | 4 | 5 | +1 |
| `context_miss` | 4 | 5 | +1 |
| `false_positive` | 4 | 4 | — |
| `ok` / `ok_negative` | 36 / 16 | 36 / 16 | — |

Both targeted classes fell by one and neither was eliminated; the offsetting
increases mean the headline is unchanged.

### Why the phase's work did not move the number

Honest finding, not an excuse. On final4, most requests produce a deterministic
candidate that the new evidence test judges **decisive** (anchored, or naming
the operation), so arbitration correctly pays nothing and rarely fires. The
cases it would fix are the ones where the detector returns **no candidate at
all**, which is the residual recorded in §3. Context fell from 1/5 to 0/5.

---

## 8. Phase 3 defect ledger — every class found, and its disposition

| # | Defect | Disposition |
|---|---|---|
| 1 | Gate false-success ("gate PASS" meant admitted to the LLM, not correct) | **Fixed** — pinned; vocabulary renamed to lexical tier |
| 2 | Contaminated corpus (registry-description provenance; 12 few-shot examples) | **Fixed** — audit enforces; never valid evidence |
| 3 | Precedence: deterministic answered first, never challenged | **Fixed** — same-family hook + cross-domain arbitration |
| 4 | Suspected downstream discard at `workflow_decision.py:3108` | **Not a defect** — proven unreachable (0/141 ops, 0/20 dev3) |
| 5 | `looks_actionable` lexical gate (17.2% ceiling on held-out) | **Fixed** — three-tier + semantic grounding |
| 6 | Whole-request-anchor exploit (vague request grounded at full strength) | **Fixed** — anchors must be discriminative |
| 7 | Fabricated deterministic evidence (`score=1.0`, "authoritative") | **Fixed** — real evidence captured from the decision |
| 8 | Stray `@staticmethod` silently disabling arbitration | **Fixed** — AST decorator audit + no-op injection test |
| 9 | Missing `@classmethod` ×2; trailing-comma 1-tuple; clobbered `_shortlist_catalog` | **Fixed** — all restored and pinned |
| 10 | Lexical trigger unable to see "vocabulary present, evidence weak" | **Fixed** — evidence-based decisiveness, 11/11 |
| 11 | **No-deterministic-candidate coverage gap** (document/file, spreadsheet/file) | **Accepted as residual** — §3 |
| 12 | Preconditions declared but not enforced | **Fixed** — see §9.1. Enforced generically in `capability_resolver.py`; 17 capabilities / 23 preconditions; strict no-op across the other 124 |
| 13 | No prior-turn channel (context misses) | **PARTIALLY FIXED** — see §10. Single prior turn supported and proven; multi-turn chains out of scope |
| 14 | False-positive rate 20% | **Partially characterised** — Item 2. Not reproducible against adversarially-vetted negatives (8.7% vs 20.0%); one real defect remains as item 21 |
| 15 | `file.rename` with no new name drops to L1 instead of asking | **Open — named future item**, not fixed. §9.6 |
| 16 | A precondition-bearing SEMANTIC candidate can be selected by arbitration but never installed | **Open — named future item**, not fixed. §9.6 |
| 17 | 4 routing/sub-page gaps surfaced by restored tests | **Open** — pre-existing, strict-xfailed. §9.5 |
| 18 | 13 regression tests lost to the truncation bug, unrecoverable | **Open — permanent coverage gap**, named in §9.4 |
| 19 | `LLMIntentResolver` env overrides permanently mutate class state, leaking budget values between tests | **Open — order-dependent**, demonstrated in §9.6 item 5 |
| 20 | ACTIONABLE-tier requests with no deterministic candidate never reach the context channel | **Open** — §10.7. Production routing change, out of scope for Item 4 |
| 21 | Regex literal `archive` resolves `folder.organize` at 0.91 with no target, and the hint is retained when the semantic layer declines | **Open** — Item 2. The only real FP defect surviving an adversarially-vetted negative set |
older.organize\ at 0.91 with no target, retained on semantic decline | **Open** — Item 2. The only real FP defect surviving a vetted negative set |

---

## Phase 3 — Final Sign-Off

```
Date: 2026-10-02

STEP 1 backend reachability: RESOLVED WITH EVIDENCE.
  Production does inherit ('local','cloud',None) at
  llm_intent_resolver.py:290 via genesis.py:519 and
  workflow_decision.py:585. MEASURED under production defaults:
  local bounded at 12.0s (TimeoutError), cloud answered in 0.8s,
  total 12.8s. Cloud was NEVER unreachable; the earlier claim in
  this phase that it was is CORRECTED as unmeasured and wrong.
  Real residual defect is a fixed ~12s latency penalty, now pinned
  by 4 regression tests. Live env documented above.

STEP 2 document/file + spreadsheet/file: DECISION (B), FORMALLY
  ACCEPTED AS RESIDUAL. Trigger-level gap already closed by the
  evidence-based trigger (11/11). The live failure is a distinct
  NO-DETERMINISTIC-CANDIDATE COVERAGE GAP: the detector returns
  None, so arbitration has nothing to challenge. Owner: next
  semantic-coverage item. Not a benchmark problem.

STEP 3 complexity sanity pass: CLEAN. Decorators audited, no
  1-tuples, no silent no-op (injection test proves the feature
  fires). _shortlist_catalog byte-identical, 27 domains / 141 ids.

STEP 4 live validation (cloud pinned, openai/gpt-oss-120b,
  health OK 9.4s): folder/file correct, gui/clipboard-style
  correct, spreadsheet/file partial, document/file L1, Phase 0
  gui.type_text HELD live. Arbitration not reached on these
  wordings because the detector produced no candidate; reported.

STEP 5 regression: 2281 passed, 0 failed (>= 2254 required).

STEP 6 final4 remeasurement (scored once, cloud only):
  strict  36/57 = 63.2%  CI [50.2-74.5]
  FP       4/20 = 20.0%  CI [8.1-41.6]
  control 10/57 = 17.5%
  margin  +45.7 points
  strict < 75%  FAIL
  FP    > 5%    FAIL
  margin >= 20  PASS
  deterministic_outranked_llm        6 -> 5   (reduced, not fixed)
  no_l3_decision_after_round_trip    6 -> 5   (reduced, not fixed)
  headline identical to the previous final4 measurement
  validity: 0 errors, 0 rate limits; 3 unexplained sub-second
  no-answers recorded as a caveat

SEALED ARTIFACTS UNCHANGED: final3 and final4 digests verified
  against content; corpora, audits, scorer and thresholds untouched.

VERDICT: NOT CLOSED
```

**Why not closed.** The bar is 75% strict with FP ≤5%. The best valid
configuration reached **63.2%** with **20.0%** false positives, unchanged by this
phase's entire body of work. Both targeted defect classes shrank by one and
neither was eliminated. The measurement is sound, the diagnosis is thorough,
and the remaining gap is now precisely located: it is not the arbitration
trigger but coverage for requests where the deterministic detector produces no
candidate at all.

One caveat on the FP figure, carried forward honestly: the final4 negative set
is agent-drafted and less adversarially vetted than the positive set, so 20.0%
is not directly comparable to final3's 8.0% on a different negative set.

**This verdict applies to Phase 3 only.**

---

# 9. Item 3 — Precondition enforcement, then repo-damage recovery (2026-10-04)

Added 2026-10-04. Sections 1–8 above are the original 2026-10-02 closeout and
are unchanged. This section records Item 3 and the recovery work that followed a
bulk-edit bug that destroyed 21 test files.

## 9.1 Precondition enforcement — the actual Item 3 deliverable

**Unchanged and correct. It was not touched during recovery.**

`CapabilityResolver._resolve_exact` now enforces every declared precondition.
Verified properties:

| Property | Value |
|---|---|
| Precondition-bearing capabilities | 17 of 141 |
| Total declared preconditions | 23 |
| Every precondition is also a declared required input | yes — one mechanism covers the registry, no per-capability mapping |
| Behaviour on unmet precondition | `UNAVAILABLE` (not a new status), explanation names exactly which inputs are missing |
| Strict no-op for the 124 capabilities with no preconditions | the loop body never runs; the `RESOLVED` return is unchanged |
| `document.transform` re-verified | `("output_path", "output_format")` enforced; probe 1 PASS |
| Ranking probe | 3/3 |

Enforcement mechanism in `genesis_os/capability_resolver.py:414-501`. Not
modified at any point in the recovery.

## 9.2 Item 3 fixture repairs

Eight failures, all caused by enforcement correctly surfacing pre-existing gaps in
test fixtures.

**`file.rename` (2).** `rename the file I just created` and `rename the document
I was editing` previously asserted L3. `file.rename` declares `new_name` as a
required input, and an anaphoric rename supplies only the source, so the
condition is correctly unmet. Dropping to L1 is correct *for now* — the real gap
is that the system should ask for the missing name rather than silently failing
to Level 1, which is a Human Escalation concern (roadmap Phase 13), not
something built here. Logged as named future item #15 in §8 and §9.6.

The tests now assert three separate things, because the old single assertion
conflated them: recognition is intact (classifier still yields family
`anaphoric_file_rename`, intent `file.rename`, `requires_confirmation=True`),
no Level 3 decision is produced, and the refusal is caused by precisely the
missing input (resolving `file.rename` with no inputs is `UNAVAILABLE` naming
`new_name`; with `new_name` supplied it is `RESOLVED`). The precondition check
was **not** weakened.

**Arbitration fixtures (6).** `_det_intent` now supplies the candidate's own
declared required inputs, registry-derived and generic. This fixed 3 of the 6
outright. The other 3 depended on a *semantic* candidate resolving, which no
longer exists — see §9.5.

## 9.3 The truncation bug and the safeguard adopted

**What happened.** The script that inserted `@pytest.mark.live` markers contained

```python
new_lines = lines[:insert_at] + block        # BUG: dropped the tail
```

instead of

```python
new_lines = lines[:insert_at] + block + lines[insert_at:]
```

It **truncated 21 test files** to their import block. Caught by a collection
count check (2,468 → 2,058 tests); there is no git, no VSS access, and no other
copy on disk.

**Safeguard now in force — line-count assertion around every bulk edit.** Any
script that rewrites files must, for each file, record the line count before and
after and assert `after == before + len(block)`, plus re-parse the result with
`ast.parse` before writing. Both assertions live in the marker script
(`apply_live_markers.py`) that caused this. A splice is only ever
`head + block + tail`; a whole-file rewrite from a partial slice is never
acceptable. Concretely, the check that would have caught this is:

```python
assert len(spliced) == len(lines) + added
ast.parse(text)
```

**Recovery source.** `7041.zip`, dated 2026-09-21 — two weeks stale. Test names
were diffed against `.pytest_cache/v/cache/nodeids`, captured before the
truncation, so the loss list is measured, not guessed.

## 9.4 Recovery results — every lost test accounted for

29 tests were lost. **Every one is accounted for; none was silently dropped.**

| Disposition | Count | Basis |
|---|---|---|
| Restored from citation | **12** | see below |
| Not lost — renamed | **1** | `test_run_multi_agent_call_site_passes_inner_list` survives as `..._to_synthesis`; the node-ID cache is cumulative across runs |
| Genuinely lost, no citation | **16** | searched all 235 `.md`/`.txt`/`.log`/`.json` artifacts |
| — of those, re-covered during the §9.5 fix | 3 | the idempotency trio; contract is `roadmap_addendum_phase5_provider_safety.md:54-57` |
| — **remain permanently lost** | **13** | named below |

**Restored with citation (12).**

| Restored | Cited from |
|---|---|
| `TestTwoStepCompoundParaphrases::test_routes_to_compound_workflow` ×7 | `phase2_collect_now.txt:35` (node IDs encode `<text>-<first_op>-<second_op>`) |
| `TestSettingsSubPageContext::test_routes_to_system_open_settings_sub_page` ×2 | `phase2_collect_now.txt:72` |
| `TestBrowserContext::test_browser_context_routes_to_browser_intent` ×1 | `phase2_collect_now.txt:78` |
| `test_production_genesis_wires_adapter_to_canonical_executor` | `PHASE_2_SEMANTIC_ADAPTER_2026-09-26.md:55-61` |
| `test_newly_wired_capabilities_and_aliases_build_canonical_plans` | `PHASE_2_SEMANTIC_ADAPTER_2026-09-26.md:107`, membership read from `phase2_step1_dispositions_2026-09-26.txt` |

Only parametrized *rows* were restored — the methods survived, so no assertion
logic was invented. The two adapter tests were rebuilt from the quoted contract;
the A/B membership is read from the machine-readable disposition capture at test
time rather than hard-coded.

**Permanently lost — 13, named as a permanent coverage gap:**

| File | Lost tests |
|---|---|
| `test_phase5_provider_registry.py` (2) | `test_webbrowser_health_check_is_non_destructive`, `test_webbrowser_is_always_registered_without_network` |
| `test_level3_3_browser_adversarial.py` (1) | `test_dispatch_success_without_url_readback_is_unverified` |
| `test_level3_6_golden_workflow.py` (2) | `test_create_final_copy`, `test_verify_result` |
| `test_intent_gate_and_confirmation_prompt.py` (1) | `test_desired_state_without_evidence_is_not_reported_as_verified` — its contract *is* now asserted by the rewritten `test_already_in_desired_state_does_not_print_not_verified_line`, but the named test is gone |
| `test_phase2_agent_framework_adapter.py` (3) | `test_all_registry_capability_descriptors_are_resolvable`, `test_browser_upload_requires_explicit_approval_token`, `test_full_registry_capability_surface_is_callable_or_aliased` |
| `benchmark_real_os/test_benchmark_real_os.py` (4) | `test_action_executor_failure_does_not_fall_back_to_osmanager`, `test_process_list_plan_is_targetless`, `test_run_step_uses_raw_request_and_fails_closed_on_router_mismatch`, `test_semantic_check_routes_raw_natural_language` |

**No replacement was fabricated for any of these.** Where the underlying contract
is still worth pinning, a *new* test was written from a citable source and named
accordingly (see §9.5).

## 9.5 Failure triage — 24 failures, triaged individually

Not batch-dismissed as "stale". Each was classified by asking whether the
behaviour it checked was *deliberately* changed, with the source of that change
identified. **20 × (a) intentional evolution. 4 × pre-existing gaps. 0 × (b)
regressions.**

The decisive method: `objective_understanding.py` and
`context_hint_resolver.py` were A/B-tested by loading the 2026-09-21 versions
side by side with current. The four remaining failures reproduce **byte-identically
on 9/21**, which rules out a regression introduced in the last two weeks.

| # | Failing test(s) | Cause | Class |
|---|---|---|---|
| 1–5 | `TestRunnerWithMockOSM::test_runner_osm_call_args_*` (5) | `_build_osm_call_args` removed; `_dispatch` now executes via `ActionExecutor` exclusively — "does not silently fall back to a direct OSManager call" | **(a)** refactor |
| 6–8 | `TestPart4Amendment3Idempotency::test_browser_click_is_idempotent`, `test_idempotent_allows_blind_retry`, `test_idempotent_skips_state_check` | production now carries an explicit 67-entry `NON_IDEMPOTENT_CAPABILITIES` set containing `browser.click`; `roadmap_addendum_phase5_provider_safety.md:54-57` classifies anything with real-world side effects as non-idempotent | **(a)** |
| 9 | `TestPart5WiringPerOperationDispatch::test_dispatch_with_fallback_returns_error_when_all_fail` | non-idempotent + no state checker ⇒ blind fallback refused, message changed accordingly | **(a)** |
| 10–11 | `test_browser_download_dispatched`, `test_browser_upload_dispatched` | `security_model.py` declares both `requires_confirmation=True`; `browser.upload` also in `APPROVAL_REQUIRED_CAPABILITIES` (`PHASE_2_SEMANTIC_ADAPTER:77,109`) | **(a)** |
| 12 | `test_tool_description_includes_descriptor_fields` | tool description now always annotates risk tier | **(a)** |
| 13 | `test_open_my_downloads_folder_end_to_end` | Phase 1 evidence contract rejects `verified=True` without capability-specific evidence; `OSManager.open_folder` is a bare pass-through with no verifier, unlike `create_folder`/`list_folder` | **(a)** |
| 14–15 | `test_multi_step_workflow_executes_and_verifies`, `test_confirmation_required_stops_entire_workflow` | same — the `_verified_result` fixture fabricated a bare `verified: True`, rejected at the gate | **(a)** |
| 16–17 | `test_pure_level3_objectives_do_not_invoke_agents`, `test_mixed_objective_runs_level3_and_level2_together` | same, plus the Coding Agent is resolved via `unified_executor.agent_registry`, not `genesis.executor`, so the old monkeypatch never intercepted it | **(a)** |
| 18 | `test_compound_pipeline_returns_workflowresult_with_both_steps` | `ObservationLoop` requires an independently observed browser page state | **(a)** |
| 19 | `test_settings_compound_plan_is_valid` | same, plus the fabricated result was rejected before step 2 was ever dispatched | **(a)** |
| 20 | `test_already_in_desired_state_does_not_print_not_verified_line` | `ActionResult.__post_init__` clears `already_in_desired_state` when it is unverified or carries no evidence — the desired-state flag is not evidence | **(a)** |
| 21–22 | `TestTwoStepCompoundParaphrases[…langchain…]`, `[…navigate to github…]` | "navigate to ⟨site⟩" classifies as `browser.search`, not `browser.open_url` | **pre-existing** — identical on 9/21 |
| 23 | `TestSettingsSubPageContext[…display settings / dark mode…]` | `dark mode` triggers both `display` and `personalization`; resolver returns `display` (arguably correct — the user said "display settings") | **pre-existing** — identical on 9/21 |
| 24 | `TestSettingsSubPageContext[…sound settings / headphones…]` | compound detector does not split "open the sound settings **and switch** the output to headphones" | **pre-existing** — identical on 9/21 |

**Fixes applied.**

- For every **(a)**: the test was updated to the new, intentional behaviour. No
  production code was changed anywhere in this pass. Where the old assertion was
  conflating "the environment lacks a browser" with "the pipeline is correct",
  it was rewritten to assert the honest-degradation contract instead — e.g.
  "an unverified workflow must not report success" — so the coverage is preserved
  rather than dropped.
- `test_browser_click_is_idempotent` → `test_browser_click_is_non_idempotent`,
  and two companions added (`test_browser_mutation_operations_are_non_idempotent`,
  `test_unknown_capability_is_not_assumed_idempotent`), matching what the lost
  set shows production had moved to.
- `test_dispatch_with_fallback_returns_error_when_all_fail` now pins **both**
  branches: refuse-blind-fallback for non-idempotent, all-providers-tried for
  idempotent.
- The five obsolete `_build_osm_call_args` tests were replaced by four tests
  pinning the contract that replaced them, including
  `test_unregistered_intent_fails_closed_instead_of_falling_back`.

**For the 4 pre-existing gaps:** marked `xfail(strict=True, reason=…)`. They are
visible, named, and will turn into a *failure* the moment the routing is fixed,
forcing the marker to be removed. They are neither hidden nor weakened.

## 9.6 Named future items — not fixed, not hidden

1. **`file.rename` routes to L1 instead of asking for the missing name.** The
   precondition is correctly enforced, but a user saying "rename the file I just
   created" gets a conversation-level reply rather than a clarification. Human
   Escalation / roadmap Phase 13 ("ask for confirmation… escalate ambiguity
   instead of uncontrolled retries"). Deliberately not built in this pass.
2. **A precondition-bearing semantic candidate can be selected by arbitration but
   never installed.** `_arbitrate_os_decision` and `_grounded_os_decision` both
   build the promoted decision's `parameters` from two metadata keys alone, so a
   semantic candidate's declared required inputs are never present and the
   control plane refuses every precondition-bearing promotion — 17 of 141
   capabilities. The practical effect is that cross-domain arbitration is biased
   toward the deterministic candidate for exactly those capabilities, and the
   arbitration record is dropped when promotion is refused. Pinned by
   `test_precondition_bearing_semantic_candidate_can_be_selected_but_never_installed`.
3. **`OSManager.open_folder` has no verification helper**, so `folder.open` can
   never be honestly verified, unlike `create_folder` / `list_folder`.
4. **Four routing / sub-page gaps**, §9.5 rows 21–24.
5. **Order-dependent test isolation in the LLM budget tests — NEW, found during
   this pass, NOT fixed.** `LLMIntentResolver` applies its
   `GENESIS_LLM_CALL_TIMEOUT` / `GENESIS_LLM_TOTAL_BUDGET` overrides by
   **permanently writing the class attributes**. `test_budget_env_vars_remain_the_escape_hatch`
   (`test_phase3_trigger_hardening.py:532-549`) pops the env vars in a `finally`
   but does not restore the class attributes, so constructing a resolver with
   those vars set leaks `_LLM_CALL_TIMEOUT = 60.0` /
   `_RESOLVE_TOTAL_BUDGET = 120.0` into the rest of the process.
   `test_phase3_control_plane_maturity.py::TestProviderCallBounding::test_budgets_are_bounded`
   then asserts the *production defaults* and fails. Demonstrated:

   ```
   pytest test_phase3_control_plane_maturity.py test_phase3_trigger_hardening.py
     -> 132 passed
   pytest test_phase3_trigger_hardening.py test_phase3_control_plane_maturity.py
     -> 2 failed, 130 passed
   ```

   It is currently masked in a full run only by alphabetical file order
   (`...control_plane_maturity` sorts before `...trigger_hardening`).
   `pytest-randomly` is **not** installed, so the masking is deterministic
   today — but any future reordering, parallelisation (`pytest-xdist`), or
   reordering of these files turns this into a real red. Fix belongs in
   production: the env override should not mutate shared class state.

## 9.7 Test-split infrastructure — reuse for Items 2 and 4

The `live` marker was already registered in `backend/pytest.ini` but applied
nowhere. It is now applied at the granularity each file warrants: file-level
`pytestmark` for wholly-live files, function-level `@pytest.mark.live` for files
mixing real and mocked tests.

| | Count |
|---|---|
| `live` (excluded from fast run) | 439 |
| non-live (fast run) | 2,044 |
| **Total collected** | **2,495** |

**Two commands, run from `backend/`:**

```
FAST (default iteration, ~2 minutes)
    python -m pytest -m "not live"

FULL (the real gate, ~21 minutes — pay once before declaring an item done)
    python -m pytest
```

`-m "not live"` is deliberately **not** in `addopts`: if it were, a bare `pytest`
would silently stop running the live tests and the full gate could not be run
without editing the config.

Also changed in `pytest.ini`: `--ignore=_debug_test.py` was added. It is a
zero-test debug script that pytest collected by accident and which cost 241s of
import time on every run. The `--ignore` list now contains only scripts with no
tests; three files that *do* have tests (`test_modal_dialog_recovery.py`,
`test_phase6_real_windows.py`, `test_phase6_text_verification.py`, 27 tests) were
**removed** from it, because they were silently disabled from every run. They are
now governed by the `live` marker — excluded from fast, included in full.

## 9.8 Final verification — verbatim, from an actual run

Fast suite (`python -m pytest -m "not live"`):

```
2044 passed, 12 skipped, 439 deselected in 111.21s (0:01:51)
```

**Full suite (`python -m pytest`, no flags) — authoritative:**

```
2479 passed, 12 skipped, 4 xfailed, 62 warnings in 1273.65s (0:21:13)
```

**0 failed.** Above the 2,444 threshold. This is the documented full-run
command executed verbatim, with no plugin flags, against the final repository
state.

Earlier full runs this session, for the runtime record:

| Run | Result | Wall |
|---|---|---|
| pre-triage baseline | 24 failed | 16m52s |
| post-fix, run A | 2479 passed | 21m05s |
| post-fix, run B (confirmation) | 2479 passed | **1h24m** |
| **final, plain `pytest`** | **2479 passed** | **21m13s** |
| earlier post-restore | 20 failed | 21m29s |

Three of five land in 16–21 minutes, matching every historical full-suite log in
the repository (2016-09-02 → 09-03: 4–12 minutes for 1,200–1,400 tests). The
previously reported **4h24m did not reproduce in any run**, and neither did run B's
1h24m.

Run B was investigated and **could not be reproduced**:

- The fast non-live suite is stable at ~111-116s across every run.
- Re-timing the six slowest live files individually totals ~440s and every one
  is at or below its historical time (`test_level3_3_browser_adversarial.py`
  20.9s vs 85.2s originally; `test_level3_2_applications.py` 72.2s vs 149.5s) —
  i.e. the browser-provider probes got *cheaper*, not more expensive.
- Test counts and outcomes were byte-identical between runs A and B, so B was
  not doing different work.

The most likely explanation is a transient network stall during run B: the
`live` set's cost is dominated by `ChromeDriverManager().install()` and
`sync_playwright()` probes, which are per-process uncached and would each burn
their full timeout if the network went away mid-run. That is consistent with a
~4x wall-clock jump with identical test outcomes. **This is recorded as an open
infrastructure observation, not chased**, per instruction. It does not affect
correctness: run B is green.

**Item 3 is closed.** Precondition enforcement was the deliverable and is
correct and untouched (§9.1). The recovery is complete with every lost test
accounted for (§9.4), every failure triaged individually (§9.5), future items
named rather than hidden (§9.6), and the fast/full split documented for reuse
(§9.7).

---

# 10. Item 4 — Minimal context channel (Roadmap task 2)

Added 2026-10-04. Roadmap task 2 verbatim: *"Semantic retrieval and
context-aware candidate selection."*

## 10.1 What was found before building

`decide(text)` accepted exactly one argument. Verified, not assumed: there was
no prior-turn, history or conversation parameter anywhere on the path
`decide` → `_try_semantic_intent_resolution` / `_arbitrate_os_decision` /
`_grounded_os_decision` → `LLMIntentResolver`, and no dormant context
parameter on any of the seven prompt builders. The channel was structurally
absent, exactly as the roadmap said.

The sealed corpora already carried the field: every v3 and v4 `CONTEXT_ITEMS`
entry has a `prior` string. **The harness was dropping it on the floor** —
`phase3_final4_score.py` called `engine.decide(item["phrase"])` with one
argument, so the field existed in the item, was used for *classification*,
and never reached the pipeline. That is why the 5 final4 context items scored
as an automatic GAP: not a routing failure, a missing argument.

## 10.2 The mechanism

One optional parameter, `prior_turn`, threaded from the entry point into the
semantic/grounding prompts only:

```
decide(text, prior_turn=None)
  -> _try_semantic_intent_resolution  -> resolver.resolve(text, prior_turn=)
  -> _arbitrate_os_decision           -> grounded_capability(text, prior_turn=)
  -> _grounded_os_decision            -> grounded_capability(text, prior_turn=)
       -> _grounding_probe            -> prompt gains a labelled PREVIOUS TURN
       -> evaluate_grounding          -> discriminativeness denominator (below)
```

Where the prior lands in the prompt:

```
PREVIOUS TURN: <prior>

USER: <request>

JSON:
```

with one extra rule telling the model to resolve "that" / "it" / "this one"
against it, and an explicit instruction never to quote the anchor from the
prior turn.

**Deliberately NOT threaded:**

| Site | Why |
|---|---|
| `_detect_os_intent` and the whole deterministic/regex layer | "keywords/regex as fast hints" means it must stay context-free. It gained no parameter, and a test asserts that. |
| `arbitration_probe`, `arbitrate_capabilities` | Arbitration is done, and its anchor-fidelity rule was specified for single-turn requests. Tests assert both signatures are still prior-free. |
| `_resolve_exact` (preconditions) | Item 3's mechanism, untouched. A test asserts it contains no reference to the channel. |
| any state, history or memory store | One string, one request, no chain. A test asserts `decide()` accumulates nothing. |

**Scorer plumbing.** `phase3_final4_score.py`, `phase3_final3_score.py` and
`phase3_benchmark.py` now pass the `prior` field the item already carried.
PLUMBING ONLY — the sealed corpora, item classification, scoring, thresholds
and reported figures are all untouched. Without this the channel would be
unreachable from the benchmark, which was the original GAP.

## 10.3 The no-op guarantee — proven, not assumed

Four independent forms of proof:

1. **Prompt strings, compared to a transcription of the pre-Item-4 literal.**
   `test_grounding_prompt_without_prior_is_unchanged` asserts the composed
   no-prior prompt is `==` a hand-copied copy of the original. Rule wording,
   numbering and spacing are all pinned.
2. **Real pipeline, every existing request.** `decide(text)` compared against
   `decide(text, prior_turn=<variant>)` for **86 phrases** — every phrase in
   both sealed corpora plus the live-suite requests — across `None`, `""`,
   whitespace and newline-only. **0 mismatches.**
3. **Blank and non-string priors are treated as absent**, so a caller cannot
   widen the prompt or the gate by passing `""` or `0`.
4. **Call sites are conditional.** `prior_turn` is forwarded only when
   supplied, so the no-prior call is *literally* the pre-Item-4 call. This is
   why existing test doubles and overrides with the old signature kept working
   — four of them failed when I first threaded unconditionally, which is how
   the problem surfaced.

## 10.4 Anchor fidelity under context — the decision, and the trade-off

Measured live against all 8 sealed v4 context items before designing anything:

| Observation | Value |
|---|---|
| Model named the correct capability | 7/8 |
| Model anchored on the **current request** | **8/8** |
| Model anchored on the prior turn | **0/8** |
| Anchor covered the **entire** current request | **8/8** |

Those two facts forced the design:

- **Fidelity is NOT relaxed.** The anchor must still be verbatim in the
  *current request*. Measured 8/8, the model satisfies this anyway, so allowing
  a prior-turn anchor would buy nothing and would surrender the guarantee that
  the model points at words the user just typed. Pinned by
  `test_prior_turn_cannot_satisfy_fidelity`.
- **Discriminativeness had to widen, because otherwise nothing works.** A
  pronoun-led request like "skip this one" has no honest narrower span, so any
  faithful anchor covers all of it and the rule "leave one content word
  outside the anchor" rejects **8 of 8**. When a prior turn is supplied the
  denominator becomes request ∪ prior, since that is where the discriminating
  information genuinely lives.

**The accepted narrowing, stated plainly.** With a prior present, a model that
names the *wrong* capability and quotes the whole request can still pass,
because the prior supplies the out-of-anchor content word. That is a real
weakening of a measured safety property. It is accepted because without it the
feature cannot function at all, and bounded because it cannot arise when no
prior is supplied. It is pinned as an executable fact by
`test_known_narrowing_is_documented_not_hidden`, so if a later item closes it
that test fails and this section gets revised.

**A tightening was tried and measured to fail.** The obvious fix — only let the
prior widen discriminativeness when the request is lexically ACTIONABLE — does
not work: three of the five legitimate context cases are AMBIGUOUS, and so is
every illegitimate one. Tiers do not separate them. Recorded by
`test_a_lexical_tier_gate_could_not_replace_this_rule` so the dead end is not
re-attempted. A domain-vocabulary guard was also considered and rejected on
measurement: `domain_tokens()` is built from capability-ID tokens only, so
"the settings window is open" does not support the `application` domain and
the guard would reject legitimate items.

Closing the narrowing properly needs the capability checked against the prior —
per-capability verifiers, or a model-side agreement check. Out of scope here.

## 10.5 Tests

`backend/test_phase3_minimal_context_channel.py` — **52 tests, all offline and
deterministic.** Only model probes are stubbed; `evaluate_grounding`, the
registry, the safety layer and the control plane are real.

| Group | Count | What it pins |
|---|---|---|
| No-op guarantee | 9 | 86 real phrases × 4 absent forms; prompt bytes; non-string priors |
| Prompt identity | 4 | grounding and single-stage prompts byte-identical without a prior |
| No invented context | 5 | no prior block for blank input; vague requests still refused; fidelity not satisfiable from a prior |
| Discriminativeness | 6 | whole-request anchor fails bare / passes with prior / fails for a stopword-only prior; the accepted narrowing; the dead-end tier gate |
| Synthetic context cases | 15 | **5 cases × 3 assertions** |
| Genuinely ambiguous | 6 | 3 structural refusals + 3 model refusals |
| Reachability limit | 3 | the routing limit below, asserted |
| Scope boundaries | 5 | regex layer, arbitration, preconditions and state accumulation all still context-free |

The five synthetic cases are pronoun reference, elided reference, a definite
reference across two candidates, anaphoric continuation, and an object
reference to a browser page. Each is asserted three ways: it **resolves with**
the prior, it is **refused without** the prior (so it is genuinely
context-dependent rather than context-tolerated), and **no prior leaks into the
prompt** when none was supplied.

Two of my first-draft assertions were wrong and I corrected them rather than
weakening the code: I had asserted that a vague request is *not* rescued by an
unrelated prior, and it is — that is the accepted narrowing above, now
documented as such instead of asserted as absent. And the "genuinely
ambiguous" cases now exercise the realistic path (the model declines) plus
structural refusals, rather than adversarially stubbing a model to claim an
action for a request that names none.

**All sealed-corpus phrase guards pass.** Two of my own docstrings initially
reused sealed context phrases (`close that`, `close it too`); the guards caught
both and the wording was changed. The live probe artifact was moved outside
the repository for the same reason.

## 10.6 Live validation

Cloud pinned per the documented configuration (`GENESIS_LLM_MODES=cloud`,
`GENESIS_LLM_CALL_TIMEOUT=60`, `GENESIS_LLM_TOTAL_BUDGET=120`,
`GENESIS_LLM_INFLIGHT_CAP=2`), model `openai/gpt-oss-120b`, 0 errors.

| Group | Result |
|---|---|
| Sealed v4 context items, **with** prior | **3/8 correct** |
| The same items, **without** prior (control) | **2/8 correct** |
| Non-context requests unchanged by an unrelated prior | **6/6 identical** |
| Errors | **0** |

The one genuinely new resolution is an anaphoric reference to a browser page
(`browser.extract`), which is Level 1 without the channel.

The non-context control is the important row: six ordinary requests, including
two anaphoric L3 routes and three conversations, produced byte-identical
decisions with and without a prior turn.

## 10.7 Why only 3/8 — the two structural causes, both pre-existing

Diagnosed by instrumenting `decide()` and counting model calls, not inferred.

**Cause 1 — the channel is not reached for ACTIONABLE-tier requests with no
deterministic candidate (2 items: `media.next`, `clipboard.paste`).**
`_deterministic_match_is_only_a_hint` returns `False` for a `None` decision,
so the semantic block that now carries `prior_turn` is skipped, and
`_grounded_os_decision` refuses non-AMBIGUOUS text by design. Instrumented
proof:

```
'skip this one'                  tier=actionable  _detect_os_intent -> None
  model calls inside decide(): [('shortlist', False)]   <- prior never used
'pull the numbers out of that'  tier=ambiguous   _detect_os_intent -> None
  model calls inside decide(): [('grounding_probe', True)]  <- prior used
```

Fixing this means changing the hint gate or adding a prior-aware escalation —
a production routing change, explicitly out of scope here. Ledger item 20.

**Cause 2 — precondition enforcement refuses the semantic candidate (2 items:
`file.copy`, `spreadsheet.sort`).** `file.copy` requires `destination` and
`spreadsheet.sort` requires `column`; a semantic decision carries no inputs, so
Item 3's enforcement returns UNAVAILABLE. This is the exact asymmetry recorded
as Item 3 future item #16 and §9.6 item 2, now observed end-to-end. Not fixed
here by design.

**One item reached Level 3 with a defensible but different capability**
(`document.create_pdf` where the corpus expects `document.transform`). That is
a model-choice disagreement that predates this item — the same choice was made
in the pre-Item-4 probe — not a channel failure.

So the honest reading of 3/8 vs 2/8: the channel works and is proven; the
corpus coverage is capped by two pre-existing structural facts, neither of
which belongs to a context-channel item.

## 10.8 Regression

```
python -m pytest -m "not live"
2096 passed, 12 skipped, 439 deselected in 149.08s (0:02:29)

python -m pytest
2531 passed, 12 skipped, 4 xfailed, 62 warnings in 1273.95s (0:21:13)
```

**0 failed**, above the 2531 threshold (2479 + 52 new). Runtime 21m13s,
inside the 16–26 minute baseline; the earlier one-off 1h24m outlier (§9.8) did
not recur. This is the final run, against a repo state verified free of
stray probe artifacts.

Two pre-existing order-dependent failures appear if
`test_phase3_trigger_hardening.py` is listed *before*
`test_phase3_control_plane_maturity.py` — that is ledger item 19 from Item 3,
not caused by Item 4, and green in default file order.

## 10.9 Can final4's context items now be scored?

**Yes.** They can be meaningfully scored going forward, and the change required
was plumbing only. `classify()` already reads `item["prior"]` and already
reported these as `context` rather than as failures, so the scoring logic,
thresholds and figures are unchanged — what was missing was an argument. The
scorer now passes the field the item already had.

The sealed corpus was **not** rescored and **not** modified, per instruction.
The measured 3/8 in §10.6 came from running the items live against the
existing scorer path; it is reported as evidence about the channel, not as a
benchmark figure, and the official context score remains whatever a future
scored run produces.

**Multi-turn chains are out of scope and remain open.** One prior turn, one
request. No session state, no history, no memory, no chains — deliberately, per
the roadmap's own task language and Phase 22's separate scope. Ledger item 13
is therefore recorded as **partially fixed**, with exactly this boundary.