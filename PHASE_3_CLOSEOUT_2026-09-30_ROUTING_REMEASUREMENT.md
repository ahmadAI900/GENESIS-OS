# Phase 3 — Routing Defect Fixes and Remeasurement

**Date:** 2026-09-30
**Supersedes:** `PHASE_3_CLOSEOUT_2026-09-30.md` (the final3 measurement, archived)
**Corpus:** `backend/phase3_v4_SEALED.json` / `backend/phase3_v4_SEAL_DIGEST.txt`
**Results:** `phase3_final4_{cloud,control}_RESULT.json`

---

## 1. Verdict

**VERDICT: NOT CLOSED.**

`final4` is a clean, valid, correctly-provenanced re-measurement. The two
targeted routing fixes were real and they shrank both defect classes.
Neither eliminated them, and the run still fails the pre-registered bar on
both thresholds.

| Configuration | Strict | 95% Wilson CI | FP | 95% Wilson CI | Verdict |
|---|---|---|---|---|---|
| Cloud `openai/gpt-oss-120b` | **36/57 = 63.2%** | 50.2–74.5 | **4/20 = 20.0%** | 8.1–41.6 | **FAILS both** |
| Deterministic control | 10/57 = 17.5% | 9.8–29.4 | 1/20 = 5.0% | 0.9–23.6 | — |

Bar, unchanged: strict ≥75% **and** FP ≤5% **and** ≥20 points over control.
Strict **63.2% < 75% FAIL**. FP **20.0% > 5% FAIL**. Margin **+45.7 points
≥ 20 PASS**.

Context (5 items, reported separately, never folded into the headline):
**1/5 = 20.0%**.

### Seal verification

Read from `phase3_v4_SEAL_DIGEST.txt` and independently recomputed from the
sealed content, never retyped:

```
final4_sha256  a74aa1959e172d144a6737d6f3654ac9cdb78a76f94441783af4219641a7577c
recorded in digest file   : a74aa1959e172d144a6737d6f3654ac9cdb78a76f94441783af4219641a7577c
recomputed from content   : a74aa1959e172d144a6737d6f3654ac9cdb78a76f94441783af4219641a7577c
MATCH                     : True
```

The digest covers `sha256(json.dumps(final4, indent=2, sort_keys=True))`.
It is **not** the seal file's byte digest (`37ed596f…`, a different value,
now documented as such in the seal itself).

**Correction to the previous artifact.** It claimed "the file's digest
self-verifies against its own content." That was wrong about the
mechanism. `final3_sha256` is the digest of the canonical `final3`
serialization, not of the file's bytes — the file's byte digest is
`5b15c617…`. The seal was intact and the conclusion held; the reasoning
was false. `phase3_v3_audit.json` also stored **no** hash at all, so the
digest was asserting itself inside the only file it protected. `final4`
fixes this: the digest is written to its own file, whose bytes are
`1c67635c…`.

---

## 2. Step 1a — deterministic answers outranking the model

**Fixed, partially. The fix is narrower than the defect.**

The rule: a deterministic match is overruled only when it is unanchored
(no target, no named application) **and** contradicted by its own family —
some sibling in the same domain whose description overlaps the request
strictly more.

```
go back to the previous track    hint media.play_pause 0.000
                                media.previous        0.667  -> overruled
write hello world               hint gui.type_text    0.000
                                no gui sibling beats it -> stands
```

**The first attempt was unsafe and the suite caught it.** Treating every
unanchored family match as a hint let the model overwrite a correct
deterministic answer: `"write hello world"` went `gui.type_text` →
`document.create_txt`, breaking a pinned Phase 0 forensic regression
guard. The contradiction clause exists because of that regression.

11 regression tests, all synthetic, exercising the mechanism rather than
any corpus phrase — including the mirror case that the model is *never
called* when the hint is its family's best match.

**Why it did not fully generalize** (see §5): 5 of the 6 surviving
class-1a misses are **cross-domain** — `gui` vs `clipboard`, `folder` vs
`file`, `document` vs `file`, `system` vs `application`. A within-family
contradiction test cannot fire on those by construction. The remaining one
(`media.previous` → `media.play_pause`, same domain) did not fire because
the deterministic match carried an anchor, and the rule treats any anchor
as authoritative.

---

## 3. Step 1b — no L3 decision after the round trip

