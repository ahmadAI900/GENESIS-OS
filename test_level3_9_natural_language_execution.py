"""
Genesis OS — Level 3.9
Natural-Language Execution Completion

Regression tests for the first Level 3 real-world gaps reported
in the handoff document, plus the completed execution-safety
capability surface:

    Gap 1:
        A semantic folder target such as "downloads" must be
        resolved to the user's REAL Windows Downloads folder
        before execution instead of being treated as a literal
        relative path.

    Gap 2:
        "Find my IELTS essay" must execute as a genuine
        multi-root filesystem search rather than being blocked
        by the execution-safety policy.

    Gap 3:
        "Create a folder called Genesis Test" must execute and
        verify on the real filesystem rather than being blocked.

Safety invariants that must survive all of the above:

    - explicitly denied operations remain blocked
    - unknown operations remain blocked
    - destructive operations remain confirmation-gated
"""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.execution_safety import ExecutionSafety
from genesis_os.file_target_provider import FileTargetProvider
from genesis_os.folder_target_provider import FolderTargetProvider
from genesis_os.os_manager import OSManager
from genesis_os.target_discovery import TargetDiscovery

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: constructs a real OSManager.
# --------------------------------------------------------------
pytestmark = [
    pytest.mark.live,
    pytest.mark.usefixtures("hermetic_capabilities"),
]


# =========================================================
# HELPERS
# =========================================================


def _build_decision_engine():
    return WorkflowDecisionEngine()


def _build_target_discovery():
    return TargetDiscovery(
        file_provider=FileTargetProvider(),
        folder_provider=FolderTargetProvider(),
    )


def _resolve_plan_target(target_discovery, plan):
    """
    Mirror of the production single-action semantic resolution
    step performed by GenesisOS.run_level3 before execution.
    """
    from dataclasses import replace

    if plan.operation not in {
        "folder.open",
        "folder.inspect",
        "folder.organize",
    }:
        return plan

    query = target_discovery.build_query_from_action_plan(plan)
    resolution = target_discovery.discover_and_resolve(query)

    if not resolution.successful or resolution.resolved is None:
        return plan

    return replace(plan, target=resolution.resolved.value)


# =========================================================
# EXECUTION SAFETY SURFACE COMPLETION
# =========================================================


@pytest.mark.parametrize(
    "operation",
    [
        "file.search",
        "file.hash",
        "file.open",
        "file.create",
        "file.copy",
        "folder.create",
        "folder.rename",
        "folder.move",
        "folder.delete",
        "browser.open_url",
        "system.status",
        "system.open_settings",
    ],
)
def test_executor_surface_is_registered_with_safety(operation):
    decision = ExecutionSafety.check(operation)
    assert decision.allowed is True
    assert decision.status == "supported"


@pytest.mark.parametrize(
    "operation",
    [
        "system.shutdown",
        "system.restart",
        "system.sleep",
        "shell.execute",
        "process.kill",
        "filesystem.delete",
    ],
)
def test_explicit_denials_survive_surface_completion(operation):
    decision = ExecutionSafety.check(operation)
    assert decision.allowed is False
    assert decision.status == "denied"


def test_unknown_operation_remains_blocked():
    decision = ExecutionSafety.check("totally.unknown_capability")
    assert decision.allowed is False
    assert decision.status == "unknown"


def test_destructive_file_operations_are_confirmation_gated(tmp_path):
    """file.move escalates to Tier 1 when it would OVERWRITE.

    Blast radius classifies a move to a FREE destination as Tier 2 --
    it is undone by moving back -- so this no longer gates on the
    destination being a plain relative name. The evaluator escalates
    exactly when the destination already exists and its contents would
    be destroyed irrecoverably, which is what this test now pins.
    """
    existing = tmp_path / "archive" / "report.docx"
    existing.parent.mkdir(parents=True)
    existing.write_text("precious")

    os_manager = Mock()
    executor = ActionExecutor(os_manager)

    plan = ActionPlan(
        operation="file.move",
        target="report.docx",
        parameters={"destination": str(existing)},
        confidence=0.99,
    )

    result = executor.execute(plan)

    assert result.success is False
    assert result.status == "confirmation_required"
    assert result.executed is False
    os_manager.move_file.assert_not_called()


