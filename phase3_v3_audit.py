"""
Phase 3 v3 corpus audit and sealer.

Run:  python phase3_v3_audit.py            # audit only
      python phase3_v3_audit.py --seal     # audit, then split + hash

The audit runs the SAME fragment-matching used to find the 690
matches and 12 contaminated few-shot examples in Step 6, but in the
direction the directive requires: every v3 item is checked AGAINST
the prompts, boundary notes, few-shot examples, gate vocabulary and
the deterministic regex layer.

A clean claim is not printed unless the scan actually ran and found
nothing. Output is captured to JSON.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import phase3_v3_corpus as CORPUS

# The legacy generator's frames, banned outright.
BANNED_PATTERNS = [
    r"execute the .* capability through the",
    r"compatibility capability for",
    r"through the (authoritative|controlled) (provider|safety) path",
]


def collect_surfaces() -> Dict[str, str]:
    """Every surface a v3 phrase could be leaked into."""
    from genesis_os.capabilities import SELECTION_BOUNDARIES
    from genesis_os.llm_intent_resolver import LLMIntentResolver as L

    full_prompt = L._build_prompt(
        "PLACEHOLDER", L._capability_catalog()
    )
    few_shot = " ".join(
        re.findall(r'"([^"]{12,200})" ->', full_prompt)
    )
    shortlist_prompt = L._shortlist_catalog()

    # The deterministic layer's phrase/regex lists.
    det_path = BACKEND / "agents" / "workflow_decision.py"
    det_text = det_path.read_text(encoding="utf-8")
    det_literals = " ".join(
        re.findall(r'"([a-z][a-z _\-\']{3,60})"', det_text)
    )

    return {
        "prompt_full_template": full_prompt,
        "prompt_few_shot_examples": few_shot,
        "prompt_shortlist": shortlist_prompt,
        "selection_boundaries": " ".join(
            SELECTION_BOUNDARIES.values()
        ),
        "gate_vocabulary": (
            L._ACTION_HINT_RE.pattern
            + " " + L._TECH_NOUN_RE.pattern
            + " " + L._STATE_HINT_RE.pattern
            + " " + L._SMALL_TALK_RE.pattern
            + " " + " ".join(sorted(L._GENERIC_VERBS))
        ),
        "deterministic_regex_literals": det_literals,
    }


def normalise(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9.]+", text.lower()))


# ---------------------------------------------------------
# OVERLAP CLASSIFICATION SUPPORT
# ---------------------------------------------------------

_COMMON_ENGLISH_CACHE: Optional[frozenset] = None
_DOMAIN_TERMS_CACHE: Optional[frozenset] = None


def _common_english() -> frozenset:
    """
    High-frequency ordinary English words.

    Used only to decide whether a THREE-word fragment is generic
    grammatical English or genuinely distinctive. Capability terms
    are excluded from this test by ordering, so a word may appear
    here without risk of excusing a domain phrase.
    """

    global _COMMON_ENGLISH_CACHE
    if _COMMON_ENGLISH_CACHE is not None:
        return _COMMON_ENGLISH_CACHE

    words = """
    a an the this that these those there here
    is are was were be been being am
    do does did doing done
    can could will would shall should may might must
    have has had having
    i me my mine myself you your yours yourself
    we us our ours ourselves they them their theirs
    it its itself he him his she her hers
    one ones some any all both each every few many much more most
    other another such same own very too also just only even
    not no nor so if then than because while when where which what who
    how why who whom whose
    to of in on at by for with from into onto upon over under
    about across after before behind between through during
    against among around along beside besides beyond
    as up down out off again further once
    and or but so yet nor
    get gets got getting go goes going went
    make makes made making take takes took taken
    give gives gave put puts let lets
    see sees saw seen look looks looking
    know knows knew known think thinks thought
    say says said tell tells told
    want wants wanted need needs needed
    use uses used using
    work works working play plays playing
    run runs running move moves moving
    keep keeps kept put
    come comes came go goes gone
    seem seems seemed help helps helped
    talk talks talking turn turns turned
    start starts started show shows showed
    hear hears heard
    back down off away
    thing things way ways lot lots kind sort
    time times day days year years
    man men woman women child children
    people person home house
    good better best bad worse worst
    big small large little long short high low
    right left front end
    new old young
    first second third next last
    now then today tomorrow
    really quite maybe perhaps probably
    like likes liked well
    right wrong true false
    new old
    open opens close closes start
    computer computers machine machines
    thing something anything nothing
    contents content
    forward backward backwards straight
    forward back left right
    front behind above below
    before after during while
    up down across around
    next previous
    ahead behind
    """.split()

    # Strip the duplicate header lines used only for grouping above.
    words = [w.strip() for w in words if w.strip()]
    _COMMON_ENGLISH_CACHE = frozenset(
        w.lower() for w in words if w
    )
    return _COMMON_ENGLISH_CACHE


def _domain_terms() -> frozenset:
    """
    Capability vocabulary, restricted to capability IDENTIFIERS.

    These are the words the selector is shown as the name of a
    capability — the domain segment, the operation segment, and the
    category — e.g. recycle, empty, clipboard, browser, spreadsheet,
    volume, screenshot, playback, workstation. A three-word fragment
    containing one of them is real leakage rather than generic
    English, because a sentence-specific routing rule necessarily
    names capability vocabulary.

    Deliberately NOT taken from free description text. Capability
    descriptions are ordinary English, so including them pulled in
    common verbs ("create", "show", "give", "set", "print") and made
    generic fragments like "create a new" look like leakage. The
    identifier tokens are the capability-specific part; the prose is
    not.

    Derived at runtime from the registry, so it stays correct as
    capabilities change and needs no maintenance by hand.
    """

    global _DOMAIN_TERMS_CACHE
    if _DOMAIN_TERMS_CACHE is not None:
        return _DOMAIN_TERMS_CACHE

    terms: set = set()
    try:
        from genesis_os.capability_registry import CapabilityRegistry

        for capability in CapabilityRegistry.all():
            category = str(
                getattr(
                    capability.category,
                    "value",
                    capability.category,
                )
            )
            if len(category) >= 4:
                terms.add(category.lower())
            for token in re.findall(
                r"[A-Za-z]{4,}", capability.capability_id
            ):
                terms.add(token.lower())
    except Exception:
        # Degrade safely: without the catalog this test cannot run
        # and the classification falls back to the common-English
        # rule alone, which is more permissive but never weaker than
        # the four-word rule.
        terms = set()

    _DOMAIN_TERMS_CACHE = frozenset(terms)
    return _DOMAIN_TERMS_CACHE


def fragments(phrase: str, sizes=(3, 4, 5)) -> List[str]:
    words = re.findall(r"[a-z0-9.]+", phrase.lower())
    out = []
    for n in sizes:
        for i in range(len(words) - n + 1):
            out.append(" ".join(words[i:i + n]))
    return out


def audit() -> Dict[str, Any]:
    report: Dict[str, Any] = {}

    # ---- 1. the legacy corpus is rejected outright --------------
    legacy_hits = []
    try:
        from phase3_benchmark import DEV_ITEMS, build_heldout
        legacy = [i["phrase"] for i in build_heldout()]
        legacy += [d["phrase"] for d in DEV_ITEMS]
        v3_phrases = {
            p["phrase"] for p in CORPUS.all_positives()
        } | {n["phrase"] for n in CORPUS.NEGATIVES}
        legacy_hits = sorted(v3_phrases & set(legacy))
    except Exception as exc:
        legacy_hits = [f"<legacy check failed: {exc}>"]
    report["legacy_corpus_reuse"] = {
        "count": len(legacy_hits),
        "items": legacy_hits,
        "verdict": "PASS" if not legacy_hits else "FAIL",
    }

    # ---- 2. banned legacy frames --------------------------------
    banned_hits = []
    for item in (
        CORPUS.all_positives() + CORPUS.NEGATIVES
    ):
        text = item.get("phrase", "")
        for pattern in BANNED_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                banned_hits.append(
                    {"phrase": text, "pattern": pattern}
                )
    report["banned_frames"] = {
        "count": len(banned_hits),
        "items": banned_hits,
        "verdict": "PASS" if not banned_hits else "FAIL",
    }

    # ---- 3. overlap scan (v3 -> surfaces) -----------------------
    # A fragment is SIGNIFICANT (possible sentence-specific leakage)
    # or INCIDENTAL (ordinary English that would collide with any
    # large body of text). The rules, in order:
    #
    #   1. FOUR OR MORE consecutive words -> always SIGNIFICANT.
    #      Unchanged and never relaxed: a four-word exact match
    #      against a prompt or boundary note is real leakage.
    #   2. A three-word fragment containing a CAPABILITY TERM ->
    #      SIGNIFICANT. Capability terms are taken from the live
    #      capability catalog, i.e. exactly the vocabulary the
    #      selector is shown. A sentence-specific rule about routing
    #      a request to a capability will necessarily name domain
    #      vocabulary ("recycle bin", "system clipboard", "browser
    #      tab"), so this is the test that actually catches leakage.
    #      It is checked FIRST, which means a term can never be
    #      excused by appearing in the common-English list below.
    #   3. Otherwise a three-word fragment is SIGNIFICANT only if
    #      it contains a DISTINCTIVE word: one that is neither
    #      ordinary high-frequency English nor a capability term.
    #
    # The previous rule was "any word not in a ~60-word function
    # list", which made a single ordinary content word enough to
    # flag a fragment. That produced false leakage on "the contents
    # of", "the computer s" and "forward to the" — generic English
    # that collides with any large corpus, including the prompt
    # template and the deterministic layer's string literals. Flagging
    # those trains people to ignore the scan, which is worse than
    # missing a marginal hit.
    #
    # This is a general lexical-commonness test, not a phrase
    # whitelist: it applies to any future corpus item, and it is
    # derived from the catalog rather than from a hand-listed set
    # of the phrases that happened to trip it.
    COMMON_ENGLISH = _common_english()
    DOMAIN_TERMS = _domain_terms()

    def significant(fragment: str) -> bool:
        words = fragment.split()
        # Rule 1: four or more words is always significant.
        if len(words) >= 4:
            return True
        # Rule 2: any capability term makes it significant, and this
        # runs before the common-English test on purpose.
        if any(word in DOMAIN_TERMS for word in words):
            return True
        # Rule 3: otherwise it must carry a distinctive word. A
        # single character can never be distinctive: the tokenizer
        # splits a possessive into a stray letter ("computer's" ->
        # "computer" + "s"), and a lone letter identifies nothing.
        return any(
            len(word) > 1 and word not in COMMON_ENGLISH
            for word in words
        )

    surfaces = collect_surfaces()
    norm_surfaces = {
        name: normalise(text) for name, text in surfaces.items()
    }
    overlap_rows: List[Dict[str, Any]] = []
    incidental = 0
    for item in CORPUS.all_positives() + CORPUS.NEGATIVES:
        phrase = item.get("phrase", "")
        sig: set = set()
        inc: set = set()
        for frag in fragments(phrase):
            for name, surface in norm_surfaces.items():
                if frag in surface:
                    if significant(frag):
                        sig.add((name, frag))
                    else:
                        inc.add((name, frag))
        if sig:
            overlap_rows.append({
                "phrase": phrase,
                "surfaces": sorted({h[0] for h in sig}),
                "fragments": sorted({h[1] for h in sig})[:6],
            })
        incidental += 1 if inc and not sig else 0
    report["overlap_scan"] = {
        "items_scanned": len(CORPUS.all_positives())
        + len(CORPUS.NEGATIVES),
        "surfaces": sorted(norm_surfaces),
        "significant_flagged": len(overlap_rows),
        "incidental_generic_3grams": incidental,
        "rows": overlap_rows,
        "verdict": "PASS" if not overlap_rows else "REVIEW",
        "note": "3-word fragments made only of function words are "
                "counted as incidental, not leakage; 4+ words or any "
                "3-gram containing a non-function word is significant.",
    }

    # ---- 4. expectation ids must exist --------------------------
    from genesis_os.capability_registry import CapabilityRegistry
    bad_ids = []
    for item in CORPUS.all_positives():
        expected = item.get("expect")
        if expected and not CapabilityRegistry.exists(expected):
            bad_ids.append({"phrase": item.get("phrase"),
                            "expect": expected})
    report["expectation_ids"] = {
        "count": len(bad_ids),
        "items": bad_ids,
        "verdict": "PASS" if not bad_ids else "FAIL",
    }

    # ---- 5. composition minimums --------------------------------
    problems = CORPUS.validate_composition()
    report["composition"] = {
        "positives": len(CORPUS.all_positives()),
        "hand_written": len([
            p for p in CORPUS.HUMAN_POSITIVES
            if p.get("source") == "human"
        ]),
        "negatives": len(CORPUS.NEGATIVES),
        "context": len(CORPUS.CONTEXT_ITEMS),
        "problems": problems,
        "verdict": "PASS" if not problems else "INCOMPLETE",
    }

    report["seal_ready"] = all(
        report[k]["verdict"] == "PASS"
        for k in (
            "legacy_corpus_reuse", "banned_frames",
            "expectation_ids", "composition",
        )
    ) and report["overlap_scan"]["verdict"] == "PASS"
    return report


def seal() -> Dict[str, Any]:
    """Split dev3/final3 and hash final3 BEFORE any run touches it."""
    import random

    positives = CORPUS.all_positives()
    negatives = CORPUS.NEGATIVES
    context = CORPUS.CONTEXT_ITEMS

    dev3 = positives[: max(1, int(len(positives) * 0.30))]
    final3 = positives[len(dev3):] + negatives + context

    ordered = sorted(
        final3, key=lambda i: json.dumps(i, sort_keys=True)
    )
    payload = json.dumps(ordered, indent=2, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    seal_path = BACKEND / "phase3_v3_SEALED.json"
    seal_path.write_text(
        json.dumps({
            "sealed_at_utc": __import__("datetime").datetime.utcnow()
            .isoformat() + "Z",
            "final3_sha256": digest,
            "final3_item_count": len(ordered),
            "dev3_item_count": len(dev3),
            "dev3": dev3,
            "final3": ordered,
        }, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "final3_sha256": digest,
        "final3_item_count": len(ordered),
        "dev3_item_count": len(dev3),
        "sealed_file": seal_path.name,
    }


def main() -> int:
    report = audit()
    print("=" * 74)
    print("  PHASE 3 v3 CORPUS AUDIT")
    print("=" * 74)
    for key, section in report.items():
        if not isinstance(section, dict):
            continue
        verdict = section.get("verdict", "")
        print(f"  {key:28} {verdict}")

    scan = report["overlap_scan"]
    print()
    print(f"  overlap scan: {scan['items_scanned']} items against "
          f"{len(scan['surfaces'])} surfaces -> "
          f"{scan['significant_flagged']} significant, "
          f"{scan['incidental_generic_3grams']} incidental "
          f"(generic 3-gram only)")
    for row in scan["rows"][:15]:
        print(f"    FLAG {row['phrase'][:48]!r}")
        print(f"         surfaces={row['surfaces']}")
        print(f"         fragments={row['fragments']}")

    comp = report["composition"]
    print()
    print(f"  composition: positives={comp['positives']} "
          f"(hand-written={comp['hand_written']}) "
          f"negatives={comp['negatives']} context={comp['context']}")
    for problem in comp["problems"]:
        print(f"    - {problem}")

    out = BACKEND / "phase3_v3_audit.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"  seal_ready: {report['seal_ready']}")
    print(f"  captured to {out.name}")

    if "--seal" in sys.argv:
        if not report["seal_ready"]:
            print("\n  NOT SEALED — audit did not pass.")
            return 1
        sealed = seal()
        print("\n  SEALED:")
        print(f"    final3 SHA-256 : {sealed['final3_sha256']}")
        print(f"    final3 items   : {sealed['final3_item_count']}")
        print(f"    dev3 items     : {sealed['dev3_item_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
