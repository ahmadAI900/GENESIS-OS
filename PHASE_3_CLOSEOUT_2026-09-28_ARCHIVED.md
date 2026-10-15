# Phase 3 — Capability Control Plane

**Date:** 2026-09-28 (bar pre-registered 2026-09-29 12:54 local)
**Supersedes:** `PHASE_3_CLOSEOUT_2026-09-26_ARCHIVED.md`
**Machine-readable record:** `backend/phase3_final_results_2026-09-28.json`
**Ranking probe:** `backend/phase3_ranking_probe_2026-09-28.json`
**v3 audit:** `backend/phase3_v3_audit.json`
**Benchmark harness:** `backend/phase3_benchmark.py`
**v3 corpus + audit/sealer:** `backend/phase3_v3_corpus.py`, `backend/phase3_v3_audit.py`

---

## 1. Verdict and scope

**VERDICT: NOT CLOSED.**

| Directive step | Status |
|---|---|
| 0 — Order-independence confirmation | **DONE — CONFIRMED** |
| 1 — Build and seal the v3 corpus | **BLOCKED ON HUMAN INPUT** (audit tooling built and passing; 0 hand-written positives) |
| 2 — Pre-register the bar | **DONE** (§7) |
| 3 — Live ranking probe | **DONE — 2/3, one genuine FAIL recorded** |
| 4 — Measurement | **NOT REACHED** (no sealed corpus) |
| 5 — Failure taxonomy and rules audit | **NOT REACHED** for v3; the rules audit tooling is built and the legacy audit is closed (§11) |
| 6 — Regression and closeout | **DONE** (§12) |

Two things this session established that the previous one did not: the
batch bug is fully root-caused and there is **no surviving state bug**, and
one ranking signal the roadmap names **does not actually work**.

---

## 2. Roadmap conformance

| Task | Status | Evidence |
|---|---|---|
| Enrich descriptors | **PASS** | §6.1 |
| Semantic retrieval and context-aware candidate selection | **PASS / GAP** | §6.2 — two-stage selector verified; context dependence is a **GAP**: 9 context items exist but the selector has no prior-turn channel, so they are unscoreable as written |
| Capability ranking (confidence, preconditions, provider availability, risk) | **PARTIAL** | §6.3 — health and risk **proven by live probe**; **preconditions are declared but NOT enforced**, measured FAIL |
| Keywords/regex as fast hints or fallback | **PASS** | §6.4 |

**Conformance: 2 PASS, 1 PASS-with-GAP, 1 PARTIAL.**

---

## 3. Contained fixes (carried forward, unchanged)

Typed `UNSUPPORTED` from `resolve_operation()`; default resolver on
`WorkflowDecisionEngine`; single shared metadata propagator; live shared
provider-health registry; evidence-based `looks_actionable` (was rejecting
65% of the corpus pre-model); conversational guard no longer pre-empts a
correct semantic answer; `temperature 0.0` and 256-token output bound.

---

## 4. Order-independence confirmation (Step 0)

**CONFIRMED.** Three items, each in a fresh process, then the same three
sequentially, then reversed. All nine results identical.

| Item | Fresh process | Sequential | Reversed |
|---|---|---|---|
| "could you close the running application for me" | `None` / L1 / 192 s | `None` / L1 / 198 s | `None` / L1 / 188 s |
| "what is currently playing" | `None` / L1 / 198 s | `None` / L1 / 188 s | `None` / L1 / 194 s |
| "grab a picture of my screen" | `screen.capture` / L3 / 0 s | `screen.capture` / L3 / 0 s | `screen.capture` / L3 / 0 s |

In-flight slot counter was `0` after every item in all three modes. The two
failures are consistent across orderings, which is what makes them a model
finding rather than a state finding: the 7B model returns a stage-one
shortlist containing no valid canonical id for those two phrasings. The
third item routes deterministically in 0 s and never reaches the model.

**No second state bug exists behind the shim-timeout fix.**

---

## 5. Batch-vs-single root cause and fix (carried forward, now confirmed)

