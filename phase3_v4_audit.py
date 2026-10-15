"""
Phase 3 v4 corpus audit and sealer.

Run:  python phase3_v4_audit.py            # audit only
      python phase3_v4_audit.py --seal     # audit, then split + hash

This runs the SAME checks as phase3_v3_audit.py — legacy-corpus
reuse, banned legacy frames, the v3 significance/incidental overlap
scan, expectation-ID validation and composition minimums — by
reusing that module's own functions with CORPUS rebound to the v4
corpus. Nothing is relaxed.

Two deliberate differences from the v3 sealer, both fixing measured
defects rather than changing standards:

  1. CONTEXT IS NOT DOUBLE-COUNTED. The v3 sealer built final3 as
     `all_positives()[n:] + negatives + context`, but
     all_positives() ALREADY includes the context items, so all 9
     context items appeared twice in final3 (18 context rows for 9
     items). v4 final4 is `all_positives()[n:] + negatives`.

  2. THE DIGEST IS RECORDED INDEPENDENTLY. In v3 the only copy of
     final3_sha256 lived inside phase3_v3_SEALED.json itself — the
     file the digest is supposed to protect — and
     phase3_v3_audit.json stored no digest at all, so there was
     nothing to cross-check against. A self-asserted digest proves
     nothing about tampering. v4 writes the digest to
     phase3_v4_SEAL_DIGEST.txt as well, and that file's bytes are
     what the sign-off quotes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import phase3_v3_audit as AUDIT
import phase3_v4_corpus as CORPUS

# Reuse the v3 pipeline verbatim, against the v4 corpus.
AUDIT.CORPUS = CORPUS

SEAL_PATH = BACKEND / "phase3_v4_SEALED.json"
DIGEST_PATH = BACKEND / "phase3_v4_SEAL_DIGEST.txt"
REPORT_PATH = BACKEND / "phase3_v4_audit.json"


def audit() -> Dict[str, Any]:
    """Run every v3 check against the v4 corpus, unchanged."""
    report = AUDIT.audit()

    report["corpus"] = "v4"
    report["provenance"] = {
        "dev3_carryover": len(CORPUS.DEV3_CARRYOVER),
        "dev3_carryover_caveat": (
            "6 dev3 phrases were read during the Step 1b routing "
            "investigation. Never scored; no fix encodes a dev3 "
            "phrase (the gate fix dev3 analysis suggested was tried "
            "and reverted). Diagnosis-exposed, not untouched."
        ),
        "new_human_positives": len(CORPUS.NEW_HUMAN_POSITIVES),
        "new_hand_written": len([
            p for p in CORPUS.NEW_HUMAN_POSITIVES
            if p.get("source") == "human"
        ]),
        "new_assistant_drafted": len([
            p for p in CORPUS.NEW_HUMAN_POSITIVES
            if p.get("source") != "human"
        ]),
        "negatives_agent_drafted": len(CORPUS.NEGATIVES),
        "context_agent_drafted": len(CORPUS.CONTEXT_ITEMS),
        "scored_final3_items_reused": 0,
        "accept_sets_declared": len([
            p for p in CORPUS.HUMAN_POSITIVES if p.get("accept")
        ]),
    }
    return report


def seal() -> Dict[str, Any]:
    """
    Split dev4/final4 and hash final4 BEFORE any run touches it.

    Same canonical form as the v3 sealer:
      * items sorted by their canonical JSON,
      * serialised with json.dumps(ordered, indent=2, sort_keys=True),
      * SHA-256 over those UTF-8 bytes.

    Context items are NOT appended again (see module docstring).
    """
    positives = CORPUS.all_positives()
    negatives = CORPUS.NEGATIVES

    # STRATIFIED split, not a prefix slice.
    #
    # The v3 sealer took `positives[:30%]`. Because the positives
    # list starts with the dev3 carryover and dev3 was itself a
    # prefix slice, that produced a category-confounded split: every
    # one of dev3's 29 items was application/browser/gui, and zero
    # were filesystem, documents, clipboard, spreadsheet, system or
    # media. Repeating a prefix slice here inherited the same defect
    # and left final4 with ZERO gui items and only ONE application
    # item, so two whole capability domains were untested.
    #
    # Taking ~25% from each category keeps dev4 representative and
    # guarantees every category is represented in the measured set.
    # Ordering inside a category is canonical, so the split is
    # deterministic and reproducible.
    by_category: Dict[str, list] = {}
    for item in positives:
        by_category.setdefault(
            str(item.get("category", "")), []
        ).append(item)

    dev4: list = []
    dev4_keys: set = set()
    for category in sorted(by_category):
        group = sorted(
            by_category[category],
            key=lambda i: json.dumps(i, sort_keys=True),
        )
        take = max(1, int(len(group) * 0.25))
        for item in group[:take]:
            key = json.dumps(item, sort_keys=True)
            dev4.append(item)
            dev4_keys.add(key)

    dev4.sort(key=lambda i: json.dumps(i, sort_keys=True))
    final4 = [
        item for item in positives
        if json.dumps(item, sort_keys=True) not in dev4_keys
    ] + negatives

    ordered = sorted(final4, key=lambda i: json.dumps(i, sort_keys=True))
    payload = json.dumps(ordered, indent=2, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # dev4 was previously stored in the seal but never hashed, so an
    # edit to a dev4 item's CONTENT was undetectable -- only its count
    # was recorded. The dev/measured split is what keeps final4 honest,
    # so the split itself has to be covered. Recorded as two additional
    # digests so the original final4 fingerprint is preserved
    # byte-for-byte and every published result that quotes it stays
    # valid; no rescoring is implied by adding these.
    dev4_ordered = sorted(
        dev4, key=lambda i: json.dumps(i, sort_keys=True)
    )
    dev4_payload = json.dumps(dev4_ordered, indent=2, sort_keys=True)
    dev4_digest = hashlib.sha256(dev4_payload.encode("utf-8")).hexdigest()
    split_payload = json.dumps(
        {"dev4": dev4_ordered, "final4": ordered},
        indent=2, sort_keys=True,
    )
    split_digest = hashlib.sha256(split_payload.encode("utf-8")).hexdigest()

    SEAL_PATH.write_text(
        json.dumps({
            "sealed_at_utc": __import__("datetime").datetime.utcnow()
            .isoformat() + "Z",
            "final4_sha256": digest,
            "final4_item_count": len(ordered),
            "dev4_sha256": dev4_digest,
            "dev4_item_count": len(dev4),
            "split_sha256": split_digest,
            "digest_covers": (
                "final4_sha256 = sha256(json.dumps(final4, "
                "indent=2, sort_keys=True)) where final4 is sorted by "
                "json.dumps(item, sort_keys=True). dev4_sha256 is the "
                "same construction over dev4. split_sha256 covers BOTH "
                "halves as one object {\"dev4\": ..., \"final4\": ...} "
                "so the dev/measured split is tamper-evident as a "
                "whole. None of these is the sha256 of the seal file's "
                "own bytes."
            ),
            "dev4": dev4_ordered,
            "final4": ordered,
        }, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Independent record, written to its own file so the digest is
    # not merely asserting itself inside the artefact it protects.
    DIGEST_PATH.write_text(
        f"final4_sha256 {digest}\n"
        f"final4_item_count {len(ordered)}\n"
        f"dev4_sha256 {dev4_digest}\n"
        f"dev4_item_count {len(dev4)}\n"
        f"split_sha256 {split_digest}\n"
        f"sealed_file {SEAL_PATH.name}\n",
        encoding="utf-8",
    )

    return {
        "final4_sha256": digest,
        "final4_item_count": len(ordered),
        "dev4_sha256": dev4_digest,
        "split_sha256": split_digest,
        "dev4_item_count": len(dev4),
        "sealed_file": SEAL_PATH.name,
        "digest_file": DIGEST_PATH.name,
    }


def main() -> int:
    report = audit()
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    print("=" * 74)
    print("  PHASE 3 v4 CORPUS AUDIT")
    print("=" * 74)
    for key, section in report.items():
        if isinstance(section, dict) and "verdict" in section:
            count = section.get("count", "?")
            print(f"  {key:22} {section['verdict']:10} ({count})")
            for item in section.get("items", [])[:12]:
                print(f"      - {item}")

    print()
    print(f"  composition          {report['composition']['verdict']}")
    for problem in report["composition"].get("problems", []):
        print(f"      - {problem}")
    print(
        f"      positives={report['composition']['positives']} "
        f"hand_written={report['composition']['hand_written']} "
        f"negatives={report['composition']['negatives']} "
        f"context={report['composition']['context']}"
    )
    print()
    print(f"  seal_ready           {report['seal_ready']}")

    if "--seal" in sys.argv:
        if not report["seal_ready"]:
            print(
                "\n  REFUSING TO SEAL: audit is not clean."
            )
            return 1
        result = seal()
        print()
        print("=" * 74)
        print("  SEALED final4")
        print("=" * 74)
        print(f"  final4_sha256    {result['final4_sha256']}")
        print(f"  final4 items     {result['final4_item_count']}")
        print(f"  dev4_sha256      {result['dev4_sha256']}")
        print(f"  dev4 items       {result['dev4_item_count']}")
        print(f"  split_sha256     {result['split_sha256']}")
        print(f"  digest record   {result['digest_file']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())