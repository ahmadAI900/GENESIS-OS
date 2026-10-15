"""
Genesis OS
Level 3.2.3B — Windows Registered Application Discovery Test
"""

from genesis_os.applications.windows_registered_apps import (
    WindowsRegisteredApplicationDiscovery
)


def main():

    print("=" * 70)

    print(
        "GENESIS OS — WINDOWS REGISTERED "
        "APPLICATION DISCOVERY"
    )

    print("=" * 70)

    discovery = (
        WindowsRegisteredApplicationDiscovery()
    )

    # =====================================================
    # DISCOVERY
    # =====================================================

    print()
    print(
        "[1] Discovering Windows registered applications..."
    )

    applications = (
        discovery.discover()
    )

    print(
        f"[Discovery] Found "
        f"{len(applications)} registered applications."
    )

    # =====================================================
    # SAMPLE
    # =====================================================

    print()
    print(
        "[2] Sample registered applications:"
    )

    for application in sorted(
        applications,
        key=lambda item:
            item.get(
                "name",
                ""
            ).lower()
    )[:40]:

        print(
            f"  - "
            f"{application.get('name')} "
            f"| "
            f"type={application.get('type')} "
            f"| "
            f"source={application.get('source')} "
            f"| "
            f"app_id={application.get('app_id')}"
        )

    # =====================================================
    # SEARCH
    # =====================================================

    print()
    print(
        "[3] Searching registered applications..."
    )

    queries = [
        "whatsapp",
        "settings",
        "calculator",
        "notepad",
        "camera",
        "store",
        "xbox",
    ]

    for query in queries:

        matches = [
            application
            for application in applications
            if query.lower()
            in application.get(
                "name",
                ""
            ).lower()
        ]

        print(
            f"  Search '{query}': "
            f"{len(matches)} result(s)"
        )

        for match in matches[:5]:

            print(
                f"      → "
                f"{match.get('name')} "
                f"[{match.get('source')}]"
            )

    # =====================================================
    # SOURCE COUNTS
    # =====================================================

    print()
    print(
        "[4] Discovery source statistics:"
    )

    source_counts = {}

    for application in applications:

        source = application.get(
            "source",
            "unknown"
        )

        source_counts[source] = (
            source_counts.get(
                source,
                0
            ) + 1
        )

    for source, count in sorted(
        source_counts.items()
    ):

        print(
            f"  {source}: {count}"
        )

    # =====================================================
    # COMPLETE
    # =====================================================

    print()
    print("=" * 70)

    print(
        "WINDOWS REGISTERED APPLICATION "
        "DISCOVERY TEST COMPLETE"
    )

    print("=" * 70)


if __name__ == "__main__":

    main()