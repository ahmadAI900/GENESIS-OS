"""
Phase 3 final4 scorer (cloud only).

Run:  python phase3_final4_score.py            # full run
      python phase3_final4_score.py --control  # deterministic only

Aggregate-only. Prints no per-item rows while the run is in
progress, and never loads item content into stdout.

Two harness defects in phase3_final3_score.py are fixed here,
because they corrupted final3's reported denominators rather than
merely its presentation:

  1. KIND WAS CLASSIFIED FROM `expect`, NOT FROM `prior`. A context
     item with expect=None was therefore counted as a NEGATIVE. That
     is why final3 reported 25 negatives when its corpus holds 23.
     Here `prior` decides context, first and unconditionally, so
     context and negatives partition cleanly.

  2. THE CONTROL RUN WAS SCORED WITH A DIFFERENT CODE PATH. final3's
     control simply skipped the semantic layer inside one loop; the
     13/77 it produced is not comparable to the cloud run, which
     executed the full routing path. Here the control is a SEPARATE
     MODE of the same harness over the same items, so the
     margin-over-control comparison is like-for-like.

Pre-registered bar, unchanged: strict >= 75% AND FP <= 5% AND
>= 20 percentage points over the fresh deterministic control.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SEAL = BACKEND / "phase3_v4_SEALED.json"
DIGEST = BACKEND / "phase3_v4_SEAL_DIGEST.txt"
EXPECTED_SHA = (
    dict(
        line.split(" ", 1)
        for line in DIGEST.read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )["final4_sha256"].strip()
)

MODE = "control" if "--control" in sys.argv else "cloud"
PACE_SECONDS = 6.0


def wilson(k: int, n: int) -> List[float]:
    if n == 0:
        return [0.0, 0.0]
    z = 1.959964
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (
        z
        * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
        / denom
    )
    return [
        round(100 * max(0.0, centre - half), 1),
        round(100 * min(1.0, centre + half), 1),
    ]


def verify_seal() -> List[Dict[str, Any]]:
    """Refuse to score anything that is not the sealed final4."""
    obj = json.loads(SEAL.read_text(encoding="utf-8"))
    ordered = sorted(
        obj["final4"], key=lambda i: json.dumps(i, sort_keys=True)
    )
    digest = hashlib.sha256(
        json.dumps(ordered, indent=2, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if digest != EXPECTED_SHA:
        raise SystemExit(
            f"SEAL MISMATCH\n  expected {EXPECTED_SHA}\n  actual   {digest}"
        )
    if obj["final4_item_count"] != len(ordered):
        raise SystemExit("final4_item_count disagrees with content")
    print(f"[seal] verified  final4_sha256 {digest}")
    print(f"[seal] items     {len(ordered)}")
    return ordered


def build_engine():
    for line in (BACKEND / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    if MODE == "cloud":
        os.environ["GENESIS_LLM_MODES"] = "cloud"
        os.environ["GENESIS_LLM_TIMEOUT_SECONDS"] = "300"
        os.environ["GENESIS_LLM_CALL_TIMEOUT"] = "120"
        os.environ["GENESIS_LLM_TOTAL_BUDGET"] = "180"
        os.environ["PACE_SECONDS"] = str(PACE_SECONDS)
    else:
        # Deterministic only: no semantic layer at all.
        os.environ["GENESIS_LLM_MODES"] = ""

    from ai.ai_engine import AIEngine
    from ai.providers import GroqProvider
    from agents.workflow_decision import WorkflowDecisionEngine
    from genesis_os.capability_resolver import CapabilityResolver

    ai = AIEngine()
    if MODE == "cloud":
        ai._providers = [
            p for p in ai._providers if isinstance(p, GroqProvider)
        ]
        ai._provider_by_name = {
            name: provider
            for name, provider in ai._provider_by_name.items()
            if isinstance(provider, GroqProvider)
        }
        print(f"[model] {ai._providers[0].model_id} via Groq")
        print(f"[model] call timeout 120s, total budget 180s")
    else:
        print("[model] deterministic only, no LLM")
    engine = WorkflowDecisionEngine(
        ai_engine=ai, capability_resolver=CapabilityResolver()
    )

    if MODE == "control":
        # Setting GENESIS_LLM_MODES="" is NOT sufficient. The
        # deterministic layer calls the semantic resolver internally
        # (the conversational guard in _detect_os_intent), so the
        # control run still reached the model and took hours.
        # Removing the resolver makes _try_semantic_intent_resolution
        # return None immediately, which is what "deterministic only"
        # has to mean for the margin comparison to be like-for-like.
        engine._llm_resolver = None
        assert engine._llm_resolver is None

    return engine


def classify(item: Dict[str, Any]) -> str:
    """Context is decided by `prior`, never by the absence of an
    expectation. This is the fix for final3's 23/25 split."""
    if item.get("prior"):
        return "context"
    if not item.get("expect"):
        return "negative"
    return "positive"


