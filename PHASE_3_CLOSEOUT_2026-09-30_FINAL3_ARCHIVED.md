# Phase 3 — Capability Control Plane

**Date:** 2026-09-30
**Supersedes:** `PHASE_3_CLOSEOUT_2026-09-28.md` (archived)
**Sealed corpus:** `backend/phase3_v3_SEALED.json`
**Results:** `phase3_final3_{cloud,local,control}_RESULT.json`

---

## 1. Verdict and scope

**VERDICT: NOT CLOSED.**

Both production configurations were measured on a properly sealed corpus
with a real capable model. Neither clears the pre-registered bar. The cloud
run is the meaningful number and it is a hard, honestly-earned miss.

| Configuration | Strict | 95% Wilson CI | FP | Verdict vs bar |
|---|---|---|---|---|
| Cloud `openai/gpt-oss-120b` | **50/77 = 64.9%** | 53.8–74.7 | 2/25 = 8.0% | **FAILS** (needs ≥75%, FP ≤5%) |
| Local `qwen2.5:7b` | **13/77 = 16.9%** | 10.1–26.8 | 1/25 = 4.0% | **FAILS** (needs ≥75%) |
| Deterministic control | 13/77 = 16.9% | 10.1–26.8 | 1/25 = 4.0% | — |

Margin over control: cloud **+48.0 points** (pre-registered minimum ≥20 —
met); local **+0.0** (not met).

For the first time in this phase, these numbers are trustworthy: the corpus
was sealed and hashed before any run, both models were verified at runtime,
no run starved, and determinism reproduced 5/5 on both configurations.

### Seal verification

Recorded and re-verified SHA-256:
`785b68217389b260a9c0999519afacc1c225d728444ad5e5a2b8cde37f07fe24` (102
items), recomputed from the sealed content after every step — **unchanged**.

> The hash quoted in the directive is 63 hex characters. A SHA-256 digest is
> 64. The directive string is the file's value minus its final `4`. The file's
> digest self-verifies against its own content, so the seal is intact and the
> directive string is a transcription truncation. Recorded rather than silently
> reconciled.

---

## 2. Step 0 — precondition-gap decision

**Decision: (B) measure WITH the gap present; fix afterward.**

The corpus was sealed with expectations assigned against the current system.
`document.transform` declares `preconditions = ('output_path',
'output_format')`, but `_resolve_exact` validates only the inputs the
requirement itself declares, so it resolves with no declared inputs. Enforcing
those preconditions first would make any requirement that does not itself
declare them unresolvable, turning `document.transform` items into failures
for a reason unrelated to routing quality. Measuring first yields a clean
baseline and avoids changing system behaviour between corpus design and
measurement.

The gap is therefore **live during this measurement** and is a known
contributor to the `document.transform` miss (§6).

---

## 3. Steps 1–2 — pre-measurement verification

**Registry / prompt drift:** 141 registered capabilities,
`CapabilityRegistry.operations()` = 141, **0 ids absent from the
shortlist**. No drift.

**Curated approval-gate invariant held:** `application.close` (medium risk)
gates; `document.transform` (high risk) does not. Matches the
ranking-probe session exactly.

**Resolved models, confirmed before any scoring call:**

| Config | Resolved model string | Health |
|---|---|---|
| Cloud | `openai/gpt-oss-120b` | available, 3359 ms, no error |
| Local | `qwen2.5:7b` | available, 32328 ms (cold), no error |

Local native-endpoint routing confirmed active: capability prompts are
5,794 chars against a 1,500-char native threshold, so `/api/generate` is
used, not the OpenAI-compat shim.

---

## 4. Validity

| Check | Cloud | Local |
|---|---|---|
| Determinism spot-check (5 items rerun) | **5/5 identical** | **5/5 identical** |
| Harness errors | 0 | 0 |
| Items with a genuine round-trip | 79 (3 excluded: 1 round-trip <1 s) | 61 (>60 s each) |
| Sub-second no-answers | 20 — **16 are negatives correctly gate-blocked** (legitimate), 4 positives | 17 |
| Wall clock | 976 s | 12,252 s (3.4 h) |

