"""
Phase 3 Item 2 -- scoped false-positive REMEASUREMENT.

This is NOT a new `final5`. It scores the current system, with Items 3
and 4 in place, against the vetted negative set ONLY. Nothing else is
measured, no sealed corpus is touched, and no score is recomputed for
anything that was already scored.

CLASSIFICATION IS DELIBERATELY DIFFERENT FROM `phase3_final4_score`
--------------------------------------------------------------------
`final4`'s `classify()` files any item carrying a `prior` as CONTEXT.
That is correct for the sealed corpora, where a `prior` accompanies an
item that IS expected to resolve. It is wrong for this set: every item
here is a NEGATIVE, including the four that carry a prior precisely so
the context channel gets its chance and must still decline. So this
scorer classifies on the absence of `expect` -- which is how `final3`
did it -- and reports the prior-carrying family separately, so the cost
of Item 4's discriminativeness widening is directly legible rather than
averaged away.

Modes
-----
`cloud`      the real pinned cloud model, one score per item, run once.
`deterministic`  the regex layer only, for attribution.

Both record per-item tier, intent and timing.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.capability_resolver import CapabilityResolver
from genesis_os.llm_intent_resolver import LLMIntentResolver

import phase3_negatives_vetted_corpus as CORPUS

MODE = os.environ.get("PHASE3_FP_MODE", "cloud").strip().lower()
OUT = BACKEND / "phase3_fp_remeasure.json"

# NO ENVIRONMENT MUTATION AT IMPORT TIME.
#
# This module is imported by `test_phase3_fp_negative_rigor.py` for its
# `wilson()` helper. Setting `GENESIS_LLM_MODES` at module scope made
# that import reconfigure the whole pytest process, which broke
# `test_phase3_trigger_hardening` in the fast suite -- the same
# class of leak as ledger item 19, committed here deliberately and then
# caught. The live configuration is applied in `configure_live_env()`
# at run time only.


def configure_live_env() -> None:
    """The documented live configuration from the Phase 3 closeout."""
    os.environ["GENESIS_LLM_MODES"] = "cloud"
    os.environ["GENESIS_LLM_CALL_TIMEOUT"] = "60"
    os.environ["GENESIS_LLM_TOTAL_BUDGET"] = "120"
    os.environ["GENESIS_LLM_INFLIGHT_CAP"] = "2"


def wilson(successes: int, total: int, z: float = 1.96) -> Dict[str, Any]:
    """95% Wilson score interval, the format used for every Phase 3 rate."""
    if total <= 0:
        return {"pct": 0.0, "lo": 0.0, "hi": 0.0}
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    spread = (
        z
        * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
        / denom
    )
    return {
        "pct": round(100 * p, 1),
        "lo": round(100 * max(0.0, centre - spread), 1),
        "hi": round(100 * min(1.0, centre + spread), 1),
    }


def build_engine():
    if MODE == "deterministic":
        engine = WorkflowDecisionEngine()
        engine._llm_resolver = None
        return engine
    from ai.ai_engine import AIEngine

    # Applied here, at run time, never at import time.
    configure_live_env()
    return WorkflowDecisionEngine(
        ai_engine=AIEngine(), capability_resolver=CapabilityResolver()
    )


def main() -> int:
    if MODE == "cloud":
        configure_live_env()
    engine = build_engine()
    items = CORPUS.all_negatives()

    print(f"mode              : {MODE}")
    if MODE == "cloud":
        print(f"model             : {os.environ.get('OPENROUTER_MODEL')}")
        print(f"modes             : {LLMIntentResolver._backend_modes()}")
    print(f"negatives scored  : {len(items)}")
    print(f"  with a prior    : {len(CORPUS.with_context())}")
    print(f"  without a prior : {len(CORPUS.without_context())}")
    print()

    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        tier = LLMIntentResolver.lexical_actionability(item["phrase"])
        started = time.monotonic()
        error = ""
        decision: Optional[Dict[str, Any]] = None
        try:
            if MODE == "deterministic":
                decision = engine._resolve_with_capability_control_plane(
                    engine._detect_os_intent(
                        engine._normalize_text(item["phrase"])
                    )
                )
            else:
                decision = engine.decide(
                    item["phrase"], prior_turn=item.get("prior")
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - started

        intent = (decision or {}).get("intent")
        level = (decision or {}).get("level")
        false_positive = bool(intent)

        rows.append({
            "n": index,
            "phrase": item["phrase"],
            "prior": item.get("prior"),
            "category": item["category"],
            "lexical_tier": tier,
            "intent": intent,
            "level": level,
            "false_positive": false_positive,
            "seconds": round(elapsed, 1),
            "error": error,
        })
        flag = "FALSE POSITIVE" if false_positive else "declined"
        prior_note = "  [prior supplied]" if item.get("prior") else ""
        print(f"{index:3d}. {flag:14s} tier={tier:10s} "
              f"{str(intent)!r:26s} {elapsed:5.1f}s")
        print(f"     {item['phrase']!r}{prior_note}")
        if error:
            print(f"     error: {error}")

    total = len(rows)
    fps = sum(1 for r in rows if r["false_positive"])
    with_prior = [r for r in rows if r["prior"]]
    without_prior = [r for r in rows if not r["prior"]]

    print()
    print("=" * 78)
    print(f"MODE {MODE.upper()} -- FALSE POSITIVES OVER VETTED NEGATIVES")
    print("=" * 78)
    print(f"overall           : {fps}/{total} = "
          f"{wilson(fps, total)['pct']}%  "
          f"CI [{wilson(fps, total)['lo']}-{wilson(fps, total)['hi']}]")
    if with_prior:
        w = wilson(sum(1 for r in with_prior if r["false_positive"]),
                   len(with_prior))
        print(f"with a prior      : "
              f"{sum(1 for r in with_prior if r['false_positive'])}"
              f"/{len(with_prior)} = {w['pct']}%  "
              f"CI [{w['lo']}-{w['hi']}]")
    if without_prior:
        w = wilson(sum(1 for r in without_prior if r["false_positive"]),
                   len(without_prior))
        print(f"without a prior   : "
              f"{sum(1 for r in without_prior if r['false_positive'])}"
              f"/{len(without_prior)} = {w['pct']}%  "
              f"CI [{w['lo']}-{w['hi']}]")
    print()
    print("by lexical tier:")
    for tier in sorted({r["lexical_tier"] for r in rows}):
        group = [r for r in rows if r["lexical_tier"] == tier]
        n = sum(1 for r in group if r["false_positive"])
        print(f"  {tier:12s} {n}/{len(group)} false positives")
    print()
    print("by category:")
    for category in sorted({r["category"] for r in rows}):
        group = [r for r in rows if r["category"] == category]
        n = sum(1 for r in group if r["false_positive"])
        print(f"  {category:26s} {n}/{len(group)} false positives")

    report = {
        "mode": MODE,
        "model": (os.environ.get("OPENROUTER_MODEL") if MODE == "cloud"
                  else None),
        "total": total,
        "false_positives": fps,
        "overall": wilson(fps, total),
        "with_prior": wilson(
            sum(1 for r in with_prior if r["false_positive"]),
            len(with_prior),
        ),
        "without_prior": wilson(
            sum(1 for r in without_prior if r["false_positive"]),
            len(without_prior),
        ),
        "by_tier": {
            tier: wilson(
                sum(1 for r in rows
                    if r["lexical_tier"] == tier
                    and r["false_positive"]),
                sum(1 for r in rows if r["lexical_tier"] == tier),
            )
            for tier in sorted({r["lexical_tier"] for r in rows})
        },
        "by_category": {
            category: wilson(
                sum(1 for r in rows
                    if r["category"] == category
                    and r["false_positive"]),
                sum(1 for r in rows if r["category"] == category),
            )
            for category in sorted({r["category"] for r in rows})
        },
        "rows": rows,
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print("written:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())