Root cause: the **Ollama OpenAI-compatibility shim's ~188 s wall-clock
ceiling**. The same 772-token prompt failed on the shim at ~188 s and
succeeded natively in 209.4 s returning the correct shortlist. Every
selection call was dying there, and the resolver caught `ProviderError`
and returned `None` — so a **provider timeout was counted as "the model
declined" for every item in every batch run**.

Fixed by routing prompts ≥ 1,500 characters to native `/api/generate` with
automatic shim fallback, plus a 240 s in-flight watchdog so a cap of 1
cannot delete every subsequent request. Regression test proven to fail on
pre-fix code:

```
OLD (no watchdog)      next_result=None      -> STARVED
NEW (bounded watchdog) next_result=file.copy -> served
```

---

## 6. Evidence

### 6.1 Descriptor enrichment
141 registered; 44 explicit risk tiers; 17 precondition sets; 46
selection-boundary notes; 115 input declarations. The 95 without a
boundary note are an accepted exception class — they are not members of an
identical-description family, so there is nothing to disambiguate.

### 6.2 Selector architecture
Two-stage: id-only grouped index (682 tokens) → full descriptors, risk,
inputs and boundary notes for ≤5 candidates (273 tokens). ~1,130 tokens
total vs 5,480 single-stage, a 79% cut.

**Context GAP:** the selector has no prior-turn channel. The 9 context
items exist in the v3 corpus and are retained, but the pipeline cannot
supply a `prior` turn to the resolver, so they are recorded as a GAP rather
than scored as failures or silently dropped.

### 6.3 Ranking probe — 2/3, with a real failure

Full output: `phase3_ranking_probe_2026-09-28.json`. All three are now
regression tests in `TestRankingProbes`.

**PROBE 1 — unmet precondition blocks: FAIL.**
`document.transform` declares `preconditions = ('output_path',
'output_format')`, yet a requirement naming the capability and declaring no
inputs **still resolves** (`status=resolved`). `_resolve_exact` validates
only the inputs the requirement itself declares, so an empty
`required_inputs` means "no constraint" and the declared preconditions are
never consulted.

Consequence: roadmap task 3 asks for ranking that takes preconditions into
account. They are currently **display metadata plus a small scoring term,
not an enforcement gate**. Recorded as a measured gap; pinned by a test
that documents the current behaviour so fixing it is a deliberate change.

**PROBE 2 — provider health changes ranking: PASS.**
Flipping recorded health on the live shared registry for
`browser.open_url` moves the rank score from **0.7675 → 0.9675**
(Δ +0.2000), and the structured evidence changes from
`provider_health score -0.15 "All registered providers last checked
unhealthy"` to `score +0.05 "A registered provider last checked healthy"`.

**PROBE 3 — risk triggers approval: PASS.**
5 of 9 sampled capabilities are gated; **0 low-risk** capabilities are
gated. `application.close` under test: a missing token is rejected, and a
token scoped to a *different* capability is rejected. Reuses the Phase 2
`HUMAN-APPROVE:` mechanism; nothing was rebuilt.

**Correction found by the probe:** the approval gate is **curated, not
derived from the risk tier**. `application.close` is *medium* risk and
gated; `document.transform` is *high* risk and **not** gated. The invariant
that holds is "nothing low-risk is gated", not "high-or-worse is gated".

### 6.4 Keywords/regex as fast hint
Deterministic and regex layers untouched and still execute first. The
conversational-guard fix demoted the guard to protecting the regex layer
rather than removing it. Evidence: "grab a picture of my screen" resolves
deterministically in 0 s and never calls the model.

---

## 7. Bar — PRE-REGISTERED

**Timestamped 2026-09-29 12:54 local, before any v3 run. Written before
any `final3` measurement exists.**

- **Primary bar:** strict accuracy ≥ **75%** on `final3` positives for the
  production-grade configuration, **and** false-positive rate on `final3`
  negatives ≤ **5%**.
- **Control:** the same `final3` run with `deterministic_only`. The LLM
  configuration must beat the control by **≥ 20 percentage points** of
  strict accuracy. A smaller margin does not justify keeping an LLM in the
  interactive path.
