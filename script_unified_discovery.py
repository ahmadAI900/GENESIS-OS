"""
Genesis OS — Unified Application Discovery Test

LEVEL 3.2.3C
------------

Tests:

1. Unified application discovery
2. Canonical application registry
3. Application resolution
4. Source preservation
5. Identity-aware deduplication
6. Explainable identity decisions

This test does NOT launch applications.
"""

from __future__ import annotations

from genesis_os.applications.unified_discovery import (
    UnifiedApplicationDiscovery,
)


def print_separator():
    print("=" * 70)


def print_subseparator():
    print("-" * 70)


def main():

    print_separator()

    print(
        "GENESIS OS — UNIFIED APPLICATION "
        "DISCOVERY & DEDUPLICATION"
    )

    print_separator()

    # =========================================================
    # INITIALIZE
    # =========================================================

    discovery = UnifiedApplicationDiscovery()

    # =========================================================
    # 1. BUILD UNIFIED APPLICATION INDEX
    # =========================================================

    print()
    print(
        "[1] Building unified application index..."
    )

    applications = discovery.discover(
        refresh=True
    )

    print(
        f"[Unified] "
        f"{len(applications)} canonical applications discovered."
    )

    # =========================================================
    # 2. UNIFIED STATISTICS
    # =========================================================

    print()
    print(
        "[2] Unified statistics:"
    )

    statistics = discovery.statistics()

    print(
        f"  Total applications: "
        f"{statistics.get('total_applications', 0)}"
    )

    print(
        f"  Multi-source applications: "
        f"{statistics.get('multi_source_applications', 0)}"
    )

    # ---------------------------------------------------------
    # Categories
    # ---------------------------------------------------------

    print()
    print(
        "  Categories:"
    )

    categories = statistics.get(
        "categories",
        {}
    )

    for category, count in categories.items():

        print(
            f"    {category}: {count}"
        )

    # ---------------------------------------------------------
    # Sources
    # ---------------------------------------------------------

    print()
    print(
        "  Sources:"
    )

    sources = statistics.get(
        "sources",
        {}
    )

    for source, count in sources.items():

        print(
            f"    {source}: {count}"
        )

    # ---------------------------------------------------------
    # Identity statistics
    # ---------------------------------------------------------

    print()
    print(
        "  Identity:"
    )

    identity_statistics = statistics.get(
        "identity",
        {}
    )

    if identity_statistics:

        for key, value in (
            identity_statistics.items()
        ):

            print(
                f"    {key}: {value}"
            )

    else:

        print(
            "    No identity statistics available."
        )

    print(
        "  Merge decisions recorded: "
        f"{statistics.get('merge_decisions_recorded', 0)}"
    )

    # =========================================================
    # 3. RESOLUTION TESTS
    # =========================================================

    print()
    print(
        "[3] Resolution tests:"
    )

    test_queries = [
        "google chrome",
        "chrome",
        "calculator",
        "camera",
        "settings",
        "notepad",
        "file explorer",
        "microsoft store",
        "whatsapp",
    ]

    for query in test_queries:

        print()
        print(
            f"Query: '{query}'"
        )

        result = discovery.resolve(
            query
        )

        if result is None:

            print(
                "  Result: NOT RESOLVED"
            )

            continue

        print(
            f"  Result: "
            f"{result.get('name')}"
        )

        print(
            f"  Category: "
            f"{result.get('category')}"
        )

        print(
            f"  Launchable: "
            f"{result.get('launchable')}"
        )

        print(
            f"  Sources: "
            f"{result.get('sources')}"
        )

    # =========================================================
    # 4. MULTI-SOURCE APPLICATIONS
    # =========================================================

    print()
    print(
        "[4] Multi-source application examples:"
    )

    multi_source = []

    for application in applications:

        sources = application.get(
            "sources",
            []
        )

        if len(sources) > 1:

            multi_source.append(
                application
            )

    if not multi_source:

        print(
            "  No multi-source applications found."
        )

    else:

        for application in (
            multi_source[:20]
        ):

            print(
                f"  - {application.get('name')}"
            )

            print(
                f"      category="
                f"{application.get('category')}"
            )

            print(
                f"      sources="
                f"{application.get('sources')}"
            )

    # =========================================================
    # 5. RAW-SOURCE PRESERVATION
    # =========================================================

    print()
    print(
        "[5] Raw-source preservation test:"
    )

    chrome = discovery.resolve(
        "google chrome"
    )

    if chrome is None:

        print(
            "  Google Chrome was not resolved."
        )

    else:

        raw_records = chrome.get(
            "raw_records",
            []
        )

        aliases = chrome.get(
            "aliases",
            []
        )

        print(
            f"  Google Chrome raw records: "
            f"{len(raw_records)}"
        )

        print(
            f"  Google Chrome aliases: "
            f"{aliases}"
        )

    # =========================================================
    # 6. IDENTITY-AWARE MERGE REPORT
    # =========================================================

    print()
    print(
        "[6] Identity-aware merge report:"
    )

    identity_report = (
        discovery.identity_report()
    )

    identity_report_statistics = (
        identity_report.get(
            "statistics",
            {}
        )
    )

    print()
    print(
        "  Identity engine statistics:"
    )

    for key, value in (
        identity_report_statistics.items()
    ):

        print(
            f"    {key}: {value}"
        )

    decisions = (
        identity_report.get(
            "decisions",
            []
        )
    )

    same_decisions = [
        decision
        for decision in decisions
        if decision.get("decision")
        == "same"
    ]

    different_decisions = [
        decision
        for decision in decisions
        if decision.get("decision")
        == "different"
    ]

    uncertain_decisions = [
        decision
        for decision in decisions
        if decision.get("decision")
        == "uncertain"
    ]

    print()
    print(
        f"  SAME decisions recorded: "
        f"{len(same_decisions)}"
    )

    print(
        f"  DIFFERENT decisions recorded: "
        f"{len(different_decisions)}"
    )

    print(
        f"  UNCERTAIN decisions recorded: "
        f"{len(uncertain_decisions)}"
    )

    # =========================================================
    # SAMPLE SAME DECISIONS
    # =========================================================

    print()
    print(
        "  Sample SAME decisions:"
    )

    if not same_decisions:

        print(
            "    None recorded."
        )

    else:

        for decision in same_decisions[:10]:

            print(
                f"    - "
                f"{decision.get('existing')} "
                f"<-> "
                f"{decision.get('candidate')} "
                f"| confidence="
                f"{decision.get('confidence')} "
                f"| method="
                f"{decision.get('method')}"
            )

    # =========================================================
    # SAMPLE DIFFERENT DECISIONS
    # =========================================================

    print()
    print(
        "  Sample DIFFERENT decisions:"
    )

    if not different_decisions:

        print(
            "    None recorded."
        )

    else:

        for decision in (
            different_decisions[:10]
        ):

            print(
                f"    - "
                f"{decision.get('existing')} "
                f"<-> "
                f"{decision.get('candidate')} "
                f"| confidence="
                f"{decision.get('confidence')} "
                f"| method="
                f"{decision.get('method')}"
            )

    # =========================================================
    # SAMPLE UNCERTAIN DECISIONS
    # =========================================================

    print()
    print(
        "  Sample UNCERTAIN decisions:"
    )

    if not uncertain_decisions:

        print(
            "    None recorded."
        )

    else:

        for decision in (
            uncertain_decisions[:10]
        ):

            print(
                f"    - "
                f"{decision.get('existing')} "
                f"<-> "
                f"{decision.get('candidate')} "
                f"| confidence="
                f"{decision.get('confidence')} "
                f"| method="
                f"{decision.get('method')}"
            )

    # =========================================================
    # 7. IDENTITY EVIDENCE SAMPLE
    # =========================================================

    print()
    print(
        "[7] Explainable identity evidence:"
    )

    evidence_examples = (
        same_decisions[:3]
        + different_decisions[:2]
    )

    if not evidence_examples:

        print(
            "  No identity evidence available."
        )

    else:

        for decision in evidence_examples:

            print()
            print(
                f"  {decision.get('existing')} "
                f"<-> "
                f"{decision.get('candidate')}"
            )

            print(
                f"    Decision: "
                f"{decision.get('decision')}"
            )

            print(
                f"    Confidence: "
                f"{decision.get('confidence')}"
            )

            evidence = decision.get(
                "evidence",
                []
            )

            if not evidence:

                print(
                    "    Evidence: none"
                )

            else:

                print(
                    "    Evidence:"
                )

                for item in evidence[:5]:

                    print(
                        f"      - "
                        f"{item.get('signal')} "
                        f"[{item.get('score')}] "
                        f"{item.get('description')}"
                    )

            reasons = decision.get(
                "reasons",
                []
            )

            if reasons:

                print(
                    "    Reasons:"
                )

                for reason in reasons:

                    print(
                        f"      - {reason}"
                    )

            conflicts = decision.get(
                "conflicts",
                []
            )

            if conflicts:

                print(
                    "    Conflicts:"
                )

                for conflict in conflicts:

                    print(
                        f"      - {conflict}"
                    )

    # =========================================================
    # 8. BASIC SAFETY ASSERTIONS
    # =========================================================

    print()
    print(
        "[8] Running safety assertions..."
    )

    # Discovery must return applications.
    assert isinstance(
        applications,
        list,
    )

    # Statistics must be a dictionary.
    assert isinstance(
        statistics,
        dict,
    )

    # Identity report must be a dictionary.
    assert isinstance(
        identity_report,
        dict,
    )

    # WhatsApp should remain unresolved if it is genuinely
    # absent from the machine. We do NOT hard-code this as
    # an assertion because the test should remain portable
    # to machines where WhatsApp is installed.
    whatsapp = discovery.resolve(
        "whatsapp"
    )

    if whatsapp is None:

        print(
            "  WhatsApp: not discovered "
            "(expected if not installed)."
        )

    else:

        print(
            "  WhatsApp: discovered on this machine."
        )

    print(
        "  Application list: PASS"
    )

    print(
        "  Statistics: PASS"
    )

    print(
        "  Identity report: PASS"
    )

    print(
        "  Safety assertions: PASS"
    )

    # =========================================================
    # COMPLETE
    # =========================================================

    print()
    print_separator()

    print(
        "GENESIS OS — UNIFIED APPLICATION "
        "DISCOVERY TEST COMPLETE"
    )

    print_separator()


if __name__ == "__main__":
    main()