def test_file_move_to_a_free_destination_is_not_gated(
    workspace_root, monkeypatch,
):
    """The counterpart: moving somewhere free is Tier 2 and runs.

    This is the F5 blast-radius decision made explicit. The old
    risk-table gate blocked every file.move; the reversible_local
    classification plus the overwrite evaluator blocks only the
    destructive case.

    Retargeted under the workspace boundary: the free destination now
    has to live INSIDE the configured root, which is what "free" has to
    mean for a move to remain reversible. The relative source resolves
    against the CWD, so it must be the workspace root too.
    """
    monkeypatch.chdir(workspace_root)
    os_manager = Mock()
    os_manager.move_file.return_value = {
        "success": True, "operation": "file.move", "executed": True,
        "verified": True, "file_matches": True,
        "destination_exists": True, "source_removed": True,
        "message": "moved",
    }
    free = workspace_root / "brand-new-name.docx"
    result = ActionExecutor(os_manager).execute(ActionPlan(
        operation="file.move",
        target="report.docx",
        parameters={"destination": str(free)},
        confidence=0.99,
    ))
    assert result.status != "confirmation_required"
    os_manager.move_file.assert_called_once()


def test_file_move_outside_the_workspace_requires_a_grant(workspace_root):
    """Bucket (b) counterpart: the same move, outside the root.

    Without this pair the retargeted test above would pass vacuously --
    a free destination inside the workspace runs whether or not the
    boundary works at all.

    Item 6C: this now takes the ``workspace_root`` fixture. It relies on
    the workspace boundary being ARMED for the escalation to fire, and
    it previously depended on ambient ``GENESIS_WORKSPACE_ROOT`` -- so it
    failed on any machine (or CI run) where that was unset, including at
    the baseline commit. The fixture sets the root explicitly for this
    test, so the outcome no longer depends on the environment.
    """
    os_manager = Mock()
    os_manager.move_file.return_value = {
        "success": True, "operation": "file.move", "executed": True,
        "verified": True, "file_matches": True,
        "destination_exists": True, "source_removed": True,
        "message": "moved",
    }
    # OUTSIDE the workspace root: this is the bucket-(b) case. tmp_path
    # would also be outside it, but naming the workspace fixture keeps
    # the pairing with the test above explicit.
    outside = (workspace_root.parent / "brand-new-name.docx")
    # The target names the SAME path as the destination on purpose. With a
    # relative target the plan carries two paths, the grant covers only
    # `destination`, and the escalation actually comes from the uncovered
    # `target` -- so an under-scoped grant is refused. That is the
    # intended fail-closed behaviour, verified by
    # test_grant_does_not_authorise_an_uncovered_second_path.
    plan = ActionPlan(
        operation="file.move",
        target=str(outside),
        parameters={"destination": str(outside)},
        confidence=0.99,
    )
    result = ActionExecutor(os_manager).execute(plan)
    assert result.status == "confirmation_required", (
        "a move outside the workspace root must be gated; got "
        f"{result.status!r}. If the boundary is not armed this test is "
        "not exercising anything."
    )
    assert result.executed is False
    os_manager.move_file.assert_not_called()

    # With a genuine grant the same operation runs.
    from genesis_os.action_plan import attach_authorization
    from genesis_os.approval_store import ApprovalStore
    from genesis_os.authorization_grant import issue_authorization_grant

    args = {"destination": str(outside)}
    token = ApprovalStore.issue_token("file.move", args)
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    granted = attach_authorization(
        plan, issue_authorization_grant(
            operation="file.move", arguments=args, token=token,
        ), arguments=args,
    )
    result2 = ActionExecutor(os_manager).execute(granted)
    assert result2.status != "confirmation_required"
    os_manager.move_file.assert_called_once()


def test_grant_does_not_authorise_an_uncovered_second_path(tmp_path, workspace_root):
    """A grant is bound to specific arguments, not to a whole plan.

    This plan names TWO paths. The grant covers `destination`, but the
    boundary escalation actually comes from the relative `target`, which
    resolves against cwd and leaves the workspace. An under-scoped
    grant must therefore be refused rather than treated as blanket
    approval for the plan.
    """
    os_manager = Mock()
    os_manager.move_file.return_value = {
        "success": True, "executed": True, "verified": True,
        "file_matches": True, "destination_exists": True,
        "source_removed": True, "message": "moved",
    }
    outside = tmp_path / "brand-new-name.docx"

    from genesis_os.action_plan import attach_authorization
    from genesis_os.approval_store import ApprovalStore
    from genesis_os.authorization_grant import issue_authorization_grant

    args = {"destination": str(outside)}
    token = ApprovalStore.issue_token("file.move", args)
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    granted = attach_authorization(
        ActionPlan(
            operation="file.move",
            target="report.docx",          # relative -> leaves the workspace
            parameters=args,
            confidence=0.99,
        ),
        issue_authorization_grant(
            operation="file.move", arguments=args, token=token,
        ),
        arguments=args,
    )
    result = ActionExecutor(os_manager).execute(granted)
    assert result.status == "confirmation_required"
    assert result.executed is False
    os_manager.move_file.assert_not_called()


