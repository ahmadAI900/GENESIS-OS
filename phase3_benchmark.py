"""
Phase 3 held-out semantic routing benchmark.

Purpose
-------
Phase 3's acceptance question is NOT "is the resolver wired in".
It is: can Genesis map natural-language wording that no pattern
was written for onto the correct registered capability?

This harness measures that honestly and separates the three
things that are routinely conflated:

  1. deterministic_only  - no LLM at all. Proves the improvement
                           is not merely "we turned something on".
  2. llm_local           - the locally installed model.
  3. llm_cloud           - the cloud model, when reachable.

Methodology
-----------
Two disjoint sets, and the split matters:

  * DEV      - inspected and iterated against. Every tuning
               decision in Phase 3 was made while looking at DEV.
  * HELDOUT  - generated from the capability registry by
               surface transformation (paraphrase frame, politeness
               padding, register shift, typo injection, and an
               optional mixed-language frame). It is scored ONCE,
               at the end, and never used to choose a prompt, a
               threshold, or a configuration.

Equivalence classes
-------------------
Some capability families contain members whose descriptions are
byte-identical (document.summarize / document.summarize_intel).
A selector cannot be blamed for choosing the wrong twin, and
crediting a coin flip would be dishonest, so an item may declare
`accept` — a set of capability ids that all satisfy the request.
Scoring reports BOTH strict and acceptable accuracy.

Outputs a JSON record containing every iteration, not only the
final one.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# =========================================================
# ENVIRONMENT
# =========================================================

def load_env() -> None:
    env_path = BACKEND / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


# =========================================================
# DEV SET — inspected and tuned against
# =========================================================

DEV_ITEMS: List[Dict[str, Any]] = [
    # Wording the deterministic layer already handled; kept so a
    # regression in the LLM path cannot hide behind a net gain.
    {"phrase": "open notepad", "expect": "application.open"},
    {"phrase": "delete this file", "expect": "file.delete"},
    {"phrase": "lock my computer", "expect": "workstation.lock"},

    # Indirect / idiomatic wording.
    {"phrase": "what's eating up my disk space", "expect": "hardware.storage"},
    {"phrase": "how bright is my screen right now", "expect": "display.brightness_get"},
    {"phrase": "turn the sound down a bit", "expect": "volume.down"},
    {"phrase": "what is playing right now", "expect": "media.play_pause"},
    {"phrase": "stash this somewhere else", "expect": "file.move"},
    {"phrase": "get rid of this file for me", "expect": "file.delete"},
    {"phrase": "snap a picture of what is on screen", "expect": "screen.capture"},
    {"phrase": "close the thing I was just working on", "expect": "application.close"},
    {"phrase": "put these files in order for me", "expect": "folder.organize"},
    {"phrase": "clean out the recycle bin", "expect": "cleanup.empty_recycle_bin"},

    # Domain-boundary pairs: these are the cases a flat catalog
    # cannot decide, and they motivated SELECTION_BOUNDARIES.
    {"phrase": "grab the text from that webpage", "expect": "browser.extract"},
    {"phrase": "extract the text from this PDF", "expect": "document.read_intel"},
    {"phrase": "make this document into a PDF", "expect": "document.transform"},
    {"phrase": "turn the screen dimmer", "expect": "display.brightness_set"},
    {"phrase": "make it louder", "expect": "volume.up"},
    {"phrase": "search the web for recent news about AI", "expect": "browser.search"},
    {"phrase": "go to example.com", "expect": "browser.open_url"},
    {"phrase": "rename this folder to something sensible", "expect": "folder.rename"},
    {"phrase": "move this file to the desktop", "expect": "file.move"},
    {"phrase": "what time is it in Tokyo", "expect": "time.world_clock"},
    {"phrase": "calculate 15 percent of 3200", "expect": "math.evaluate"},

    # Anaphora.
    {"phrase": "copy this file to my downloads", "expect": "file.copy"},
    {"phrase": "compare the two versions of this contract",
     "expect": "document.compare",
     "accept": ["document.compare", "document.compare_intel"]},
    {"phrase": "summarize this Word document",
     "expect": "document.summarize",
     "accept": ["document.summarize", "document.summarize_intel"]},
]


# =========================================================
# HELDOUT SET — generated, never tuned against
# =========================================================

# Frames are generic surface transformations. They contain no
# capability-specific wording, so they cannot be fitted to the
# selector: the same frames are applied mechanically to every
# capability in the sample.
FRAMES: List[str] = [
    "{d}",
    "could you {d} for me",
    "i need you to {d}",
    "hey, {d} real quick",
    "can you {d}? thanks",
    "right now, {d}",
    "when you get a chance, {d}",
]

# Deliberate misspelling of the first content word, to check the
# selector is not doing exact-token matching.
TYPO_FRAMES: List[str] = [
    "{typo}",
    "please {typo} asap",
]

# Register shift: casual and terse.
CASUAL_FRAMES: List[str] = [
    "{d} pls",
    "yo {d}",
    "{d} thx",
]

# Optional mixed-language frame. Phase 3 treats multilingual as
# optional, so this is a small reported slice, not a gate.
MIXED_LANGUAGE_FRAMES: List[str] = [
    "por favor, {d}",
    "s'il vous plait, {d}",
]


def _typo(word: str) -> str:
    """Transpose two adjacent letters, a realistic human slip."""
    if len(word) < 4:
        return word
    i = len(word) // 2
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def build_heldout(
    sample_size: int = 40,
    seed: int = 20260926,
) -> List[Dict[str, Any]]:
    """
    Deterministically build the held-out set from the registry.

    Uses a fixed seed so the set is reproducible and auditable, and
    samples across categories rather than picking convenient
    capabilities.
    """

    from genesis_os.capability_registry import CapabilityRegistry

    rng = random.Random(seed)

    descriptors = [
        c
        for c in CapabilityRegistry.all()
        if c.description
        and c.availability.value == "available"
        and c.enabled
    ]

    by_category: Dict[str, List[Any]] = {}
    for descriptor in descriptors:
        by_category.setdefault(
            descriptor.category.value, []
        ).append(descriptor)

    categories = sorted(by_category)

    # Round-robin across categories for even coverage.
    chosen: List[Any] = []
    index = 0
    while len(chosen) < min(sample_size, len(descriptors)):
        category = categories[index % len(categories)]
        pool = by_category[category]
        if index // len(categories) < len(pool):
            chosen.append(pool[index // len(categories)])
        index += 1
        if index > sample_size * len(categories) + len(categories):
            break

    items: List[Dict[str, Any]] = []
    for position, descriptor in enumerate(chosen):
        directive = descriptor.description
        directive = directive[0].lower() + directive[1:]
        if not directive.endswith((".", "!", "?")):
            directive += " it"

        accept = [descriptor.capability_id]
        twin = f"{descriptor.capability_id}_intel"
        if (
            descriptor.capability_id in _INTEL_BASES
            and CapabilityRegistry.exists(twin)
        ):
            accept.append(twin)

        if position % 10 == 7:
            frames = TYPO_FRAMES
        elif position % 10 == 3:
            frames = CASUAL_FRAMES
        elif position % 10 == 5:
            frames = MIXED_LANGUAGE_FRAMES
        else:
            frames = FRAMES

        frame = frames[position % len(frames)]
        phrase = frame.format(
            d=directive,
            typo=_typo(directive.split()[0]) + directive[len(directive.split()[0]):],
        )

        items.append({
            "phrase": phrase,
            "expect": descriptor.capability_id,
            "accept": accept,
            "category": descriptor.category.value,
        })

    return items


_INTEL_BASES = {
    "document.summarize", "document.compare", "document.read",
    "spreadsheet.read", "spreadsheet.inspect",
}


# =========================================================
# SCORING
# =========================================================

def score(
    items: List[Dict[str, Any]],
    decide,
    label: str,
    pause_s: float = 0.0,
) -> Dict[str, Any]:
    """
    Run the benchmark and score strict vs acceptable accuracy.

    `decide` is called with the phrase and must return a dict (or
    None) shaped like a WorkflowDecisionEngine decision.

    `pause_s` inserts a fixed pause between items. The cloud
    provider enforces a rolling tokens-per-minute quota, and the
    enriched catalog prompt is ~5.4k tokens, so an unpaced batch
    drains the quota mid-run and silently measures rate-limit
    failures as routing failures. Pacing keeps the measurement
    about routing rather than about quota exhaustion.
    """

    rows: List[Dict[str, Any]] = []
    strict = 0
    acceptable = 0
    routed_l3 = 0
    elapsed_total = 0.0
    quota_errors = 0

    for index, item in enumerate(items):
        if pause_s and index:
            time.sleep(pause_s)
        started = time.monotonic()
        try:
            decision = decide(
                item["phrase"], prior=item.get("prior")
            )
            error = None
        except Exception as exc:  # a crash is a failure, not a skip
            decision = None
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - started
        elapsed_total += elapsed

        got = (decision or {}).get("intent")
        level = (decision or {}).get("level")

        is_strict = got == item["expect"]
        accept = item.get("accept") or [item["expect"]]
        is_acceptable = got in accept

        strict += 1 if is_strict else 0
        acceptable += 1 if is_acceptable else 0
        if level == 3:
            routed_l3 += 1

        rows.append({
            "phrase": item["phrase"],
            "expect": item["expect"],
            "accept": accept,
            "got": got,
            "level": level,
            "strict_pass": is_strict,
            "acceptable_pass": is_acceptable,
            "elapsed_s": round(elapsed, 2),
            "error": error,
        })

    total = len(items)

    # An item that returned NOTHING without an exception may still
    # be a provider rate-limit failure: LLMIntentResolver.resolve()
    # catches ProviderError internally and returns None, so a 429
    # is indistinguishable from "the model declined" by the time it
    # reaches this function. Counting an instant no-answer as a
    # routing failure would silently misreport an exhausted quota as
    # a capability-selection defect, which is exactly what happened
    # in the first cloud rerun.
    #
    # A sub-second no-answer is the signature: a real model call
    # cannot return "no capability" that fast. Those are counted
    # separately and excluded from the headline rate, because the
    # question "can this model select the right capability?" is not
    # answered by items the model was never allowed to see.
    unaided = [
        row for row in rows
        if row["got"] is None and not row["error"]
        and row["elapsed_s"] < 1.0
    ]
    measured = [row for row in rows if row not in unaided]
    m_total = len(measured)
    m_strict = sum(1 for row in measured if row["strict_pass"])
    m_acceptable = sum(
        1 for row in measured if row["acceptable_pass"]
    )

    return {
        "label": label,
        "total": total,
        "strict_correct": strict,
        "acceptable_correct": acceptable,
        "strict_pct": round(100.0 * strict / total, 1) if total else 0.0,
        "acceptable_pct": round(100.0 * acceptable / total, 1) if total else 0.0,
        "routed_level3": routed_l3,
        "quota_errors": quota_errors,
        "mean_elapsed_s": round(elapsed_total / total, 2) if total else 0.0,
        "suspected_quota_starved": len(unaided),
        "measured_total": m_total,
        "measured_strict_pct": (
            round(100.0 * m_strict / m_total, 1) if m_total else 0.0
        ),
        "measured_acceptable_pct": (
            round(100.0 * m_acceptable / m_total, 1) if m_total else 0.0
        ),
        "results": rows,
    }


# =========================================================
# CONFIGURATIONS
# =========================================================

def make_decider(mode: str):
    """
    Build a decide() function for one measurement configuration.

    deterministic_only deliberately passes NO ai_engine, reproducing
    the pre-Phase-3 production state.
    """

    from agents.workflow_decision import WorkflowDecisionEngine
    from genesis_os.capability_resolver import CapabilityResolver

    if mode == "deterministic_only":
        engine = WorkflowDecisionEngine(
            ai_engine=None,
            capability_resolver=CapabilityResolver(),
        )

        def decide(phrase, prior=None, _e=engine):
            # ITEM 4: plumbing only.
            return _e.decide(phrase, prior_turn=prior)

        # A bound method cannot carry attributes, so provenance is
        # attached to the wrapper rather than to engine.decide.
        decide.__phase3_provenance__ = {
            "backends": [],
            "model_ids": [],
            "note": "no LLM consulted",
        }
        return decide

    from ai.ai_engine import AIEngine

    ai_engine = AIEngine()
    _force_mode(ai_engine, mode)

    live = [
        getattr(p, "name", "?")
        for p in getattr(ai_engine, "_providers", [])
    ]
    model_ids = [
        getattr(p, "model_id", "?")
        for p in getattr(ai_engine, "_providers", [])
    ]

    engine = WorkflowDecisionEngine(
        ai_engine=ai_engine,
        capability_resolver=CapabilityResolver(),
    )

    def decide(phrase, prior=None, _e=engine):
        # ITEM 4: plumbing only.
        return _e.decide(phrase, prior_turn=prior)

    decide.__phase3_provenance__ = {
        "backends": live,
        "model_ids": model_ids,
        "pinned": True,
    }
    print(f"    pinned backends: {live}")
    print(f"    model ids      : {model_ids}")
    return decide


def _force_mode(ai_engine, mode: str):
    """
    Pin a single backend so a configuration cannot silently drift
    to another provider between runs.

    Restricting the provider list is the only reliable way: the
    resolver tries several modes in order (local -> cloud -> auto)
    and the local model is available here, so without pinning a
    "cloud" run would be served by the 0.5B local model and the
    number would be meaningless.

    AIEngine stores its provider list in ``_providers`` (with a
    leading underscore) and a name index in ``_provider_by_name``.
    An earlier version of this harness filtered ``providers``,
    which does not exist, so the getattr default fired and NOTHING
    was pinned -- the "llm_local"/"llm_cloud" labels were not
    enforced. That is exactly the silent-misconfiguration class of
    bug this benchmark exists to rule out, so pinning now asserts
    the outcome rather than assuming it.
    """

    if mode == "llm_local":
        keep = {"Ollama"}
    elif mode == "llm_cloud":
        keep = {"Groq"}
    else:
        return None

    providers = list(getattr(ai_engine, "_providers", []) or [])
    if not providers:
        raise RuntimeError(
            "cannot pin a backend: AIEngine exposes no _providers"
        )

    kept = [
        p for p in providers
        if getattr(p, "name", None) in keep
    ]
    if not kept:
        raise RuntimeError(
            f"cannot pin {mode}: no provider named {sorted(keep)} "
            f"(available: "
            f"{sorted(getattr(p, 'name', '?') for p in providers)})"
        )

    ai_engine._providers = kept
    if hasattr(ai_engine, "_provider_by_name"):
        ai_engine._provider_by_name = {
            name: p
            for name, p in ai_engine._provider_by_name.items()
            if name in keep
        }

    # Verify the pin took effect rather than trusting it.
    live = sorted(
        getattr(p, "name", "?")
        for p in getattr(ai_engine, "_providers", [])
    )
    if live != sorted(keep):
        raise RuntimeError(
            f"backend pin failed: wanted {sorted(keep)}, got {live}"
        )

    return keep


# =========================================================
# CLI
# =========================================================

def main() -> int:
    load_env()

    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    modes = (
        sys.argv[2].split(",")
        if len(sys.argv) > 2
        else ["deterministic_only", "llm_local"]
    )
    # Optional: seconds to wait between items. Cloud measurement
    # needs pacing to stay inside the rolling tokens-per-minute
    # quota (see score()).
    pause_s = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

    if which == "dev":
        items = DEV_ITEMS
        split = "dev"
    elif which == "heldout":
        items = build_heldout()
        split = "heldout"
    else:
        print(f"unknown split {which!r}; use dev|heldout")
        return 2

    print("=" * 74)
    print(f"  PHASE 3 HELD-OUT BENCHMARK — split={split}  items={len(items)}")
    print("=" * 74)

    iterations: List[Dict[str, Any]] = []

    for mode in modes:
        print(f"\n--- configuration: {mode} ---")
        decide = make_decider(mode)
        provenance = getattr(
            decide, "__phase3_provenance__", {}
        )
        result = score(
            items, decide, f"{split}:{mode}", pause_s=pause_s
        )
        result["provenance"] = provenance
        result["pause_between_items_s"] = pause_s
        iterations.append(result)
        print(
            f"    strict     {result['strict_correct']}/{result['total']} "
            f"= {result['strict_pct']}%"
        )
        print(
            f"    acceptable {result['acceptable_correct']}/{result['total']} "
            f"= {result['acceptable_pct']}%"
        )
        print(
            f"    routed L3  {result['routed_level3']}/{result['total']}"
            f"   mean {result['mean_elapsed_s']}s"
            f"   quota-errors {result['quota_errors']}"
        )
        if result["suspected_quota_starved"]:
            print(
                f"    !! {result['suspected_quota_starved']} item(s) "
                f"returned no answer in <1s — provider quota almost "
                f"certainly exhausted."
            )
            print(
                f"    !! Excluding those, on the {result['measured_total']} "
                f"items the model actually saw:"
                f" strict {result['measured_strict_pct']}%"
                f" acceptable {result['measured_acceptable_pct']}%"
            )
        misses = [
            r for r in result["results"] if not r["acceptable_pass"]
        ]
        if misses:
            print(f"    misses ({len(misses)}):")
            for m in misses[:12]:
                print(
                    f"      {m['phrase'][:52]:54} "
                    f"exp={m['expect']:26} got={m['got']}"
                )
            if len(misses) > 12:
                print(f"      ... and {len(misses) - 12} more")

    out = {
        "split": split,
        "item_count": len(items),
        "iterations": iterations,
    }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = BACKEND / f"phase3_bench_{split}_{stamp}.json"
    out_path.write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print(f"\nwrote {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
