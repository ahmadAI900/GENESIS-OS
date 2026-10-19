"""
Genesis OS
Level 3.2.3 — Universal Application Discovery Test
"""

from genesis_os.applications.app_discovery import (
    ApplicationDiscovery
)


def main():

    print("=" * 70)
    print(
        "GENESIS OS — UNIVERSAL APPLICATION DISCOVERY"
    )
    print("=" * 70)

    discovery = ApplicationDiscovery()

    # =====================================================
    # DISCOVERY
    # =====================================================

    print()
    print("[1] Discovering applications...")

    applications = discovery.discover()

    print(
        f"[Discovery] Found {len(applications)} "
        f"applications."
    )

    # =====================================================
    # SHOW FIRST RESULTS
    # =====================================================

    print()
    print("[2] Sample discovered applications:")

    for application in sorted(
        applications,
        key=lambda item: item.get(
            "name",
            ""
        ).lower()
    )[:30]:

        print(
            f"  - {application.get('name')} "
            f"[{application.get('type')}] "
            f"({application.get('source')})"
        )

    # =====================================================
    # SEARCH
    # =====================================================

    print()
    print("[3] Testing search...")

    searches = [
        "chrome",
        "visual",
        "notepad",
        "settings",
        "whatsapp",
    ]

    for query in searches:

        results = discovery.search(
            query
        )

        print(
            f"  Search '{query}': "
            f"{len(results)} result(s)"
        )

        for result in results[:5]:

            print(
                f"      → {result.get('name')}"
            )

    # =====================================================
    # CACHE
    # =====================================================

    print()
    print("[4] Cache status:")

    print(
        discovery.cache_status()
    )

    # =====================================================
    # REFRESH
    # =====================================================

    print()
    print("[5] Testing refresh...")

    refreshed = discovery.refresh()

    print(
        f"[Refresh] Found {len(refreshed)} "
        f"applications."
    )

    # =====================================================
    # COMPLETE
    # =====================================================

    print()
    print("=" * 70)
    print(
        "UNIVERSAL APPLICATION DISCOVERY TEST COMPLETE"
    )
    print("=" * 70)


if __name__ == "__main__":

    main()