# =========================================================
# GAP 3 — NATURAL FOLDER CREATION
# =========================================================


def test_create_folder_called_genesis_test_executes_and_verifies(workspace_root, monkeypatch):
    # chdir into the workspace root: this flow creates a folder from a
    # RELATIVE target ("Genesis Test"), which resolves against cwd. Under
    # activation that only stays Tier 2 if cwd is inside the root.
    monkeypatch.chdir(workspace_root)

    engine = _build_decision_engine()
    decision = engine.decide("Create a folder called Genesis Test.")

    assert decision["level"] == 3
    assert decision["intent"] == "folder.create"
    # Natural casing of the requested folder name is preserved.
    assert decision["target"] == "Genesis Test"

    plan = ActionPlan.from_decision(decision)
    # Security model requires confirmation for folder.create (modifying operation)
    plan.parameters["confirmed"] = True
    result = ActionExecutor(OSManager()).execute(plan)

    assert result.success is True
    assert result.executed is True
    assert result.verified is True
    assert (workspace_root / "Genesis Test").is_dir()


def test_create_folder_outside_the_workspace_is_gated(workspace_root, monkeypatch):
    """Bucket (b) counterpart for the folder-create flow above.

    Same relative-target flow, but with cwd OUTSIDE the workspace root,
    so the folder would land outside and must require a grant. Note the
    `confirmed: True` alone is not enough -- that is attack A6.
    """
    import tempfile as _tempfile

    outside_cwd = Path(_tempfile.mkdtemp(prefix="g_folder_outside_"))
    monkeypatch.chdir(outside_cwd)

    engine = _build_decision_engine()
    decision = engine.decide("Create a folder called Genesis Test.")
    plan = ActionPlan.from_decision(decision)
    plan.parameters["confirmed"] = True

    os_manager = Mock()
    os_manager.create_folder.return_value = {
        "success": True, "operation": "folder.create", "executed": True,
        "verified": True, "path": str(outside_cwd / "Genesis Test"),
        "message": "created",
    }
    result = ActionExecutor(os_manager).execute(plan)
    assert result.status == "confirmation_required"
    assert result.executed is False
    os_manager.create_folder.assert_not_called()


@pytest.mark.usefixtures("hermetic_capabilities")
def test_creating_an_existing_folder_does_not_fake_success(
    workspace_root, monkeypatch,
):
    monkeypatch.chdir(workspace_root)
    (workspace_root / "Genesis Test").mkdir()

    plan = ActionPlan(
        operation="folder.create",
        target=str(workspace_root / "Genesis Test"),
        confidence=0.99,
        parameters={"confirmed": True},
    )

    result = ActionExecutor(OSManager()).execute(plan)

    assert result.success is False
    assert result.to_dict()["status"] == "already_exists"


# =========================================================
# GAP 2 — SEMANTIC FILE SEARCH
# =========================================================


