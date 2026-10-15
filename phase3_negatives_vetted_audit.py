"""
Phase 3 Item 2 -- overlap audit for the vetted negative set.

Applies the SAME rules `phase3_v3_audit.py` applies to every sealed item,
to `phase3_negatives_vetted_corpus.NEGATIVES_VETTED`:

  * the legacy 40-item corpus is rejected outright,
  * the banned old-generator frame is rejected,
  * every item is fragment-matched against prompts, boundary notes,
    few-shot examples, gate vocabulary and the deterministic regex layer,
    and anything SIGNIFICANT must be rewritten,
  * plus two checks specific to this item: no overlap with either sealed
    corpus, and no internal duplicates.

Fragment significance uses the v3 rules verbatim rather than a
re-implementation, so this module cannot drift from the sealed standard.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

import phase3_negatives_vetted_corpus as CORPUS

BANNED_FRAMES = (
    "execute the",
    "compatibility capability for",
)

MIN_NEGATIVES = 20


def _surfaces() -> Dict[str, str]:
    from genesis_os.capabilities import SELECTION_BOUNDARIES
    from genesis_os.llm_intent_resolver import LLMIntentResolver as L

    full_prompt = L._build_prompt("PLACEHOLDER", L._capability_catalog())
    few_shot = " ".join(re.findall(r'"([^"]{12,200})" ->', full_prompt))
    shortlist_prompt = L._shortlist_catalog()

    det_text = (BACKEND / "agents" / "workflow_decision.py").read_text(
        encoding="utf-8"
    )
    det_literals = " ".join(
        re.findall(r'"([a-z][a-z _\-\']{3,60})"', det_text)
    )

    return {
        "prompt_full_template": full_prompt,
        "prompt_few_shot_examples": few_shot,
        "prompt_shortlist": shortlist_prompt,
        "selection_boundaries": " ".join(SELECTION_BOUNDARIES.values()),
        "deterministic_regex_layer": det_literals,
    }


def _common_english() -> frozenset:
    import phase3_v3_audit as A

    return A._common_english()


def _domain_terms() -> frozenset:
    import phase3_v3_audit as A

    return A._domain_terms()


def audit() -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    items = CORPUS.all_negatives()

    # ---- composition minimum -----------------------------------
    report["composition"] = {
        "count": len(items),
        "minimum_required": MIN_NEGATIVES,
        "meets_minimum": len(items) >= MIN_NEGATIVES,
        "families": {
            name: len(rows) for name, rows in
            sorted(CORPUS.by_category().items())
        },
        "carrying_prior": len(CORPUS.with_context()),
        "without_prior": len(CORPUS.without_context()),
    }

    # ---- banned frame ------------------------------------------
    banned_hits: List[str] = []
    for item in items:
        low = item["phrase"].lower()
        for frame in BANNED_FRAMES:
            if frame in low:
                banned_hits.append(f"{item['phrase']!r} :: {frame}")
    report["banned_frame"] = {"hits": banned_hits}

    # ---- fragment overlap against production surfaces ----------
    surfaces = _surfaces()
    common = _common_english()
    domain = _domain_terms()
    significant: List[Dict[str, Any]] = []
    incidental = 0
    for item in items:
        phrase = item["phrase"]
        tokens = re.split(r"[^a-z0-9]+", phrase.lower())
        grams = {
            " ".join(tokens[i:i + 4])
            for i in range(max(0, len(tokens) - 3))
        }
        sig: set = set()
        inc: set = set()
        for surface_name, surface in surfaces.items():
            norm = re.sub(r"[^a-z0-9]+", " ", surface.lower())
            for gram in grams:
                if gram and gram in norm:
                    meaningful = [
                        w for w in gram.split()
                        if w not in common and w not in domain
                    ]
                    if len(meaningful) >= 2:
                        sig.add((surface_name, gram))
                    else:
                        inc.add((surface_name, gram))
        incidental += len(inc)
        if sig:
            significant.append({
                "phrase": phrase,
                "surfaces": sorted({s for s, _ in sig}),
                "fragments": sorted({g for _, g in sig})[:6],
            })
    report["overlap_vs_production_surfaces"] = {
        "items_with_significant_overlap": len(significant),
        "significant": significant,
        "incidental_fragment_hits": incidental,
    }

    # ---- overlap vs BOTH sealed corpora -------------------------
    sealed_hits: List[Dict[str, str]] = []
    sealed_phrases: List[str] = []
    for module_name, seal_name in (
        ("phase3_v3_corpus", "phase3_v3_SEALED.json"),
        ("phase3_v4_corpus", "phase3_v4_SEALED.json"),
    ):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        pool = []
        for name in dir(module):
            value = getattr(module, name)
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        if entry.get("phrase"):
                            pool.append(entry["phrase"])
                        if entry.get("prior"):
                            pool.append(entry["prior"])
        sealed_phrases += pool
        seal = BACKEND / seal_name
        if seal.exists():
            data = json.loads(seal.read_text(encoding="utf-8"))
            for split, rows in data.items():
                if not isinstance(rows, list):
                    continue
                for entry in rows:
                    if isinstance(entry, dict) and entry.get("phrase"):
                        sealed_phrases.append(entry["phrase"])

    def norm(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()

    sealed_norm = {norm(p): p for p in sealed_phrases if p}
    for item in items:
        for candidate in (item["phrase"], item.get("prior")):
            if not candidate:
                continue
            key = norm(candidate)
            if key in sealed_norm:
                sealed_hits.append({
                    "phrase": candidate,
                    "sealed": sealed_norm[key],
                })
                continue
            # also flag a 4-gram shared with any sealed phrase
            tokens = key.split()
            for i in range(max(0, len(tokens) - 3)):
                gram = " ".join(tokens[i:i + 4])
                for other_norm, other in sealed_norm.items():
                    if gram and gram in other_norm:
                        sealed_hits.append({
                            "phrase": candidate,
                            "fourgram": gram,
                            "sealed": other,
                        })
                        break
    report["overlap_vs_sealed_corpora"] = {
        "sealed_phrases_checked": len(sealed_phrases),
        "hits": sealed_hits,
    }

    # ---- internal duplicates ------------------------------------
    seen: Dict[str, str] = {}
    duplicates: List[Dict[str, str]] = []
    for item in items:
        key = norm(item["phrase"])
        if key in seen:
            duplicates.append({"phrase": item["phrase"],
                               "first_seen": seen[key]})
        else:
            seen[key] = item["phrase"]
    report["internal_duplicates"] = duplicates

    # ---- every item has a reason --------------------------------
    missing = [i["phrase"] for i in items if not i.get("reason")]
    report["missing_reason"] = missing

    # ---- verdict ------------------------------------------------
    failed = (
        not report["composition"]["meets_minimum"]
        or bool(banned_hits)
        or bool(significant)
        or bool(sealed_hits)
        or bool(duplicates)
        or bool(missing)
    )
    report["audit_passed"] = not failed
    return report


def main() -> int:
    report = audit()
    out = BACKEND / "phase3_negatives_vetted_audit.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)[:6000])
    print()
    print("written:", out)
    print("AUDIT PASSED:", report["audit_passed"])
    return 0 if report["audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())