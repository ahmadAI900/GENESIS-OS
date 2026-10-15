"""
Genesis OS
Level 3.2.3C.1 — Application Identity & Confidence Engine
"""

from genesis_os.applications.application_identity import (
    ApplicationIdentityEngine,
    IdentityDecision,
)


def run_test(
    engine,
    title,
    first,
    second,
):

    print()
    print("-" * 70)
    print(title)
    print("-" * 70)

    result = engine.compare(
        first,
        second,
    )

    print(
        f"Decision: {result.decision.value}"
    )

    print(
        f"Confidence: {result.confidence}"
    )

    print(
        "Reasons:"
    )

    for reason in result.reasons:

        print(
            f"  - {reason}"
        )

    print(
        "Evidence:"
    )

    for evidence in result.evidence:

        print(
            f"  - "
            f"{evidence.signal} "
            f"[{evidence.score}] "
            f"{evidence.description}"
        )

    if result.conflicts:

        print(
            "Conflicts:"
        )

        for conflict in result.conflicts:

            print(
                f"  - {conflict}"
            )

    return result


def main():

    print("=" * 70)

    print(
        "GENESIS OS — APPLICATION IDENTITY "
        "& CONFIDENCE ENGINE"
    )

    print("=" * 70)

    engine = (
        ApplicationIdentityEngine()
    )

    # =====================================================
    # TEST 1 — SAME APPID
    # =====================================================

    chrome_a = {
        "name": "Google Chrome",
        "app_id": "Chrome",
        "type": "registered_application",
    }

    chrome_b = {
        "name": "Google Chrome",
        "app_id": "Chrome",
        "type": "registered_application",
    }

    result = run_test(
        engine,
        "TEST 1 — Exact AppID Match",
        chrome_a,
        chrome_b,
    )

    assert (
        result.decision
        == IdentityDecision.SAME
    )

    # =====================================================
    # TEST 2 — SAME PACKAGE
    # =====================================================

    calculator_a = {
        "name": "Calculator",
        "package_name":
            "Microsoft.WindowsCalculator",
        "package_family_name":
            "Microsoft.WindowsCalculator_8wekyb3d8bbwe",
    }

    calculator_b = {
        "name":
            "Microsoft.WindowsCalculator",
        "package_name":
            "Microsoft.WindowsCalculator",
        "package_family_name":
            "Microsoft.WindowsCalculator_8wekyb3d8bbwe",
    }

    result = run_test(
        engine,
        "TEST 2 — Package Identity Match",
        calculator_a,
        calculator_b,
    )

    assert (
        result.decision
        == IdentityDecision.SAME
    )

    # =====================================================
    # TEST 3 — SAME EXECUTABLE
    # =====================================================

    notepad_a = {
        "name": "Notepad",
        "executable":
            r"C:\Windows\System32\notepad.exe",
    }

    notepad_b = {
        "name": "Notepad",
        "path":
            r"C:\Windows\System32\notepad.exe",
    }

    result = run_test(
        engine,
        "TEST 3 — Executable Identity Match",
        notepad_a,
        notepad_b,
    )

    assert (
        result.decision
        == IdentityDecision.SAME
    )

    # =====================================================
    # TEST 4 — SAME NAME ONLY
    # =====================================================

    unknown_a = {
        "name": "Example Application",
    }

    unknown_b = {
        "name": "Example Application",
    }

    result = run_test(
        engine,
        "TEST 4 — Name-Only Evidence",
        unknown_a,
        unknown_b,
    )

    print(
        "Name-only evidence must remain conservative."
    )

    # =====================================================
    # TEST 5 — DIFFERENT APPID
    # =====================================================

    edge = {
        "name": "Microsoft Edge",
        "app_id": "Microsoft.MicrosoftEdge",
    }

    chrome = {
        "name": "Google Chrome",
        "app_id": "Chrome",
    }

    result = run_test(
        engine,
        "TEST 5 — Conflicting AppIDs",
        edge,
        chrome,
    )

    assert (
        result.decision
        == IdentityDecision.DIFFERENT
    )

    # =====================================================
    # TEST 6 — DIFFERENT APPLICATIONS,
    #           SIMILAR NAMES
    # =====================================================

    visual_studio = {
        "name": "Visual Studio",
    }

    visual_studio_code = {
        "name": "Visual Studio Code",
    }

    result = run_test(
        engine,
        "TEST 6 — Similar Names Must Not Automatically Merge",
        visual_studio,
        visual_studio_code,
    )

    assert (
        result.decision
        != IdentityDecision.SAME
    )

    # =====================================================
    # COMPLETE
    # =====================================================

    print()
    print("=" * 70)

    print(
        "APPLICATION IDENTITY ENGINE TEST COMPLETE"
    )

    print("=" * 70)


if __name__ == "__main__":

    main()