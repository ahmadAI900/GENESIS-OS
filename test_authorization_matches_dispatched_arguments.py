"""Item 20A (S14): the grant gate must check what will actually be dispatched.

Two holes, both reproduced by probe against `ActionExecutor.execute`
before this file was written:

  (1) TARGETLESS BYPASS. Every ``plan.target is None`` path returns
      BEFORE the blast-radius grant gate at the bottom of ``execute``.
      A Tier 1 targetless operation (``file.search`` against a path
      outside the workspace, no grant attached at all) therefore
      dispatched ``search_file`` and returned ``executed=True``.

  (2) DIVERGENT ARGUMENTS. The gate validated
      ``plan.authorization_arguments`` -- the dict the human approved --
      while ``_dispatch`` reads ``plan.parameters``. A grant for
      {source: A, destination: B} attached to a plan whose parameters
      say destination: C executed the move to C. An injected
      target-bearing argument the human never saw dispatched too.

Both are fail-open on an authorization path. The corrected contract
pinned here:

  * a Tier 1 plan clears the gate only when a valid grant covers the
    EXACT arguments -- and the target -- the executor will dispatch;
  * the gate runs on the targetless dispatch paths as well;
  * the approval seam binds the target it shows the human into the
    hashed arguments, so a grant approved for one target cannot be
    reattached to another target at all.

The controls (2, 4) must hold before AND after the fix: a genuine,
argument-matching grant still executes exactly once.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan, attach_authorization
from genesis_os.approval_store import ApprovalStore
from genesis_os.authorization_grant import issue_authorization_grant

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")


class _CountingOSM:
    """Records dispatches so 'did it execute' is provable."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a))
            return {
                "success": True, "operation": name, "executed": True,
                "verified": True, "file_exists": False, "folder_exists": False,
                "post_state_matches": True, "path": a[0] if a else None,
                "message": "ok", "result": {},
            }
        return call

    def dispatched(self, name):
        return [c for c in self.calls if c[0] == name]


def _grant(capability_id, arguments):
    token = ApprovalStore.issue_token(capability_id, dict(arguments))
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    return issue_authorization_grant(
        operation=capability_id, arguments=dict(arguments), token=token
    )


# ======================================================================
# (1) Targetless Tier 1 plans must hit the gate too
# ======================================================================
def _targetless_search_plan(outside: Path) -> ActionPlan:
    return ActionPlan(
        operation="file.search",
        target=None,
        parameters={"path": str(outside), "query": "*.txt"},
        confidence=0.99,
    )


def test_targetless_tier1_plan_without_a_grant_is_refused(tmp_path):
    """A Tier 1 targetless op with NO grant must not reach the manager.

    Before this item the target=None branch dispatched it ungated:
    `execute` returned executed=True with `search_file` called.
    """
    from genesis_os.action_executor import _operation_requires_authorization

    outside = tmp_path / "outside"
    outside.mkdir()
    plan = _targetless_search_plan(outside)
    assert _operation_requires_authorization(
        "file.search", None, plan.parameters
    ) is True, "premise broken: this search is not gated, test is void"

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(plan)

    assert result.status == "confirmation_required", (
        f"a targetless Tier 1 plan dispatched without a grant: "
        f"{result.status}"
    )
    assert result.executed is False
    assert not osm.dispatched("search_file"), osm.calls


def test_targetless_tier1_plan_with_a_genuine_grant_executes(tmp_path):
    """Control: the same plan with a grant over the SAME arguments runs.

    Green before the fix; must stay green after it.
    """
    from genesis_os.action_executor import _operation_requires_authorization

    outside = tmp_path / "outside"
    outside.mkdir()
    plan = _targetless_search_plan(outside)
    assert _operation_requires_authorization(
        "file.search", None, plan.parameters
    ) is True, "premise broken: this search is not gated, test is void"

    args = {"path": str(outside), "query": "*.txt"}
    granted = attach_authorization(plan, _grant("file.search", args),
                                   arguments=args)

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(granted)

    assert result.status != "confirmation_required", (
        f"a properly granted targetless search was gated: {result.status}"
    )
    assert len(osm.dispatched("search_file")) == 1, osm.calls


# ======================================================================
# (2) The grant must cover the arguments _dispatch will read
# ======================================================================
def test_grant_for_a_different_destination_is_refused(tmp_path):
    """The approved dict and the dispatched dict must be the same.

    Before this item the gate hashed authorization_arguments
    {source: A, destination: B} while _dispatch read parameters with
    destination: C -- and executed the move to C.
    """
    from genesis_os.action_executor import _operation_requires_authorization

    src = tmp_path / "a.txt"
    dst_b = tmp_path / "b.txt"
    dst_c = tmp_path / "c.txt"
    for f in (src, dst_b, dst_c):
        f.write_text("x", encoding="utf-8")

    approved = {"source": str(src), "destination": str(dst_b)}
    plan = ActionPlan(
        operation="file.move",
        target=str(src),
        parameters={"source": str(src), "destination": str(dst_c)},
        confidence=0.99,
    )
    assert _operation_requires_authorization(
        "file.move", None, plan.parameters
    ) is True, "premise broken: this move is not gated, test is void"

    granted = attach_authorization(
        plan, _grant("file.move", approved), arguments=approved
    )

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(granted)

    assert result.status == "confirmation_required", (
        f"a move to an UNAPPROVED destination executed: {result.status}"
    )
    assert result.executed is False
    assert not osm.dispatched("move_file"), osm.calls


