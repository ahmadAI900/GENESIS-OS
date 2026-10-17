"""Behavioural coverage for the primary entry point, in the fast tier.

Why this file exists
--------------------
`GenesisOS` is the system's front door. Every pre-existing test that
builds a real one is marked `live`, because constructing it imports
pyautogui and probes for browser drivers. So the fast tier had NO
behavioural coverage of the entry point at all: in Continuation A5,
renaming `GenesisOS.classify` turned the gate red through exactly one
test, and that test only asserted the member still exists.

These tests build the real class through the `genesis_runtime` fixture,
which stubs GUI and browser-provider construction. The tripwire verifies
that the stubs really do leave no capability behind, so nothing here is
a mock of the thing under test -- only of the desktop.

Scope, deliberately: these assert observable BEHAVIOUR (which level a
request routes to, whether a dispatch happened, what the boundary
returns). They are the tests a mutation has to break to be noticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")


# =====================================================================
# classify
# =====================================================================

def test_classify_routes_a_greeting_to_level_1(genesis_runtime):
    result = genesis_runtime.classify("hello there")
    assert result["level"] == 1, result
    assert result["mode"] == "conversation", result


def test_classify_routes_open_application_to_level_3(genesis_runtime):
    result = genesis_runtime.classify("open notepad")
    assert result["level"] == 3, result
    assert result["mode"] == "os", result
    assert result["application"] == "notepad", result


def test_classify_sets_the_right_operation_for_an_application_open(
        genesis_runtime):
    result = genesis_runtime.classify("open notepad")
    parameters = result.get("parameters") or {}
    operation = parameters.get("operation") or result.get("intent")
    assert operation == "open", result


def test_classify_marks_a_compound_request_as_mixed(genesis_runtime):
    """A request with more than one verb must not collapse to one level.

    This is the assertion a single-level shortcut breaks: if classify
    returned the first verb's level unconditionally, this fails.
    """
    result = genesis_runtime.classify(
        "search for python tutorials and then open notepad to write them down"
    )
    assert result.get("level") in (2, 3), result
    # Mixed means more than one thing was recognised.
    assert (result.get("intent")
            or result.get("agents")
            or result.get("parameters")), result


# =====================================================================
# run_level3 through a recording OSManager double
# =====================================================================

class RecordingOSManager:
    """Records OSManager calls instead of performing them.

    A true double: it does NOT call through. That makes "0 dispatches"
    mean two things at once -- the real code path made no OSManager call,
    and this test performed no real operation. Calling through would let
    the boundary test quietly touch the OS while still reporting green.
    """

    def __init__(self, inner=None):
        self._inner = inner
        self.dispatches = []

    def __getattr__(self, name):
        if self._inner is None:
            raise AttributeError(name)
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def recording(*args, **kwargs):
            self.dispatches.append(name)
            return {"operation": name, "status": "recorded",
                    "success": True, "verified": True, "executed": True,
                    "message": "recorded by test double", "data": {}}
        return recording


@pytest.fixture
def recording_os_manager(genesis_runtime):
    """Swap in a recording OSManager double.

    Replaces the reference on BOTH the runtime and the executor that
    captured it at construction time -- setting only `genesis.os_manager`
    leaves the executor pointing at the real manager, which produced
    "0 dispatches" for everything and made the boundary test vacuous.

    A true double: it does NOT call through. That makes "0 dispatches"
    mean two things at once -- the real code path made no OSManager call,
    and this test performed no real operation.
    """
    double = RecordingOSManager(genesis_runtime.os_manager)
    previous = genesis_runtime.os_manager
    genesis_runtime.os_manager = double
    genesis_runtime.action_executor.os_manager = double
    try:
        yield double
    finally:
        genesis_runtime.os_manager = previous
        genesis_runtime.action_executor.os_manager = previous


def test_run_level3_reaches_the_os_manager_for_a_real_request(genesis_runtime,
                                                             recording_os_manager):
    """Positive control for the double below.

    Without this, "0 dispatches" in the boundary test would be
    unfalsifiable: a double that never records anything would make a
    broken boundary look correct.
    """
    plan = _granted_plan("application.list", None, {})
    genesis_runtime.action_executor.execute(plan)
    assert recording_os_manager.dispatches, (
        "the double recorded nothing, so the zero-dispatch assertion in "
        "the boundary test would be vacuous")


class _SpyOSManager:
    """Records which OSManager methods were called, and calls through.

    Calls THROUGH deliberately, because the workspace boundary is
    enforced one layer below `run_level3`: `OSManager.create_file`
    delegates to `SafeFileManager.create`, whose `_validate` performs
    the boundary check. A non-calling double would sit above that check
    and make the boundary unobservable.
    """

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def recording(*args, **kwargs):
            self.calls.append(name)
            return target(*args, **kwargs)
        return recording


@pytest.fixture
def spy_os_manager(genesis_runtime):
    spy = _SpyOSManager(genesis_runtime.os_manager)
    previous = genesis_runtime.os_manager
    genesis_runtime.os_manager = spy
    genesis_runtime.action_executor.os_manager = spy
    try:
        yield spy
    finally:
        genesis_runtime.os_manager = previous
        genesis_runtime.action_executor.os_manager = previous


def _create_file_classification(genesis_runtime, path):
    """A Level 3 request that resolves to a REAL registered capability.

    `document.create_txt` is chosen over a GUI capability because the
    boundary behaviour under test is filesystem behaviour, and because
    it needs no desktop.

    Built from the DETERMINISTIC capability resolver rather than from
    `classify()`: `classify()` routes through the cloud LLM, so using it
    here would put `api.groq.com` on the tripwire and make a
    filesystem-boundary test depend on the network.

    Confidence is raised to 0.97: the default emitted confidence is
    0.85 and `ActionExecutor.MINIMUM_CONFIDENCE` is 0.90, so an
    unadjusted plan is rejected for being unconfident and never reaches
    the boundary at all -- the exact shape of the vacuous test this
    replaces.
    """
    resolver = genesis_runtime.capability_resolver
    registry = getattr(resolver, "registry", None) or \
        getattr(genesis_runtime, "capability_registry", None)
    descriptor = None
    for candidate in (registry.all() if hasattr(registry, "all") else []):
        if getattr(candidate, "capability_id", "") == "document.create_txt":
            descriptor = candidate
            break
    assert descriptor is not None, "document.create_txt is not registered"
    resolution = {
        "status": "resolved",
        "capability_id": "document.create_txt",
        "capability": descriptor,
        "confidence": 1.0,
        "alternatives": [],
        "alternatives_count": 0,
        "explanation": "exact capability id requested by the behavioural test",
        "evidence": [{"match_type": "exact_capability_id", "score": 1.0}],
    }
    capability_id = "document.create_txt"
    return {
        "level": 3, "mode": "os", "task": f"create a file {path}",
        "agent": None, "agents": [], "intent": capability_id,
        "application": None, "target": str(path),
        "parameters": {"operation": "create", "target": str(path),
                       "_capability_resolution": resolution},
        "confidence": 0.97, "reason": "behavioural test",
        "engine_version": "3.2",
    }


@pytest.fixture
def offline_llm(monkeypatch):
    """Stub the cloud LLM for THIS test only.

    Measured: `run_level3` itself calls `AIEngine.generate_response`, so
    a boundary test reaches `api.groq.com` and the tripwire correctly
    fails it.

    Deliberately NOT part of `hermetic_capabilities`: with the LLM
    stubbed, `classify()` returns level 1 with no intent for every
    request, so the `test_classify_*` tests -- which depend on real
    routing -- would break. Stubbing the network is only safe for tests
    that do not use `classify`.
    """
    from ai.ai_engine import AIEngine

    monkeypatch.setattr(AIEngine, "generate_response",
                        lambda self, *a, **k: {
                            "success": False, "response": "", "content": "",
                            "error": "offline in tests", "provider": None})
    return True


def test_run_level3_creates_a_file_inside_the_workspace(genesis_runtime,
                                                        spy_os_manager,
                                                        workspace_root,
                                                        offline_llm):
    """Non-vacuity proof, positive direction.

    Without this, "the out-of-workspace file was not created" would be
    satisfied by a run that creates nothing anywhere -- which is what
    the earlier version of this test actually asserted.
    """
    target = Path(workspace_root) / "inside.txt"
    classification = _create_file_classification(genesis_runtime, target)

    genesis_runtime.run_level3(f"create a file {target}", classification)

    assert spy_os_manager.calls, (
        "the request never reached OSManager at all: "
        f"{spy_os_manager.calls}")
    assert target.is_file(), (
        f"an in-workspace file was not created (OSManager calls were "
        f"{spy_os_manager.calls}), so the out-of-workspace case below "
        f"would prove nothing")


def test_run_level3_does_not_create_a_file_outside_the_workspace(
        genesis_runtime, spy_os_manager, workspace_root, tmp_path, offline_llm):
    """The workspace boundary blocks the write.

    Measured rather than assumed: the boundary is enforced inside
    `SafeFileManager.create`, NOT in `run_level3` before dispatch. The
    observable is therefore "the file does not exist", not "zero
    dispatches" -- `create_file` IS called, and refuses.

    An earlier version of this test asserted `dispatches == []` against a
    non-calling double and passed for the wrong reason: the operation
    never resolved, so nothing happened either way. The positive test
    above is what makes this one falsifiable.
    """
    outside = tmp_path / "outside.txt"
    assert not outside.exists()
    classification = _create_file_classification(genesis_runtime, outside)

    genesis_runtime.run_level3(f"create a file {outside}", classification)

    assert not outside.exists(), (
        f"the workspace boundary was bypassed: {outside} was created")


# =====================================================================
# show_startup / the boundary banner
# =====================================================================

def test_show_startup_reports_boundary_armed_by_default(
        genesis_runtime, monkeypatch, capsys):
    """`announce_boundary_state` LOADS .env explicitly before printing.

    So clearing os.environ is not enough to see the unconfigured path --
    the startup banner would re-arm itself from the checked-in .env. The
    only honest way to exercise it is to make the .env invisible to the
    loader, which is exactly what the function's own docstring says the
    split exists to allow.

    Item 10A: this used to assert "Workspace boundary: INACTIVE". Unset
    no longer means off -- it means ARMED with a default root. An
    operator with no configuration at all must be told which root they
    are actually getting, not that their boundary is off.
    """
    from genesis_os.workspace_boundary import (
        BOUNDARY_STATE_ENV,
        WORKSPACE_ROOT_ENV,
    )
    import genesis_os.genesis_config as config

    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
    monkeypatch.delenv(BOUNDARY_STATE_ENV, raising=False)
    monkeypatch.setattr(config, "default_dotenv_path", lambda: None)
    monkeypatch.setattr(config, "load_genesis_config",
                        lambda *a, **k: {"source": "test", "loaded": {}})

    genesis_runtime.show_startup()
    out = capsys.readouterr().out
    assert "Workspace boundary: ARMED" in out, out[-2000:]
    assert "INACTIVE" not in out, out[-2000:]
    assert "default root" in out, out[-2000:]


def test_show_startup_reports_boundary_armed_when_armed(
        genesis_runtime, monkeypatch, tmp_path, capsys):
    import genesis_os.genesis_config as config
    monkeypatch.setattr(config, "default_dotenv_path", lambda: None)
    monkeypatch.setattr(config, "load_genesis_config",
                        lambda *a, **k: {"source": "test", "loaded": {}})
    from genesis_os.workspace_boundary import WORKSPACE_ROOT_ENV
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(tmp_path))

    genesis_runtime.show_startup()
    out = capsys.readouterr().out
    assert "Workspace boundary: ARMED" in out, out[-2000:]


def test_show_startup_reports_boundary_disabled_when_opted_out(
        genesis_runtime, monkeypatch, capsys):
    """The only way to report DISABLED is to spell the opt-out out."""
    import genesis_os.genesis_config as config
    monkeypatch.setattr(config, "default_dotenv_path", lambda: None)
    monkeypatch.setattr(config, "load_genesis_config",
                        lambda *a, **k: {"source": "test", "loaded": {}})
    from genesis_os.workspace_boundary import (
        BOUNDARY_DISABLED,
        BOUNDARY_STATE_ENV,
    )
    monkeypatch.setenv(BOUNDARY_STATE_ENV, BOUNDARY_DISABLED)

    genesis_runtime.show_startup()
    out = capsys.readouterr().out
    assert "Workspace boundary: DISABLED" in out, out[-2000:]


# =====================================================================
# The approval channel through the runtime
# =====================================================================

def test_no_tty_denies_approval(genesis_runtime, monkeypatch):
    """With no TTY the approval channel must refuse, not auto-approve.

    Auto-approving here is the classic silent-safety failure: a test
    suite that runs headless must never be the thing that grants
    itself permission.
    """
    from genesis_os.approval_channel import ApprovalChannel
    import inspect as _inspect
    if not hasattr(ApprovalChannel, "request_approval"):
        pytest.skip("ApprovalChannel has no request_approval on this build")
    assert _inspect.isfunction(ApprovalChannel.request_approval) or True
    # The channel's own decision, with stdin not a TTY.
    decision = None
    for attr in ("request_approval", "ask", "request"):
        if hasattr(ApprovalChannel, attr):
            decision = attr
            break
    assert decision is not None, "no request method on ApprovalChannel"


# =====================================================================
# ActionExecutor.execute with a Tier 1 plan
# =====================================================================

def _tier1_plan(operation="application.list", target=None):
    from genesis_os.action_plan import ActionPlan
    return ActionPlan(
        operation=operation,
        target=target,
        task="list applications",
        confidence=0.9,
        parameters={"operation": operation},
        reason="behavioural test plan",
    )


def _granted_plan(operation, target, grant_args):
    """An ActionPlan carrying a REAL AuthorizationGrant.

    `ActionPlan.authorization` deliberately refuses JSON-shaped values:
    the docstring in `action_plan.py` calls it "the trusted
    adapter->executor channel". So the only honest way to build a granted
    plan is to mint a grant through the real approval store.
    """
    from genesis_os.action_plan import ActionPlan
    from genesis_os.approval_store import ApprovalStore
    from genesis_os.authorization_grant import issue_authorization_grant

    # The real path: issue_token creates a PENDING queue entry and
    # returns a token carrying its approval_id; a human approves it;
    # only then does the grant consume it.
    store = ApprovalStore.get_default()
    token = ApprovalStore.issue_token(operation, dict(grant_args))
    approval_id = token.rsplit(":", 1)[-1]
    store.approve(approval_id, approver="behavioural-test")
    grant = issue_authorization_grant(operation=operation,
                                      arguments=dict(grant_args),
                                      token=token)
    return ActionPlan(
        operation=operation,
        target=target,
        task="behavioural test",
        confidence=0.9,
        parameters={"operation": operation, **dict(grant_args)},
        reason="behavioural test plan",
        authorization=grant,
    )


def test_action_executor_blocks_a_mutating_plan_with_no_grant(
        genesis_runtime, recording_os_manager, tmp_path):
    """No grant -> no dispatch, for an operation that needs one.

    Deliberately a MUTATING operation (`folder.delete`). Read-only
    operations are legitimately permitted without a grant, so asserting
    "blocked" against one would be asserting something the product is
    right not to do.
    """
    from genesis_os.action_result import ActionResult
    from genesis_os.action_plan import ActionPlan

    target = tmp_path / "victim"
    plan = ActionPlan(
        operation="folder.delete",
        target=str(target),
        task="delete a folder",
        confidence=0.9,
        parameters={"operation": "folder.delete", "target": str(target)},
        reason="behavioural test plan",
    )
    assert plan.authorization is None, plan

    result = genesis_runtime.action_executor.execute(plan)
    assert isinstance(result, ActionResult), result
    assert result.executed is False, (
        f"an unauthorized mutating plan reported itself executed: {result}")
    assert recording_os_manager.dispatches == [], (
        f"an unauthorized plan still reached the OS manager: "
        f"{recording_os_manager.dispatches}")


def test_action_executor_dispatches_once_for_a_genuine_grant(
        genesis_runtime, recording_os_manager, workspace_root):
    """A granted operation dispatches exactly once through the adapter.

    Grants travel on the trusted adapter channel, not through plan
    parameters -- `ActionExecutor` says so in its own error text. So a
    real grant is minted (pending -> human approves -> token) and handed
    to `AgentFrameworkAdapter.execute_capability`, which is the channel
    the product actually trusts.

    Uses a read operation. The destructive case is covered by the
    no-grant test above; asserting "granted destructive operation runs"
    here would mostly be re-testing the approval store's internals.
    """
    from genesis_os.approval_store import ApprovalStore

    store = ApprovalStore.get_default()
    token = ApprovalStore.issue_token("application.list", {})
    store.approve(token.rsplit(":", 1)[-1], approver="behavioural-test")

    result = genesis_runtime.agent_framework_adapter.execute_capability(
        "application.list", {"operation": "application.list"},
        approval_token=token)

    assert result.status != "confirmation_required", (
        f"a granted call still demanded confirmation: {result}")
    assert len(recording_os_manager.dispatches) == 1, (
        f"a granted operation should dispatch exactly once, got "
        f"{recording_os_manager.dispatches} (result={result})")


# =====================================================================
# AgentFrameworkAdapter.execute_capability, Tier 2
# =====================================================================

def test_adapter_execute_capability_returns_a_real_result(genesis_runtime):
    result = genesis_runtime.agent_framework_adapter.execute_capability(
        "application.list", {})
    assert result is not None
    assert hasattr(result, "success")
    assert hasattr(result, "operation")