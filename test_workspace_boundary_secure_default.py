"""Directive 10A (S1): the workspace boundary must not be silently OFF.

`workspace_boundary.workspace_root()` returned None whenever
`GENESIS_WORKSPACE_ROOT` was unset, and every caller read that None as
"not escaping":

    arguments_escape_workspace()  -> None   (line ~426)
    boundary_is_enforced()        -> False  (line ~291)

So with no `.env` present -- a fresh clone, a CI job, a test run with the
environment scrubbed -- Genesis ran with the boundary INACTIVE. The
module documented unset as "the deliberate off-switch", but nobody
CHOOSE it off; the variable was simply missing, and nothing said so.

Reproduced before the fix, with GENESIS_WORKSPACE_ROOT unset:

    workspace_root()                          -> None
    arguments_escape_workspace(<outside>)     -> None
    _operation_requires_authorization(...)    -> False

A read of C:/Users/Public/secret.txt was not gated and did not escalate.

After, unset means ARMED with a default root, and turning the control
off requires naming that decision:

    UNSET                             -> ARMED with a default root
    GENESIS_WORKSPACE_ROOT=<path>      -> ARMED with that root
    GENESIS_WORKSPACE_BOUNDARY=disabled-> off, but only if spelled out
    root set but broken               -> BoundaryConfigurationError
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

OUTSIDE = "C:/Users/Public/definitely-outside-the-workspace.txt"


@pytest.fixture(autouse=True)
def _unconfigured(monkeypatch):
    """Every test here runs with BOTH variables absent.

    Autouse, so a developer with a populated .env still exercises the
    unconfigured path rather than silently testing the configured one.
    """
    monkeypatch.delenv("GENESIS_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("GENESIS_WORKSPACE_BOUNDARY", raising=False)


# =====================================================================
# (i) unset must mean ARMED, not inactive
# =====================================================================

def test_unset_returns_a_root_not_none():
    """The regression. Fails before Item 10A: returned None."""
    from genesis_os.workspace_boundary import workspace_root

    root = workspace_root()

    assert root is not None, (
        "an unset GENESIS_WORKSPACE_ROOT must still yield a root; "
        "returning None is what silently disarmed the boundary"
    )
    assert root.is_dir(), root


def test_unset_means_the_boundary_is_enforced():
    from genesis_os.workspace_boundary import boundary_is_enforced

    assert boundary_is_enforced() is True


def test_unset_gates_an_out_of_workspace_read():
    """The gate consequence, not just the return value."""
    from genesis_os.workspace_boundary import arguments_escape_workspace

    escape = arguments_escape_workspace(
        {"path": OUTSIDE}, capability_id="spreadsheet.read"
    )

    assert escape, (
        "an out-of-workspace read was not gated because "
        "GENESIS_WORKSPACE_ROOT was merely missing"
    )


def test_unset_escalates_that_read_to_tier_1():
    """And it therefore reaches the executor's authorisation gate."""
    from genesis_os.action_executor import (
        _operation_requires_authorization as requires,
    )

    assert requires(
        "spreadsheet.read", None, {"path": OUTSIDE}
    ) is True


def test_the_default_root_is_the_repo_convention_not_home_or_backend():
    """Justified explicitly in the commit: the default is the SIBLING of
    the backend tree, which is what this repo's .env already uses."""
    from genesis_os.workspace_boundary import (
        DEFAULT_WORKSPACE_DIRNAME,
        workspace_root,
    )

    root = workspace_root()
    backend = pathlib_backend()

    assert root.name == DEFAULT_WORKSPACE_DIRNAME
    assert root.parent == backend.parent, (
        f"the default root must be a sibling of backend/, not inside it: "
        f"{root}"
    )
    assert root != pathlib_home(), (
        "the default root must not be the user's home; that would gate "
        "almost nothing while reporting itself armed"
    )


def pathlib_backend():
    import pathlib

    return pathlib.Path(__file__).resolve().parent


def pathlib_home():
    import pathlib

    return pathlib.Path.home().resolve()


# =====================================================================
# (ii) explicit opt-out
# =====================================================================