**Not a discard bug, and not fixed. Reported as an open defect.**

The suspected site was `workflow_decision.py:3108`, which discards a
decision when the resolver returns non-`RESOLVED`. It is **unreachable**:

- **0/141** registered capabilities resolve non-`RESOLVED`.
- **0/20** validated `dev3` semantic answers hit that branch.

So the final3 items in this class were the model returning **no usable
shortlist** — the same failure the 7B local model hit 61/61 times. Not a
code defect.

**The real LLM-blocking defect is the `looks_actionable` cost gate**,
which rejects **5/29 = 17.2%** of unambiguously actionable `dev3` requests
before any model call. Inverting its default to "ask the model" fixed all
five — **and broke 5 pinned tests** guarding a live-discovered
false-positive incident. It was reverted.

The reason is now measured, and it is not a missing word list. These nine
strings are **byte-identical across all four lexical probes**:

```
"you make me happy"          domain=F verb=F hint=F smalltalk=F
"can you fire up chrome..."  domain=F verb=F hint=F smalltalk=F
```

A lexical gate asked to make a semantic distinction is overfitting by
construction. Fixing it safely needs a **semantic grounding requirement** —
believe a gate-overridden answer only when the chosen capability is grounded
in the request — not another whitelist. That is tracked, not absorbed, and
it is the single largest remaining lever.

---

## 4. Step 1c — near-twin accepted as configuration