- **Reporting:** point estimate + 95% Wilson interval. With ~56 positives
  the interval is roughly **±11 points**; that imprecision is inherent to
  the sample size and must be stated with every number, not implied away.
- **On changing the bar:** permitted only before measuring, with written
  justification. Never after seeing a result. No result exists yet, so
  nothing has been changed.

---

## 8. Iteration history (this directive)

| # | Change | Result |
|---|---|---|
| 1 | Step 0: three items, fresh process | 1/3 correct (2 model failures, 1 deterministic) |
| 2 | Step 0: same three sequential | identical to reference |
| 3 | Step 0: same three reversed | identical to reference → **order-independence confirmed** |
| 4 | Diagnosed a swallowed 12 s timeout in my own probe | harness slip (missing `GENESIS_LLM_CALL_TIMEOUT`), not a product bug |
| 5 | Ranking probe 1 | **FAIL** — preconditions declared, not enforced |
| 6 | Ranking probe 2 | **PASS** — Δ +0.20 with changed evidence |
| 7 | Ranking probe 3 | **PASS** — 5/9 gated, 0 low-risk, tokens scoped |
| 8 | Probe test asserted risk-tier rule | test was wrong; corrected to the real invariant (gate is curated) |
| 9 | v3 audit: 6 overlap flags | all generic 3-grams; audit now separates significant from incidental |
| 10 | v3 audit: 3 significant flags | **rewrote my 3 own negatives** that shared guard prefixes → 0 significant |

---

## 9. Results

**No v3 results. No cloud or local number is reported, because no sealed
corpus exists.** Per the reporting rule, no number from a run known to be
invalid is presented as a result.

The legacy 40-item set remains unusable as evidence for the reasons in §13
and is not cited.

---

## 10. Failure taxonomy

Not produced — it requires a single valid `final3` run, which does not
exist. The directive correctly forbids producing it from anything else.

What the diagnosis did establish, outside the taxonomy:

| Class | Count | Evidence |
|---|---|---|
| Provider timeout counted as "model declined" | all items, all pre-fix runs | §5 |
| Slot starvation after timeout | 1 per timeout at cap=1 | §5 |
| Validation / safety rejection | **0/40** (model-free probe) | prior session |
| L3 gate rejection | **0/40** (model-free probe) | prior session |
| `looks_actionable` rejection | 0/40 post-fix (was 26/40) | prior session |
| Precondition not enforced | all 17 preconditions | §6.3 Probe 1 |
| Model quality, 7B local | unresolved | §4 |

---

## 11. Rules audit

**Legacy audit: CLOSED.** 690 fragment matches found; **12 of 29 few-shot
examples were verbatim corpus items** and were removed. Four tests now
block their return. A fifth permanently records that the legacy corpus is
textually contained in the prompt catalog, so nobody reaches for it.

**v3 audit tooling: built and passing.** `phase3_v3_audit.py` runs the
scan in the required direction (every v3 item against prompts, boundary
notes, few-shot examples, gate vocabulary and the deterministic regex
layer), rejects the legacy corpus, rejects the banned generator frames,
validates expectation ids, enforces composition minimums, and refuses to
seal unless everything passes.

Current v3 audit: legacy reuse **PASS**, banned frames **PASS**, overlap
**PASS** (0 significant, 3 incidental generic 3-grams), expectation ids
**PASS**, composition **INCOMPLETE**.

---

## 12. Regression

```
python -m pytest -q -p no:cacheprovider
2175 passed, 60 warnings in 1387.31s
```

Requirement ≥ 2,167 — **met**. Zero regressions. 8 tests added this
session (3 ranking probes + the curated-gate correction + 4 ranking-probe
supporting assertions).

`ruff`, `mypy`, `pyright`: **unavailable** on this host.

---

## 13. Corrections to prior claims

1. The 40-item held-out set is not generalisation evidence. Generated from
   registry descriptions, textually contained in the prompt catalog, and
   scored 8+ times.
2. `gate: "PASS"` meant *admitted to the LLM*, not *correct*.
3. "75% sits above the 78.7%" was written backwards; the 78.7% was a
   measurement, not a bar.