No starvation, no thrashing, no quota errors. Both runs are **valid**.

One harness misconfiguration occurred and was corrected **before any result
was produced**: the first local attempt used a 120 s per-call budget against
a measured ~190 s host latency, so item 1 timed out, its orphan held the
single in-flight slot, and 101/102 items were refused instantly. That run was
discarded as invalid and re-run at 300 s/600 s. No code change was made to
the system under test, and `final3` was not burned — the seal hash is
unchanged and no per-item result influenced any decision.

---

## 5. Results in detail

`final3` composition: **77 positives** (61 non-context + 16 context) and
**25 negatives** = 102 items. (The directive refers to 23 negatives; the
sealed set contains 25.)

**Context items are reported separately**, not folded into the headline.

| Config | Strict (all positives) | Strict (non-context) | Strict (context) |
|---|---|---|---|
| Cloud | 50/77 = 64.9% | **40/61 = 65.6%** | 10/16 = 62.5% |
| Local | 13/77 = 16.9% | 13/61 = 21.3% | 0/16 = 0% |
| Control | 13/77 = 16.9% | 13/61 = 21.3% | 0/16 = 0% |

Cloud per-category (non-context): system 90%, browser 100%, filesystem 80%,
media 70%, documents 60%, spreadsheet 60%, **clipboard 30%**.

Context items are a documented **GAP**, not a pass: the selector has no
prior-turn channel. The cloud model recovered 10 of 16 from the request text
alone; the local model recovered none.

---

## 6. Failure taxonomy (cloud — the informative run)

| Class | Count |
|---|---|
| ok (correct capability) | 50 |
| ok_negative (correctly no L3) | 21 |
| **no_l3_decision_after_round_trip** | **12** |
| **deterministic_outranked_llm** | **10** |
| gate_rejected_or_deterministic_decline | 4 |
| wrong_capability_by_model | 3 |
| false_positive | 2 |

The two dominant failure modes are **not** model weakness:

- **`deterministic_outranked_llm` (10).** The deterministic/regex layer
  answered instantly (0.0 s) with a wrong capability and the LLM was never
  consulted. Examples: `clipboard.paste` → `gui.paste_text` (×3),
  `media.previous` → `media.play_pause` (×2), `document.transform` →
  `file.copy`, `folder.open` → `file.open`, `screen.capture` → `file.copy`.
- **`no_l3_decision_after_round_trip` (12).** The model was called and the
  request still ended at Level 1. Split 6 non-context / 6 context.

**Expectation-equivalence finding:** 1 item (`filesystem.search` expected,
`file.search` returned) differs only by a near-identical registry twin —
`"Search accessible filesystem locations"` vs
`"Search accessible filesystem locations for matching files"`. Both exist and
are semantically the same capability. Strict scoring counts it wrong; the
acceptable column does not absorb it because no `accept` set was declared.
Worth one point.

**Local run:** 61 items produced genuine 190 s round-trips and **zero** of
them yielded a usable shortlist. The 7B model reliably returns a stage-one
candidate list containing no valid canonical capability id. The local model
contributed nothing beyond the deterministic layer.

---

## 7. Rules-audit re-check

**CLEAN.** Re-run after all measurement steps: overlap **0 significant**
(7 incidental generic 3-grams), legacy reuse PASS, banned frames PASS,
expectation ids PASS, composition PASS, `seal_ready` True. Seal hash
re-verified unchanged. Nothing added during Steps 0–1 introduced overlap.

---

## 8. Regression

```
python -m pytest -q -p no:cacheprovider
2175 passed, 60 warnings in 1356.79s
```

Requirement ≥ 2,175 — **met**, zero regressions.

---

## 9. Corrections to prior claims

1. The 2026-09-26 corpus was contaminated twice (registry-description
   provenance, then 12 of its phrases used as few-shot examples). Never
   generalisation evidence.
2. `gate: "PASS"` meant *admitted to the LLM*, not *correct*.
3. "75% sits above 78.7%" was written backwards.
4. "Scored once" was false for the 2026-09-26 corpus. `final3` **was** scored
   exactly once per configuration.