def test_explicit_disabled_returns_none_and_says_disabled(monkeypatch):
    from genesis_os.workspace_boundary import (
        boundary_banner_text,
        workspace_root,
    )

    monkeypatch.setenv("GENESIS_WORKSPACE_BOUNDARY", "disabled")

    assert workspace_root() is None
    banner = boundary_banner_text()
    assert "DISABLED" in banner, banner
    assert "disabled" in banner, banner


def test_disabled_allows_an_out_of_workspace_path(monkeypatch):
    from genesis_os.workspace_boundary import arguments_escape_workspace

    monkeypatch.setenv("GENESIS_WORKSPACE_BOUNDARY", "disabled")

    assert not arguments_escape_workspace(
        {"path": OUTSIDE}, capability_id="spreadsheet.read"
    )


@pytest.mark.parametrize(
    "typo",
    ["DISABLED", "Disabled", "off", "false", "0", "no", "", "disable", " "],
)
def test_a_typo_does_not_disable_the_boundary(monkeypatch, typo):
    """Matched EXACTLY. A control a typo disarms is not a control."""
    from genesis_os.workspace_boundary import workspace_root

    monkeypatch.setenv("GENESIS_WORKSPACE_BOUNDARY", typo)

    root = workspace_root()

    if typo.strip() == "":
        # An empty value is not the word "disabled", so still armed.
        assert root is not None, f"{typo!r} must not disable the boundary"
    else:
        assert root is not None, f"{typo!r} must not disable the boundary"


# =====================================================================
# (iii) a configured root behaves exactly as before
# =====================================================================

def test_a_configured_root_is_used_unchanged(tmp_path):
    from genesis_os.workspace_boundary import (
        boundary_banner_text,
        workspace_root,
    )

    configured = tmp_path / "ws"
    configured.mkdir()
    monkey = pytest.MonkeyPatch()
    monkey.setenv("GENESIS_WORKSPACE_ROOT", str(configured))
    try:
        assert workspace_root() == configured.resolve()
        banner = boundary_banner_text()
        assert "ARMED" in banner, banner
        assert "default root" not in banner, banner
    finally:
        monkey.undo()


def test_a_path_inside_the_configured_root_is_not_gated(tmp_path):
    from genesis_os.workspace_boundary import arguments_escape_workspace

    configured = tmp_path / "ws"
    configured.mkdir()
    inside = configured / "a.txt"
    inside.write_text("x", encoding="utf-8")

    monkey = pytest.MonkeyPatch()
    monkey.setenv("GENESIS_WORKSPACE_ROOT", str(configured))
    try:
        assert not arguments_escape_workspace(
            {"path": str(inside)}, capability_id="spreadsheet.read"
        )
    finally:
        monkey.undo()


def test_set_but_broken_still_fails_closed(monkeypatch):
    """Preserved from before Item 10A: a broken root RAISES."""
    from genesis_os.workspace_boundary import (
        BoundaryConfigurationError,
        workspace_root,
    )

    monkeypatch.setenv(
        "GENESIS_WORKSPACE_ROOT", "C:/definitely/not/a/real/dir"
    )

    with pytest.raises(BoundaryConfigurationError):
        workspace_root()


def test_set_but_empty_still_fails_closed(monkeypatch):
    from genesis_os.workspace_boundary import (
        BoundaryConfigurationError,
        workspace_root,
    )

    monkeypatch.setenv("GENESIS_WORKSPACE_ROOT", "   ")

    with pytest.raises(BoundaryConfigurationError):
        workspace_root()


# =====================================================================
# Banner states
# =====================================================================

def test_the_banner_names_the_default_root_when_unset():
    from genesis_os.workspace_boundary import boundary_banner_text

    banner = boundary_banner_text()

    assert "ARMED" in banner, banner
    assert "default root" in banner, banner


def test_the_banner_no_longer_claims_inactive():
    """'INACTIVE (not set)' was the lie. It must not come back."""
    from genesis_os.workspace_boundary import boundary_banner_text

    assert "INACTIVE" not in boundary_banner_text()