def test_grant_for_the_dispatched_arguments_executes(tmp_path):
    """Control: approved arguments == dispatched arguments -> runs once.

    Green before the fix; must stay green after it.
    """
    from genesis_os.action_executor import _operation_requires_authorization

    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    for f in (src, dst):
        f.write_text("x", encoding="utf-8")

    args = {"source": str(src), "destination": str(dst)}
    plan = ActionPlan(
        operation="file.move",
        target=str(src),
        parameters=dict(args),
        confidence=0.99,
    )
    assert _operation_requires_authorization(
        "file.move", None, plan.parameters
    ) is True, "premise broken: this move is not gated, test is void"

    granted = attach_authorization(
        plan, _grant("file.move", args), arguments=args
    )

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(granted)

    assert result.status != "confirmation_required", (
        f"a matching grant was refused: {result.status}"
    )
    assert len(osm.dispatched("move_file")) == 1, osm.calls


def test_injected_target_bearing_argument_is_refused(tmp_path):
    """A target-bearing argument the human never approved must not run.

    The grant here covers only `destination`; the plan additionally
    carries `source`, so the dispatch would act on a path that was
    never part of any approval.
    """
    from genesis_os.action_executor import _operation_requires_authorization

    src = tmp_path / "unapproved-source.txt"
    dst = tmp_path / "dst.txt"
    for f in (src, dst):
        f.write_text("x", encoding="utf-8")

    approved = {"destination": str(dst)}
    plan = ActionPlan(
        operation="file.move",
        target=str(dst),
        parameters={"source": str(src), "destination": str(dst)},
        confidence=0.99,
    )
    assert _operation_requires_authorization(
        "file.move", None, plan.parameters
    ) is True, "premise broken: this move is not gated, test is void"

    granted = attach_authorization(
        plan, _grant("file.move", approved), arguments=approved
    )

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(granted)

    assert result.status == "confirmation_required", (
        f"an unapproved `source` path dispatched: {result.status}"
    )
    assert result.executed is False
    assert not osm.dispatched("move_file"), osm.calls


# ======================================================================
# (3) The approval seam must bind the target it shows the human
# ======================================================================
EXACT_PHRASE = "approve"


class FakeTTY(io.StringIO):
    """A stdin that claims to be a TTY (shape from test_approval_channel)."""

    def isatty(self) -> bool:
        return True


def _authorize(genesis_runtime, plan, typed=EXACT_PHRASE + "\n"):
    """Drive the seam with a fake TTY, returning (plan, denial)."""
    from genesis_os import approval_channel

    real_channel = approval_channel.ApprovalChannel
    stream = FakeTTY(typed)

    def channel_factory(*args, **kwargs):
        kwargs["stdin"] = stream
        kwargs["stdout"] = io.StringIO()
        kwargs["timeout"] = None
        return real_channel(*args, **kwargs)

    approval_channel.ApprovalChannel = channel_factory
    try:
        return genesis_runtime._authorize_plan_for_execution(plan)
    finally:
        approval_channel.ApprovalChannel = real_channel


def test_seam_approval_binds_the_target_the_human_saw(
    genesis_runtime, tmp_path
):
    """The prompt displays `target : ...`; the hash must cover it.

    The seam hashed only plan.parameters, so a plan whose parameters do
    not carry the path produced a grant bound to EMPTY arguments while
    the human was shown the target -- approval and authorization were
    about two different things.
    """
    victim = tmp_path / "outside-the-workspace.txt"
    victim.write_text("important", encoding="utf-8")

    plan, denial = _authorize(
        genesis_runtime,
        ActionPlan(
            operation="file.delete",
            target=str(victim),
            parameters={},
            confidence=0.99,
        ),
    )

    assert denial is None, denial
    assert plan is not None
    assert plan.authorization is not None, "no grant was attached"
    assert plan.authorization_arguments is not None
    assert str(plan.authorization_arguments.get("target")) == str(victim), (
        "the approved arguments must contain the target the human was "
        f"shown; got {sorted(plan.authorization_arguments)}"
    )


def test_a_seam_grant_for_one_target_does_not_authorise_another(
    genesis_runtime, tmp_path
):
    """Reattaching a seam grant to a different target must be refused.

    With the seam hashing empty parameters, both plans produced the
    same (empty) arguments hash, so a grant approved for one file
    validated for the other and the second delete executed.
    """
    victim = tmp_path / "victim.txt"
    other = tmp_path / "must-survive.txt"
    victim.write_text("important", encoding="utf-8")
    other.write_text("important", encoding="utf-8")

    granted, denial = _authorize(
        genesis_runtime,
        ActionPlan(
            operation="file.delete",
            target=str(victim),
            parameters={},
            confidence=0.99,
        ),
    )
    assert denial is None, denial
    assert granted is not None

    swapped = ActionPlan(
        operation="file.delete",
        target=str(other),
        parameters={},
        confidence=0.99,
    )
    reused = attach_authorization(
        swapped, granted.authorization,
        arguments=granted.authorization_arguments,
    )

    from genesis_os.action_executor import ActionExecutor

    result = ActionExecutor(genesis_runtime.os_manager).execute(reused)
    assert result.status == "confirmation_required", (
        f"a grant for one target authorized a delete of another: "
        f"{result.status}"
    )
    assert result.executed is False
    assert other.exists(), "a grant for path A must not delete path B"