def main() -> int:
    items = verify_seal()
    engine = build_engine()

    rows: List[Dict[str, Any]] = []
    print(
        f"[{MODE}] scoring {len(items)} items "
        f"(aggregate only, no per-item output)"
    )

    for n, item in enumerate(items, 1):
        kind = classify(item)
        started = time.monotonic()
        error = ""
        decision = None
        try:
            if MODE == "cloud":
                # ITEM 4: context items carry a `prior` field. It was
                # previously dropped here, which is exactly why the
                # context items scored as an automatic GAP -- the
                # pipeline had no channel and the harness never used
                # the field it already had.
                #
                # PLUMBING ONLY. The sealed corpus, the item
                # classification, the scoring, the thresholds and the
                # reported figures are all untouched; the single
                # change is that an existing item field is now passed
                # to the decision engine instead of discarded.
                decision = engine.decide(
                    item["phrase"],
                    prior_turn=item.get("prior"),
                )
            else:
                # Deterministic layer only, same normalisation the
                # cloud path uses.
                text = engine._normalize_text(item["phrase"])
                decision = engine._detect_os_intent(text)
                decision = (
                    engine._resolve_with_capability_control_plane(
                        decision
                    )
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - started

        got = (decision or {}).get("intent")
        level = (decision or {}).get("level")
        accept = item.get("accept") or (
            [item["expect"]] if item.get("expect") else []
        )
        rows.append({
            "i": n,
            "kind": kind,
            "category": item.get("category"),
            "expect": item.get("expect"),
            "accept": accept,
            "got": got,
            "level": level,
            "elapsed_s": round(elapsed, 2),
            "error": error,
        })
        if MODE == "cloud":
            time.sleep(PACE_SECONDS)

    # ---- aggregate -------------------------------------------------
    out: Dict[str, Any] = {
        "mode": MODE,
        "corpus": "final4",
        "final4_sha256": EXPECTED_SHA,
        "item_count": len(rows),
    }

    positives = [r for r in rows if r["kind"] == "positive"]
    non_context = positives
    context = [r for r in rows if r["kind"] == "context"]
    negatives = [r for r in rows if r["kind"] == "negative"]

    strict = acceptable = 0
    for row in positives:
        if row["got"] == row["expect"]:
            strict += 1
            acceptable += 1
        elif row["got"] in row["accept"]:
            acceptable += 1
        row["strict_pass"] = row["got"] == row["expect"]
        row["acceptable_pass"] = row["got"] in row["accept"]

    ctx_strict = sum(1 for r in context if r["got"] == r["expect"])
    false_pos = sum(1 for r in negatives if r["got"])
    errors = sum(1 for r in rows if r["error"])

    subsecond = sum(
        1 for r in rows
        if r["got"] is None and r["elapsed_s"] < 1.0 and MODE != "control"
    )
    real_calls = sum(1 for r in rows if r["elapsed_s"] >= 1.0)
    rate_429 = sum(1 for r in rows if "429" in r["error"])

    out.update({
        "positives_total": len(positives) + len(context),
        "positives_non_context": len(non_context),
        "positives_context": len(context),
        "negatives": len(negatives),
        "strict": strict,
        "strict_pct": round(100 * strict / len(non_context), 1) if non_context else 0.0,
        "strict_ci": wilson(strict, len(non_context)),
        "acceptable": acceptable,
        "acceptable_pct": round(100 * acceptable / len(non_context), 1) if non_context else 0.0,
        "acceptable_ci": wilson(acceptable, len(non_context)),
        "context_strict": ctx_strict,
        "context_strict_pct": round(100 * ctx_strict / len(context), 1) if context else 0.0,
        "false_positives": false_pos,
        "false_positive_pct": round(100 * false_pos / len(negatives), 1) if negatives else 0.0,
        "false_positive_ci": wilson(false_pos, len(negatives)),
        "subsecond_no_answer": subsecond,
        "real_round_trips": real_calls,
        "errors": errors,
        "rate_429": rate_429,
        "wall_clock_s": round(sum(r["elapsed_s"] for r in rows), 1),
    })

    out["by_category"] = {}
    for row in non_context:
        bucket = out["by_category"].setdefault(
            row.get("category") or "?", {"n": 0, "ok": 0}
        )
        bucket["n"] += 1
        if row["strict_pass"]:
            bucket["ok"] += 1

    print()
    print("=" * 74)
    print(f"  final4 RESULT — {MODE}")
    print("=" * 74)
    print(f"[{MODE}] items        {len(rows)} "
          f"(non-context {len(non_context)}, context {len(context)}, "
          f"negatives {len(negatives)})")
    print(f"[{MODE}] strict       {strict}/{len(non_context)} = "
          f"{out['strict_pct']}%  CI{out['strict_ci']}")
    print(f"[{MODE}] acceptable   {acceptable}/{len(non_context)} = "
          f"{out['acceptable_pct']}%  CI{out['acceptable_ci']}")
    print(f"[{MODE}] context      {ctx_strict}/{len(context)} = "
          f"{out['context_strict_pct']}% (reported separately)")
    print(f"[{MODE}] false pos    {false_pos}/{len(negatives)} = "
          f"{out['false_positive_pct']}%  CI{out['false_positive_ci']}")
    print(f"[{MODE}] sub-second no-answer {subsecond}")
    print(f"[{MODE}] real round trips     {real_calls}")
    print(f"[{MODE}] errors {errors}   429s {rate_429}")
    print(f"[{MODE}] wall clock  {out['wall_clock_s']}s")
    print()
    print("  per-category strict (non-context):")
    for cat, bucket in sorted(out["by_category"].items()):
        pct = round(100 * bucket["ok"] / bucket["n"], 1) if bucket["n"] else 0
        print(f"    {cat:14} {bucket['ok']:2}/{bucket['n']:<2} {pct:5}%")

    outfile = BACKEND / f"phase3_final4_{MODE}_RESULT.json"
    outfile.write_text(
        json.dumps({**out, "rows": rows}, indent=2), encoding="utf-8"
    )
    print()
    print(f"[{MODE}] wrote {outfile.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())