4. "Scored once" was false.
5. "LLM accuracy 91.7%" is not reproducible.
6. "looks_actionable blocks 36.8%" is stale.
7. **New this session:** the previous closeout reported the approval gate as
   following risk tier. It is curated, and `document.transform` (high) is
   not gated while `application.close` (medium) is.
8. **New this session:** preconditions were reported as a working ranking
   signal. Probe 1 shows they are not enforced at all.

---

## 14. What unblocks this

**One input is missing and only the project owner can supply it: ≥30
hand-written positive phrases.**

I cannot write them. I have read the capability registry, the prompt
templates, the selection boundary notes, the few-shot examples and the
legacy corpus, in this session and the last. Anything I author would be
contaminated in exactly the two ways that already destroyed the previous
corpus — which is why the directive forbids delegating this step, and why I
am not going to fake it.

**To proceed:**

1. Open `backend/phase3_v3_corpus.py` and fill `HUMAN_POSITIVES` with ≥30
   phrases in your own wording, plus enough more to reach 80 positives
   total, spanning application, GUI, browser, filesystem, documents,
   spreadsheets, system/hardware, media and clipboard.
   **Do not look at** the registry, the prompt files, the boundary notes or
   `phase3_benchmark.py` while writing them.
2. Run `python phase3_v3_audit.py`. It will refuse to seal until
   composition, overlap, banned-frame and expectation-id checks all pass.
3. Run `python phase3_v3_audit.py --seal` to split `dev3`/`final3` and
   record the `final3` SHA-256 **before** any run.
4. Then measure — the bar is already pre-registered in §7, so it cannot
   move after the result is seen.

Also worth fixing while the corpus is being written, since neither needs
the corpus: the **precondition enforcement gap** (§6.3 Probe 1) and the
**context channel** (§6.2).

---

## Phase 3 — Final Sign-Off

```
Date: 2026-09-28 (bar pre-registered 2026-09-29 12:54 local)

Order-independence: CONFIRMED. Three items run fresh-process,
  sequential and reversed produced nine identical results
  (2 consistent model failures, 1 consistent deterministic
  success). In-flight slot = 0 after every item. No second state
  bug exists behind the shim-timeout fix.

final3 SHA-256 (recorded pre-run): NONE — the corpus is not sealed.
  The v3 audit refuses to seal: composition is INCOMPLETE with
  0 hand-written positives, which the agent is not permitted to
  author.

Bar (pre-registered, timestamped 2026-09-29 12:54 local):
  strict >= 75% on final3 positives AND false-positive rate <= 5%
  on final3 negatives; LLM must beat the deterministic_only
  control by >= 20 points; point estimate + 95% Wilson interval,
  ~±11 points at ~56 positives.

Ranking probe: 2/3.
  precondition  -> FAIL. document.transform declares
                   (output_path, output_format) yet resolves with
                   no declared inputs. Preconditions are metadata,
                   not an enforcement gate. GAP recorded.
  health        -> PASS. browser.open_url 0.7675 -> 0.9675
                   (delta +0.20), evidence changes from -0.15
                   "all providers unhealthy" to +0.05 "a provider
                   healthy".
  risk          -> PASS. 5/9 sampled gated, 0 low-risk gated;
                   missing and wrong-scope approval tokens both
                   rejected via the Phase 2 HUMAN-APPROVE mechanism.
                   Correction: the gate is curated, not risk-derived.

Cloud result:   NOT MEASURED — no sealed corpus.
Local result:   NOT MEASURED — no sealed corpus.
Deterministic control: NOT RUN — no sealed corpus.

Rules audit: CLEAN for the v3 items that exist (0 significant
  overlap against 6 surfaces). Legacy audit closed: 12 contaminated
  few-shot examples found and removed, now blocked by tests.

Regression: 2175 passed, 60 warnings (requirement >= 2167), 0
  regressions. ruff/mypy/pyright unavailable.

VERDICT: NOT CLOSED

This verdict applies to Phase 3 only.
```

**The specific remaining blocker:** the v3 corpus cannot be authored by the
agent, and one named ranking signal (preconditions) was found not to work
when probed for the first time.

