"""
Phase 3 Step 4 - official scoring runner for sealed final3.

HARD RULE: this runner prints AGGREGATE results only. Per-item
detail is written to a JSON file AFTER the whole run completes, so
no per-item final3 result can be observed mid-run.

It also never re-prints an item on failure, and never logs a phrase.

Usage:
    python phase3_final3_score.py <cloud|local|control> [--spotcheck]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(r"C:\Users\Muhammad\Desktop\gemini_cli\backend")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SEAL = BACKEND / "phase3_v3_SEALED.json"
EXPECTED_SHA = "785b68217389b260a9c0999519afacc1c225d728444ad5e5a2b8cde37f07fe24"

MODE = sys.argv[1] if len(sys.argv) > 1 else "control"
SPOTCHECK = "--spotcheck" in sys.argv


def load_env() -> None:
    for line in (BACKEND / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def wilson(successes: int, n: int, z: float = 1.96):
    """95% Wilson score interval."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (
        z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    )
    return (round(100 * max(0.0, centre - half), 1),
            round(100 * min(1.0, centre + half), 1))


def main() -> int:
    load_env()

    # Budget generous enough for a slow local model; the caller
    # overrides via env.
    os.environ.setdefault("GENESIS_LLM_TIMEOUT_SECONDS", "300")
    os.environ.setdefault("GENESIS_LLM_CALL_TIMEOUT", "120")
    os.environ.setdefault("GENESIS_LLM_TOTAL_BUDGET", "180")

    sealed = json.loads(SEAL.read_text(encoding="utf-8"))
    if sealed["final3_sha256"] != EXPECTED_SHA:
        print("ABORT: seal hash does not match the recorded value.")
        return 2

    items: List[Dict[str, Any]] = sealed["final3"]

    from agents.workflow_decision import WorkflowDecisionEngine
    from genesis_os.capability_resolver import CapabilityResolver

    model_id = None
    pacing = 0.0
    if MODE == "control":
        engine = WorkflowDecisionEngine(
            ai_engine=None, capability_resolver=CapabilityResolver()
        )
    else:
        from ai.ai_engine import AIEngine
        from ai.providers import GroqProvider, OllamaProvider

        ai = AIEngine()
        keep = {"cloud": GroqProvider, "local": OllamaProvider}[MODE]
        ai._providers = [p for p in ai._providers if isinstance(p, keep)]
        ai._provider_by_name = {
            n: p for n, p in ai._provider_by_name.items()
            if isinstance(p, keep)
        }
        if not ai._providers:
            print(f"ABORT: no provider for mode {MODE}")
            return 2
        model_id = ai._providers[0].model_id
        h = ai._providers[0].health_check()
        print(f"[{MODE}] resolved model: {model_id}")
        print(f"[{MODE}] health: available={h.available} "
              f"latency_ms={h.latency_ms} error={h.error}")
        if not h.available:
            print(f"ABORT: {MODE} provider unhealthy; not measuring.")
            return 2
        if MODE == "cloud":
            os.environ["GENESIS_LLM_MODES"] = "cloud"
            pacing = float(os.environ.get("PACE_SECONDS", "10"))
        else:
            os.environ["GENESIS_LLM_MODES"] = "local"
            os.environ["GENESIS_LLM_INFLIGHT_CAP"] = "1"
            pacing = 0.0
        engine = WorkflowDecisionEngine(
            ai_engine=ai, capability_resolver=CapabilityResolver()
        )

    # ---- classify WITHOUT printing any item -------------------
    positives = [i for i in items if i.get("expect")]
    negatives = [i for i in items if not i.get("expect")]
    context = [i for i in positives if i.get("prior")]

    print(f"[{MODE}] final3 items: {len(items)}  "
          f"positives={len(positives)} (context={len(context)})  "
          f"negatives={len(negatives)}")
    print(f"[{MODE}] NOTE: no per-item output until the run completes.")

    strict = acceptable = 0
    fp = 0
    rows: List[Dict[str, Any]] = []
    subsecond = 0
    errors = 0
    started = time.monotonic()

    for n, item in enumerate(items, 1):
        if pacing and n > 1:
            time.sleep(pacing)
        t0 = time.monotonic()
        try:
            decision = engine.decide(
                item["phrase"],
                # ITEM 4: plumbing only -- pass the prior turn
                # the item already carries instead of dropping it.
                prior_turn=item.get("prior"),
            )
            err = None
        except Exception as exc:
            decision, err = None, f"{type(exc).__name__}"
        dt = time.monotonic() - t0

        got = (decision or {}).get("intent")
        level = (decision or {}).get("level")
        is_context = bool(item.get("prior"))
        is_neg = not item.get("expect")

        if got is None and dt < 1.0 and MODE != "control":
            subsecond += 1
        if err:
            errors += 1

        row = {
            "i": n,
            "expect": item.get("expect"),
            "accept": item.get("accept") or (
                [item["expect"]] if item.get("expect") else []
            ),
            "got": got,
            "level": level,
            "elapsed_s": round(dt, 1),
            "error": err,
            "kind": ("context" if is_context else
                     "negative" if is_neg else "positive"),
            "category": item.get("category"),
        }
        if is_neg:
            if level == 3 or got is not None:
                fp += 1
                row["false_positive"] = True
        else:
            if got == item.get("expect"):
                strict += 1
                row["strict_pass"] = True
            if got in row["accept"]:
                acceptable += 1
                row["acceptable_pass"] = True
        rows.append(row)

        if n % 10 == 0 or n == len(items):
            print(f"  ... {n}/{len(items)}  elapsed={time.monotonic()-started:.0f}s")

    # ---- 5-item determinism spot-check -------------------------
    spot = None
    if SPOTCHECK and MODE != "control":
        print("[spotcheck] rerunning 5 scored items in isolation...")
        sample = [r for r in rows if r["kind"] == "positive"][:5]
        agree = 0
        detail = []
        for r in sample:
            idx = r["i"] - 1
            again = engine.decide(
                items[idx]["phrase"],
                prior_turn=items[idx].get("prior"),
            )
            got2 = (again or {}).get("intent")
            same = got2 == r["got"]
            agree += 1 if same else 0
            detail.append({"i": r["i"], "first": r["got"], "second": got2,
                           "identical": same})
            time.sleep(pacing)
        spot = {"items": 5, "identical": agree, "detail": detail}
        print(f"[spotcheck] identical on {agree}/5")

    # ---- write per-item detail only now ------------------------
    out = {
        "mode": MODE,
        "model_id": model_id,
        "final3_sha256": EXPECTED_SHA,
        "items_total": len(items),
        "positives": len(positives),
        "context_items": len(context),
        "negatives": len(negatives),
        "strict_correct": strict,
        "acceptable_correct": acceptable,
        "strict_pct": round(100 * strict / len(positives), 1) if positives else 0.0,
        "acceptable_pct": round(100 * acceptable / len(positives), 1) if positives else 0.0,
        "strict_ci": wilson(strict, len(positives)),
        "acceptable_ci": wilson(acceptable, len(positives)),
        "false_positives": fp,
        "fp_pct": round(100 * fp / len(negatives), 1) if negatives else 0.0,
        "fp_ci": wilson(fp, len(negatives)),
        "subsecond_noanswers": subsecond,
        "errors": errors,
        "wall_clock_s": round(time.monotonic() - started, 1),
        "determinism_spotcheck": spot,
        "results": rows,
    }
    path = BACKEND / f"phase3_final3_{MODE}_RESULT.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print()
    print(f"[{MODE}] strict      {strict}/{len(positives)} = "
          f"{out['strict_pct']}%  CI{out['strict_ci']}")
    print(f"[{MODE}] acceptable  {acceptable}/{len(positives)} = "
          f"{out['acceptable_pct']}%  CI{out['acceptable_ci']}")
    print(f"[{MODE}] false pos   {fp}/{len(negatives)} = "
          f"{out['fp_pct']}%  CI{out['fp_ci']}")
    print(f"[{MODE}] sub-second no-answers: {subsecond}   errors: {errors}")
    print(f"[{MODE}] wall clock: {out['wall_clock_s']}s")
    print(f"[{MODE}] wrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
