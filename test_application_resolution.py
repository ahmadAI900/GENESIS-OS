"""
Genesis OS — Application Resolution Intelligence Test

LEVEL 3.2.3C.3
"""

from genesis_os.applications.unified_discovery import (
    UnifiedApplicationDiscovery
)

from genesis_os.applications.application_resolution import (
    ApplicationResolutionEngine,
    ResolutionDecision,
)


def print_result(
    query: str,
    result,
) -> None:

    print()
    print("-" * 70)
    print(f"Query: {query}")
    print(f"Decision: {result.decision.value}")
    print(
        f"Confidence: "
        f"{result.confidence.value}"
    )
    print(
        f"Score: "
        f"{result.score}"
    )

    if result.application:

        print(
            f"Resolved application: "
            f"{result.application.get('name')}"
        )

    print("Reasons:")

    for reason in result.reasons:

        print(
            f"  - {reason}"
        )

    if result.candidates:

        print("Candidates:")

        for candidate in (
            result.candidates[:5]
        ):

            print(
                f"  - "
                f"{candidate.name} "
                f"| score={candidate.score}"
            )

            for evidence in (
                candidate.evidence[:3]
            ):

                print(
                    f"      "
                    f"{evidence.signal}: "
                    f"{evidence.score}"
                )

    print(
        "Safety:",
        result.safety
    )


def assert_resolved_to(
    engine,
    query: str,
    expected_name: str,
) -> None:

    result = engine.resolve(
        query
    )

    print_result(
        query,
        result
    )

    assert (
        result.decision
        == ResolutionDecision.RESOLVED
    ), (
        f"Expected '{query}' to resolve."
    )

    assert result.application is not None

    actual = result.application.get(
        "name"
    )

    assert (
        actual.lower()
        == expected_name.lower()
    ), (
        f"Expected '{expected_name}', "
        f"got '{actual}'."
    )

    assert (
        result.safety.get(
            "resolution_only"
        )
        is True
    )

    assert (
        result.safety.get(
            "execution_allowed"
        )
        is False
    )


def main():

    print("=" * 70)
    print(
        "GENESIS OS — APPLICATION "
        "RESOLUTION INTELLIGENCE"
    )
    print("=" * 70)

    # ---------------------------------------------------------
    # Build discovery
    # ---------------------------------------------------------

    print()
    print(
        "[1] Building unified application index..."
    )

    discovery = (
        UnifiedApplicationDiscovery()
    )

    applications = discovery.discover()

    print(
        f"[Discovery] "
        f"{len(applications)} applications available."
    )

    assert applications, (
        "Unified application discovery returned no applications."
    )

    # ---------------------------------------------------------
    # Create resolver
    # ---------------------------------------------------------

    print()
    print(
        "[2] Creating resolution engine..."
    )

    engine = (
        ApplicationResolutionEngine(
            discovery=discovery
        )
    )

    print(
        f"[Resolver] Version "
        f"{engine.VERSION}"
    )

    # ---------------------------------------------------------
    # Exact names
    # ---------------------------------------------------------

    print()
    print(
        "[3] Testing exact application names..."
    )

    assert_resolved_to(
        engine,
        "Google Chrome",
        "Google Chrome",
    )

    assert_resolved_to(
        engine,
        "Calculator",
        "Calculator",
    )

    assert_resolved_to(
        engine,
        "Settings",
        "Settings",
    )

    assert_resolved_to(
        engine,
        "Notepad",
        "Notepad",
    )

    # ---------------------------------------------------------
    # Human aliases
    # ---------------------------------------------------------

    print()
    print(
        "[4] Testing human application aliases..."
    )

    assert_resolved_to(
        engine,
        "chrome",
        "Google Chrome",
    )

    assert_resolved_to(
        engine,
        "vscode",
        "Visual Studio Code",
    )

    assert_resolved_to(
        engine,
        "explorer",
        "File Explorer",
    )

    assert_resolved_to(
        engine,
        "calc",
        "Calculator",
    )

    # ---------------------------------------------------------
    # Natural command prefixes
    # ---------------------------------------------------------

    print()
    print(
        "[5] Testing natural command prefixes..."
    )

    assert_resolved_to(
        engine,
        "open chrome",
        "Google Chrome",
    )

    assert_resolved_to(
        engine,
        "launch vscode",
        "Visual Studio Code",
    )

    assert_resolved_to(
        engine,
        "start calculator",
        "Calculator",
    )

    # ---------------------------------------------------------
    # Abbreviation
    # ---------------------------------------------------------

    print()
    print(
        "[6] Testing abbreviation intelligence..."
    )

    result = engine.resolve(
        "vscode"
    )

    assert result.application is not None

    print_result(
        "vscode",
        result
    )

    # ---------------------------------------------------------
    # Non-installed application
    # ---------------------------------------------------------

    print()
    print(
        "[7] Testing unavailable application..."
    )

    whatsapp = engine.resolve(
        "whatsapp"
    )

    print_result(
        "whatsapp",
        whatsapp
    )

    assert (
        whatsapp.decision
        == ResolutionDecision.NOT_FOUND
    ), (
        "WhatsApp should not resolve "
        "when it is not discovered."
    )

    # ---------------------------------------------------------
    # Unknown application
    # ---------------------------------------------------------

    print()
    print(
        "[8] Testing unknown application..."
    )

    unknown = engine.resolve(
        "genesis completely imaginary application"
    )

    print_result(
        "genesis completely imaginary application",
        unknown
    )

    assert (
        unknown.decision
        == ResolutionDecision.NOT_FOUND
    )

    # ---------------------------------------------------------
    # Safety
    # ---------------------------------------------------------

    print()
    print(
        "[9] Testing resolution/execution separation..."
    )

    chrome = engine.resolve(
        "chrome"
    )

    assert chrome.application is not None

    assert (
        chrome.safety[
            "resolution_only"
        ]
        is True
    )

    assert (
        chrome.safety[
            "execution_allowed"
        ]
        is False
    )

    print(
        "Resolution does not execute applications: PASS"
    )

    # ---------------------------------------------------------
    # Final
    # ---------------------------------------------------------

    print()
    print("=" * 70)
    print(
        "GENESIS OS — APPLICATION RESOLUTION "
        "INTELLIGENCE TEST COMPLETE"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()