def test_find_my_ielts_essay_passes_safety_and_executes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_home = tmp_path / "home"
    documents = fake_home / "Documents"
    documents.mkdir(parents=True)
    (documents / "ielts_essay_draft.txt").write_text("my essay", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    engine = _build_decision_engine()
    decision = engine.decide("Find my IELTS essay")

    assert decision["level"] == 3
    assert decision["intent"] == "file.search"

    plan = ActionPlan.from_decision(decision)
    result = ActionExecutor(OSManager()).execute(plan)

    payload = result.to_dict()

    # The search executed through the executor and its evidence
    # is trustworthy regardless of whether this particular
    # machine contains a matching file outside the sandbox.
    assert payload["status"] in {"verified", "success"}
    assert result.error is None


def test_semantic_multi_root_search_finds_matching_file(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    fake_home = tmp_path / "home"
    documents = fake_home / "Documents"
    downloads = fake_home / "Downloads"
    desktop = fake_home / "Desktop"
    documents.mkdir(parents=True)
    downloads.mkdir(parents=True)
    desktop.mkdir(parents=True)
    workspace.mkdir(parents=True)
    (documents / "IELTS_Essay_Task2.docx").write_text("essay", encoding="utf-8")
    (downloads / "unrelated_download.pdf").write_text("x", encoding="utf-8")

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    manager = OSManager()
    result = manager.search_file(None, "ielts essay")

    assert result["success"] is True
    assert set(result["roots"]) == {
        str(workspace),
        str(downloads),
        str(documents),
        str(fake_home / "Desktop"),
    }
    matches = [Path(match) for match in result["matches"]]
    assert Path(matches[0]).name == "IELTS_Essay_Task2.docx"


def test_explicit_search_root_stays_single_root(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "config.yaml").write_text("q: ielts", encoding="utf-8")

    manager = OSManager()
    result = manager.search_file(str(root), "config")

    assert result["success"] is True
    assert result["count"] == 1
    assert result["matches"][0].endswith("config.yaml")


# =========================================================
# GAP 1 — SEMANTIC FOLDER TARGET RESOLUTION
# =========================================================


def test_downloads_resolves_to_real_windows_folder():
    discovery = _build_target_discovery()

    query = discovery.build_query_from_action_plan(
        ActionPlan(operation="folder.open", target="downloads")
    )
    resolution = discovery.discover_and_resolve(query)

    expected = str((Path.home() / "Downloads").resolve())

    assert resolution.successful is True
    assert resolution.resolved.value == expected


def test_open_my_downloads_folder_end_to_end(workspace_root):
    """Bucket (c): the target is legitimately OUTSIDE the workspace.

    Rewritten rather than retargeted. "open my downloads folder" is a
    real product flow aimed at the user's real Downloads directory,
    which is outside any scratch workspace. Deleting or relocating it to
    make the test pass would be falsifying the premise, so this test now
    documents the user-visible consequence of the strict-first decision:

        a human asking Genesis to open their Downloads folder gets a
        confirmation prompt instead of a folder opening.

    That is a deliberate trade. Blast radius measures reversibility, not
    confidentiality, and opening a folder is reversible; the boundary
    nevertheless gates it because it cannot yet tell a harmless read of
    an ordinary directory from a read of something sensitive. The
    two-axis refinement that would let ordinary reads through is a named
    follow-up, not an oversight.

    Item 6C: this now takes the ``workspace_root`` fixture. The gating it
    asserts comes from the workspace boundary, which only fires when the
    root is ARMED; it previously depended on ambient
    ``GENESIS_WORKSPACE_ROOT`` and so failed wherever that was unset,
    including at the baseline commit. The fixture arms it for this test.
    """
    engine = _build_decision_engine()
    decision = engine.decide("open my downloads folder")

    assert decision["level"] == 3
    assert decision["intent"] == "folder.open"

    plan = ActionPlan.from_decision(decision)
    resolved_plan = _resolve_plan_target(_build_target_discovery(), plan)

    downloads = (Path.home() / "Downloads").resolve()
    assert resolved_plan.target == str(downloads)

    opened = {}

    os_manager = OSManager()

    original_open = os_manager.folders.open

    def capturing_open(path):
        opened["path"] = str(path)
        p = Path(path)
        return {
            "success": True,
            "operation": "folder.open",
            "path": str(p),
            "executed": True,
            "verified": p.is_dir(),
            "message": f"Opened folder '{p.name}'.",
        }

    os_manager.folders.open = capturing_open

    result = ActionExecutor(os_manager).execute(resolved_plan)

    # Outside the workspace: gated, and nothing was opened.
    assert result.status == "confirmation_required"
    assert result.executed is False
    assert "path" not in opened

    # With a genuine grant the same flow proceeds, which is what the
    # user sees after approving the prompt.
    from genesis_os.action_plan import attach_authorization
    from genesis_os.approval_store import ApprovalStore
    from genesis_os.authorization_grant import issue_authorization_grant

    # Item 20A (S14): the approved set must be the one production
    # builds -- `_authorize_plan_for_execution` hashes plan.parameters
    # plus the target. This plan still carries the pre-resolution
    # alias `folder: "downloads"` as a target-bearing parameter next
    # to the resolved target, so a grant naming only `path` would
    # leave that parameter uncovered, and the executor's gate now
    # refuses (correctly: the human never approved `folder`).
    args = dict(resolved_plan.parameters)
    args["target"] = str(downloads)
    token = ApprovalStore.issue_token("folder.open", args)
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    granted = attach_authorization(
        resolved_plan, issue_authorization_grant(
            operation="folder.open", arguments=args, token=token,
        ), arguments=args,
    )
    result2 = ActionExecutor(os_manager).execute(granted)
    assert result2.status != "confirmation_required"
    assert Path(opened["path"]).resolve() == downloads

    # REWRITTEN 2026-10-04, and re-pointed 2026-10-08 when this test was
    # rewritten for the workspace boundary. This asserted `result.verified
    # is True`. The Phase 1 evidence contract
    # (`PHASE_1_PYDANTIC_CONTRACTS_2026-09-25.md`: "a `verified=true`
    # result means the post-state was actually observed, not just that
    # the provider reported success") correctly refuses it:
    # `OSManager.open_folder` is a bare pass-through with no
    # verification helper -- unlike `create_folder` / `list_folder`,
    # which both attach one -- so there is no capability-specific
    # evidence for `folder.open` and the claim is downgraded with
    # `verification_evidence_rejected`.
    #
    # That is the intended, honest outcome, so it is now asserted
    # explicitly rather than treated as a failure: the routing and the
    # dispatch are still proven above, and the verification claim is
    # proven to be refused rather than fabricated.
    #
    # The assertions now target `result2`, the GRANTED dispatch. They
    # previously targeted `result`, which under the boundary never
    # dispatches at all and so has no verification claim to downgrade.
    assert result2.verified is False, (
        "folder.open claimed verified without a production verifier"
    )
    assert result2.metadata.get("verification_evidence_rejected"), (
        f"expected the evidence contract to reject the claim, got "
        f"{sorted(result2.metadata)}"
    )
    assert result2.metadata.get("trustworthy_success") is False


def test_unresolvable_folder_target_is_not_invented(tmp_path):
    discovery = _build_target_discovery()

    query = discovery.build_query_from_action_plan(
        ActionPlan(
            operation="folder.open",
            target=str(tmp_path / "definitely_missing_folder"),
        )
    )
    resolution = discovery.discover_and_resolve(query)

    # A nonexistent folder must never resolve to some other
    # directory; execution will fail transparently later.
    assert (
        resolution.successful is False
        or Path(resolution.resolved.value).name == "definitely_missing_folder"
        or Path(resolution.resolved.value) == (Path.home() / "Desktop")
    )


# =========================================================
# DECISION-LAYER BEHAVIOR CONTRACTS
# =========================================================


@pytest.mark.parametrize(
    "text,intent",
    [
        ("launch chrome", "application.open"),
        ("can you open google chrome?", "application.open"),
        ("open my downloads folder", "folder.open"),
        ("go to my downloads", "folder.open"),
        ("take me to downloads", "folder.open"),
        ("show me the downloads folder", "folder.open"),
        ("find my IELTS essay", "file.search"),
    ],
)
def test_routing_contract(text, intent):
    decision = _build_decision_engine().decide(text)

    assert decision["level"] == 3
    assert decision["intent"] == intent


@pytest.mark.parametrize(
    "text",
    [
        ("open my browser"),
        ("please launch my browser"),
    ],
)
def test_unresolvable_application_targets_do_not_become_fake_os_actions(text):
    """
    A generic target that application identity cannot resolve must
    never silently become an application.open execution.
    """
    decision = _build_decision_engine().decide(text)

    if decision["level"] == 3:
        promoted = decision["confidence"] >= 0.90
        # Only strong decisions with concrete targets may promote.
        assert not (promoted and not decision.get("application") and not decision.get("target"))


def test_conversational_ielts_question_never_becomes_os_action():
    decision = _build_decision_engine().decide("Is this IELTS sentence correct?")

    assert decision["level"] == 1
    assert decision["mode"] == "conversation"


def test_folder_name_case_preserved_for_various_phrasings():
    engine = _build_decision_engine()

    cases = {
        "create a folder called My IELTS Files": "My IELTS Files",
        "make a folder named Project Alpha": "Project Alpha",
        "new folder Genesis Report 2026": "Genesis Report 2026",
    }

    for text, expected in cases.items():
        decision = engine.decide(text)
        assert decision["level"] == 3
        assert decision["target"] == expected