# ======================================================================
# (4) S16: the gate must classify the target _dispatch will act on
# ======================================================================
def test_file_create_overwriting_existing_target_is_refused(workspace_root):
    """The target carries the path; parameters carry only content/overwrite.

    Before S16 the gate hashed only ``plan.parameters``, so it saw no
    ``path`` and did not run the overwrite evaluator. The dispatcher,
    however, used ``plan.target`` and overwrote the existing file with
    no grant.
    """
    existing = workspace_root / "keep-me.txt"
    existing.write_text("ORIGINAL", encoding="utf-8")

    plan = ActionPlan(
        operation="file.create",
        target=str(existing),
        parameters={"content": "PWNED", "overwrite": True},
        confidence=0.99,
    )

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(plan)

    assert result.status == "confirmation_required", (
        "file.create overwrote an existing target without approval: "
        f"{result.status}"
    )
    assert result.executed is False
    assert not osm.dispatched("create_file"), osm.calls
    assert existing.read_text(encoding="utf-8") == "ORIGINAL"


def test_file_create_target_with_matching_grant_executes(workspace_root):
    """Control: approval over the acted-on path is still accepted."""
    existing = workspace_root / "replace-me.txt"
    existing.write_text("ORIGINAL", encoding="utf-8")

    args = {
        "path": str(existing),
        "content": "APPROVED",
        "overwrite": True,
    }
    plan = ActionPlan(
        operation="file.create",
        target=str(existing),
        parameters={"content": "APPROVED", "overwrite": True},
        confidence=0.99,
    )
    granted = attach_authorization(
        plan, _grant("file.create", args), arguments=args
    )

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(granted)

    assert result.status != "confirmation_required", result.to_dict()
    assert len(osm.dispatched("create_file")) == 1, osm.calls


def test_file_rename_onto_existing_via_target_source_is_refused(
    workspace_root, monkeypatch
):
    """The bare ``new_name`` resolves beside the target source, not CWD."""
    monkeypatch.chdir(workspace_root)
    source = workspace_root / "source.txt"
    existing = workspace_root / "already-there.txt"
    source.write_text("source", encoding="utf-8")
    existing.write_text("ORIGINAL", encoding="utf-8")

    plan = ActionPlan(
        operation="file.rename",
        target=str(source),
        parameters={"new_name": existing.name},
        confidence=0.99,
    )

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(plan)

    assert result.status == "confirmation_required", (
        "file.rename overwrote an existing target without approval: "
        f"{result.status}"
    )
    assert result.executed is False
    assert not osm.dispatched("rename_file"), osm.calls


def test_document_create_docx_onto_existing_target_is_refused(workspace_root):
    """A document target is acted on by dispatch even without a path param."""
    existing = workspace_root / "keep-me.docx"
    existing.write_text("ORIGINAL", encoding="utf-8")

    plan = ActionPlan(
        operation="document.create_docx",
        target=str(existing),
        parameters={"title": "Overwrite", "sections": []},
        confidence=0.99,
    )

    osm = _CountingOSM()
    result = ActionExecutor(osm).execute(plan)

    assert result.status == "confirmation_required", (
        "document.create_docx overwrote an existing target without "
        f"approval: {result.status}"
    )
    assert result.executed is False
    assert not osm.dispatched("doc_create"), osm.calls


def test_gate_and_dispatch_share_the_acted_on_arguments():
    """Meta-test: both halves call the one canonical argument helper."""
    import inspect

    from genesis_os.action_executor import _dispatch_arguments

    target = "C:/workspace/target.txt"
    path_plan = ActionPlan(
        operation="file.create",
        target=target,
        parameters={"content": "x", "overwrite": True},
        confidence=0.99,
    )
    assert _dispatch_arguments(path_plan)["path"] == target

    search_plan = ActionPlan(
        operation="file.search",
        target="*.txt",
        parameters={"path": "C:/workspace", "query": "*.txt"},
        confidence=0.99,
    )
    searched = _dispatch_arguments(search_plan)
    assert searched["path"] == "C:/workspace"
    assert searched.get("path") != search_plan.target

    gate_source = inspect.getsource(ActionExecutor._authorization_gate)
    dispatch_source = inspect.getsource(ActionExecutor._dispatch)
    assert "_dispatch_arguments(plan)" in gate_source, (
        "the gate stopped using the dispatcher's canonical arguments"
    )
    assert "_dispatch_arguments(plan)" in dispatch_source, (
        "the dispatcher stopped using the same canonical arguments"
    )