`file.search` and `filesystem.search` both exist in the registry
("Search accessible filesystem locations" / "Search accessible filesystem
locations for matching files"). Both `file.search` items now declare
`accept: ["file.search", "filesystem.search"]`. No resolver change.

---

## 5. Remeasurement and defect recurrence

`final4`: 82 items = 62 positives (57 non-context + 5 context) + 20
negatives.

### Did the fixes generalize? Partially.

| Defect class | final3 | final4 | Movement |
|---|---|---|---|
| 1a `deterministic_outranked_llm` | 10 / 61 misses (16.4%) | **6 / 57 (10.5%)** | reduced, not eliminated |
| 1b `no_l3_decision_after_round_trip` | 12 / 61 misses (19.7%) | **6 / 57 (10.5%)** | halved, not eliminated |

### Full taxonomy (cloud)

| Class | Count |
|---|---|
| ok | 36 |
| ok_negative | 16 |
| no_l3_decision_after_round_trip (**1b**) | 6 |
| deterministic_outranked_llm (**1a**) | 6 |
| wrong_capability_by_model | 5 |
| gate_or_deterministic_decline | 4 |
| context_miss (GAP) | 4 |
| false_positive | 4 |

The 6 surviving **1a** misses:

```
0.0s  expected clipboard.paste       got gui.paste_text
0.0s  expected document.transform    got file.copy
0.0s  expected folder.move           got file.move
0.0s  expected media.previous        got media.play_pause
0.0s  expected spreadsheet.rank      got file.search
0.7s  expected system.open_settings  got application.open
```

Five of six are cross-domain; the sixth is same-domain but anchored.

### Per-category strict (non-context)

| Category | Strict |
|---|---|
| system | 5/6 = 83.3% |
| documents | 4/5 = 80.0% |
| browser | 6/8 = 75.0% |
| media | 4/6 = 66.7% |
| clipboard | 3/5 = 60.0% |
| filesystem | 3/5 = 60.0% |
| spreadsheet | 3/5 = 60.0% |
| gui | 4/8 = 50.0% |
| application | 4/9 = 44.4% |

`application` is the weakest at 44.4%, dominated by the
`application.focus` vs `application.open` confusion (the model reads
"switch over to my terminal tab" and "bring up the text editor" as
`application.open`).

### False positives went UP, and the reason is partly my own corpus

FP is **4/20 = 20.0%** against final3's 2/25 = 8.0%. This is **not a
straight comparison**, and the difference is partly a corpus-design
weakness of mine:

```
1.7s  got web.research      "how did the match end on saturday"
4.4s  got web.research      "who wrote the book frankenstein"
5.9s  got process.inspect   "why does my program take so long to start up"
0.0s  got gui.type_text     "write a short toast for my best friends wedding"
```

The 20 negatives were agent-drafted in a single pass and I did **not** hold
them to the same adversarial standard as final3's. Three of the four are
knowledge or advice questions that `looks_actionable` admits — the same
gate defect from §3, now visible on an easier set. The 8.0% vs 20.0%
comparison should not be read as a system regression; the honest reading is
that final4's negative set is harsher and less vetted.

---

## 6. Validity

| Check | Result |
|---|---|
| Seal verified before scoring | yes, digest from independent file |
| Determinism spot-check | **5/5 identical** |
| Harness errors | 0 |
| Rate limits (429) | 0 |
| Items with a genuine round trip | 36 |
| Sub-second no-answers | 20, **all explained**: 12 correct negative blocks, 4 gate-blocked positives, 4 gate-blocked context |
| Unexplained sub-second no-answers | **0** |
| Wall clock | 264.3 s |

Two harness defects were fixed first, because they corrupted final3's
reported numbers rather than just its presentation:

1. **Kind was classified from `expect`, not `prior`.** A context item with
   `expect=None` was counted as a negative. That is why final3 reported
   25 negatives when its corpus holds 23. `final4` has **0** context items
   with `expect=None`, and the denominators now partition cleanly
   (57 + 5 + 20 = 82).
2. **The control ran a different code path.** Setting
   `GENESIS_LLM_MODES=""` was not enough — the deterministic layer calls the
   semantic resolver internally through the conversational guard, so the
   first control attempt still reached the model and ran for hours. The
   resolver is now removed outright. The control is a separate mode of the
   same harness over the same items, so the margin comparison is
   like-for-like. Control shows **0 round trips, 0.3 s**.

---

## 7. final4 provenance

**Composition, stated exactly:**

| Source | Count |
|---|---|
| dev3 carryover (never scored), hand-written | 22 |
| dev3 carryover, assistant-drafted | 7 |
| new, hand-written by project owner | 37 |
| new, assistant-drafted | 6 |
| negatives, agent-drafted | 20 |
| context, agent-drafted | 8 |

- **0 scored `final3` items reused.** Verified programmatically at import:
  the v4 corpus raises `RuntimeError` if any dev3 carryover phrase appears
  in final3, and `validate_composition` re-checks the full corpus.
- **All 29 dev3 items retained** across dev4 + final4; 25 of them are in
  the scored final4.
- `dev3` is **diagnosis-exposed, not untouched**: 6 of its phrases were read
  during the Step 1b investigation. They were never scored, and no fix in
  this phase encodes a dev3 phrase (the one fix that analysis suggested was
  tried and reverted). Stated rather than glossed.
- All 43 new positives validated against the live registry: **0 invalid
  `expect` ids** across 32 distinct capabilities.
- 10 items were reworded after the overlap scan — 5 genuine leaks into text
  the model reads (including `selection_boundaries`, the strongest kind),
  5 function-word or regex-literal artifacts. Reworded, not forced through;
  the pinned rule was not relaxed. Final scan: **0 significant**, 3
  incidental generic 3-grams.

**Split fix.** The v3 sealer used a prefix slice, which is why dev3 was
100% application/browser/gui. Repeating that on v4 would have left final4
with **zero `gui` items and one `application` item** — two whole capability
domains untested. v4 uses a **stratified** split, ~25% per category, so
dev4 is 2 items from each of the 9 categories and final4 covers all 9
(57 non-context positives across 9 categories).

**Audit:** legacy-reuse PASS (0), banned-frames PASS (0), overlap PASS
(0 significant), expectation-ids PASS (0), composition PASS
(80 positives / 59 hand-written / 20 negatives / 8 context), `seal_ready`
True.

---

## 8. Regression

```
python -m pytest -q -p no:cacheprovider
2186 passed, 60 warnings in 10522.44s
```

Requirement ≥2,175 — **met**, zero failures. Baseline 2,175 + 11 new tests.
This run was taken **after the last production change** (the refined 1a
rule). The v4 files added afterwards are standalone measurement scripts that
no test imports.

**Honest cost note:** suite runtime went from 22m36s to **2h55m**. The
override now routes genuinely-ambiguous cases to the real model inside
tests that previously short-circuited deterministically. That is a real
consequence of the fix, not an accident.

---

## 9. Corrections carried forward

1. The previous artifact's "the file's digest self-verifies against its own
   content" was wrong about the mechanism. Corrected in §1.
2. `phase3_v3_audit.json` stored no digest. `phase3_v4_audit.json` now
   complements an independently written digest file.
3. final3's negative denominator (25) was wrong (23 is correct).
4. final3's control was not like-for-like with its cloud run.
5. final3's context items were each present twice (9 items, 18 rows)
   because the v3 sealer appended context that `all_positives()` already
   contained. Not repeated in v4.
6. `looks_actionable` remains an unfixed accuracy ceiling of 17.2% on
   held-out dev3, blocked behind a false-positive guard that a lexical gate
   cannot resolve.

---

## Phase 3 — Final Sign-Off

```
Date: 2026-09-30

CORPUS
  final4_sha256 a74aa1959e172d144a6737d6f3654ac9cdb78a76f94441783af4219641a7577c
  recorded in phase3_v4_SEAL_DIGEST.txt, independently recomputed from the
  sealed content: MATCH.
  82 items = 62 positives (57 non-context + 5 context) + 20 negatives.
  0 scored final3 items reused; all 29 dev3 carryover items retained.
  Hand-written positives: 59 of 72. Agent-drafted: negatives + context.

FIXES
  1a deterministic-outranks-LLM: FIXED, PARTIAL. Override fires only when
     the deterministic hint is unanchored AND contradicted by its own
     family. 10 -> 6 misses. 11 synthetic regression tests. A first,
     broader version broke a pinned Phase 0 guard and was narrowed.
  1b no-L3-after-round-trip: NOT FIXED, and not the defect it appeared to
     be. The suspected discard is unreachable (0/141 registered ops,
     0/20 dev3 answers). The real blocker is the looks_actionable cost
     gate, 17.2% of held-out actionable requests, provably inseparable
     from the conversational set it must protect. Inversion tried,
     broke 5 pinned tests, reverted. Open.
  1c file.search/filesystem.search: accept set declared. No code change.

RESULT (bar unchanged: strict >=75%, FP <=5%, margin >=20 over control)
  cloud   openai/gpt-oss-120b: strict 36/57 = 63.2% [CI 50.2-74.5]
                                 FP    4/20 = 20.0% [CI 8.1-41.6]
                                 margin over control +45.7  (>=20 MET)
  control deterministic only:    strict 10/57 = 17.5% [CI 9.8-29.4]
                                 FP    1/20 =  5.0%
  strict 63.2% < 75%   FAIL
  FP    20.0% >  5%    FAIL
  context 1/5 = 20.0%  GAP, reported separately, no prior-turn channel

VALIDITY
  determinism 5/5 identical; 0 errors; 0 rate limits;
  20 sub-second no-answers all explained; 0 unexplained.

DEFECT RECURRENCE
  1a: 6 of 57 misses still deterministic-outranked. 5 of 6 are
      cross-domain, which a within-family test cannot reach.
  1b: 6 of 57 misses still reach Level 1 after a completed round trip.
  Both reduced. Neither eliminated. The fix did not fully generalize.

AUDIT
  legacy reuse PASS, banned frames PASS, overlap PASS (0 significant),
  expectation ids PASS, composition PASS, seal_ready True.

REGRESSION
  2186 passed, 0 failed (>= 2175 required). Runtime 22m36s -> 2h55m.

VERDICT: NOT CLOSED

This verdict applies to Phase 3 only.
```

**Why not closed.** The bar is 75% strict with FP ≤5%. The best valid
configuration reached **63.2%** with **20.0%** false positives. Both
targeted defect classes shrank — 1a from 10 to 6, 1b from 12 to 6 — which
is real, measurable progress and is why the remaining work is now
narrow rather than open-ended. But neither class is gone, the run is worse
than the bar on both thresholds, and one threshold (FP) is worse than the
previous measurement.

Three things remain, in order of expected value:

1. **`looks_actionable` semantic grounding.** The 17.2% ceiling and the
   false positives are the same defect. This is the largest lever.
2. **Cross-domain arbitration.** 5 of 6 surviving 1a misses are
   `gui`/`clipboard`, `folder`/`file`, `document`/`file`, `system`/
   `application` confusions. A within-family test cannot see them; this
   needs sibling-domain boundary reasoning.
3. **`application.focus` vs `application.open`.** The weakest category
   (44.4%), and the failure is the model choosing, not a routing
   pre-emption.