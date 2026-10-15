import os
import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real OSManager and real ApplicationManager against the installed Windows app registry.
# --------------------------------------------------------------
pytestmark = pytest.mark.live
"""
Genesis OS — Level 3.2 Application Intelligence Tests
"""

from genesis_os.os_manager import OSManager
from genesis_os.applications.app_manager import ApplicationManager


def test_manager_initialization():

    manager = ApplicationManager()

    assert manager is not None

    print(
        "[PASS] ApplicationManager initialization"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows executable resolution contract")
def test_application_resolution():

    manager = ApplicationManager()

    executable = (
        manager.resolve_application(
            "notepad"
        )
    )

    assert executable is not None

    print(
        "[PASS] Notepad resolution"
    )

    print(
        f"       Resolved: {executable}"
    )


def test_application_inspection():

    manager = OSManager()

    result = (
        manager.inspect_application(
            "notepad"
        )
    )

    assert isinstance(
        result,
        dict
    )

    assert (
        result.get("operation")
        == "application.inspect"
    )

    print(
        "[PASS] Application inspection"
    )

    print(
        f"       Result: {result}"
    )


def test_unknown_application():

    manager = OSManager()

    result = (
        manager.inspect_application(
            "this_application_does_not_exist_12345"
        )
    )

    assert isinstance(
        result,
        dict
    )

    assert result.get(
        "success"
    ) is False

    print(
        "[PASS] Unknown application handled safely"
    )


def test_os_status():

    manager = OSManager()

    status = manager.status()

    assert status["level"] == 3

    assert (
        status["application_intelligence"]
        is True
    )

    assert (
        status["file_intelligence"]
        is True
    )

    print(
        "[PASS] Level 3 OS status"
    )


if __name__ == "__main__":

    print()
    print(
        "=" * 60
    )
    print(
        "GENESIS OS — LEVEL 3.2 TESTS"
    )
    print(
        "=" * 60
    )
    print()

    test_manager_initialization()
    test_application_resolution()
    test_application_inspection()
    test_unknown_application()
    test_os_status()

    print()
    print(
        "=" * 60
    )
    print(
        "ALL LEVEL 3.2 TESTS PASSED"
    )
    print(
        "=" * 60
    )