5. Preconditions are declared but not enforced — a roadmap task 3 signal
   that does not work.
6. The approval gate is curated, not risk-derived.

---

## 10. What the numbers mean

The capable model, routed correctly, reaches **65.6%** on held-out,
hand-written, never-tuned wording. The bar is 75%. The gap is not primarily
the model's competence: **22 of 61 non-context misses happen before or
despite the model** — 10 are pre-empted by the deterministic layer answering
instantly with a wrong capability, and 12 end at Level 1 despite a completed
round-trip.

Two concrete, code-level causes are now measured and reproducible:

1. **Precedence.** The deterministic path wins instantly and the LLM is
   never asked. This is the single largest correctable bucket (10 items,
   ~16 points of headroom).
2. **Post-round-trip discard.** 12 requests receive a model answer and still
   reach Level 1. That is the same class of bug as the conversational-guard
   pre-emption fixed earlier, and it is the next thing to trace.

Clipboard at 30% is a category-specific weakness: three near-identical
`gui.*` vs `clipboard.*` paste/typing intents that the deterministic layer
resolves before the model sees them.

---

## Phase 3 — Final Sign-Off

```
Date: 2026-09-30

final3 SHA-256 (confirmed unchanged):
  785b68217389b260a9c0999519afacc1c225d728444ad5e5a2b8cde37f07fe24
  (Note: the directive's copy of this string is 63 chars, missing the
   trailing '4'. The file's digest recomputes from its own content.)

Precondition-gap decision: (B) measured WITH the gap, fix afterward.
  Stated in the artifact before measurement. The gap is live in these
  numbers and contributes to the document.transform miss.

Resolved models confirmed:
  cloud = openai/gpt-oss-120b  (health OK, 3359 ms)
  local = qwen2.5:7b          (health OK, 32328 ms cold, native endpoint)

Cloud result: strict 50/77 = 64.9% [CI 53.8-74.7]
              non-context 40/61 = 65.6%
              FP 2/25 = 8.0% [CI 2.2-25.0]
              vs control: +48.0 points (>= 20 required) MET
              validity: clean - determinism 5/5, 0 errors, no starvation,
              16 of 20 sub-second no-answers are correct gate blocks

Local result: strict 13/77 = 16.9% [CI 10.1-26.8]
              non-context 13/61 = 21.3%
              FP 1/25 = 4.0% [CI 0.7-19.5]
              vs control: +0.0 points (>= 20 required) NOT MET
              validity: clean - determinism 5/5, 0 errors, 3.4h of real
              190s round-trips; model yielded zero usable shortlists

Deterministic control: strict 13/77 = 16.9%, FP 1/25 = 4.0%

Pre-registered bar: strict >= 75% AND FP <= 5%
  cloud: FAILS both (64.9% < 75%; 8.0% > 5%)
  local: FAILS (16.9% < 75%)

Context items: GAP, reported separately, 16 items.
  No prior-turn channel exists. Cloud recovered 10/16 from the request
  text alone; local 0/16. Not folded into the headline.

Failure taxonomy (cloud): 50 ok / 21 ok_negative / 12 no-decision-after-
  round-trip / 10 deterministic-outranked-LLM / 4 gate-or-decline /
  3 wrong-capability-by-model / 2 false-positive.
  22 of 61 non-context misses occur before or despite the model.

Rules audit re-check: CLEAN. 0 significant overlaps; seal unchanged.

Regression: 2175 passed, 60 warnings (requirement >= 2175), 0 regressions.

VERDICT: NOT CLOSED

This verdict applies to Phase 3 only.
```

**Why not closed:** the pre-registered bar is 75% strict with FP ≤5%. The best
valid configuration — a real 120B model, correctly verified, on a properly
sealed human-written corpus — reached **64.9%** with **8.0%** false positives.
It clears the required margin over the deterministic control by a wide
+48 points, so the LLM selector is doing real work, but it does not clear the
bar and Phase 3 does not close on a miss. The measurement is now sound; the
remaining ~10 points are concentrated in two code-level routing defects
rather than in model capability.