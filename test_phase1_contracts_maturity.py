"""Phase 1 maturity: all 15 gate contracts exist as Pydantic models
with adapters, and 14 of them are enforced at real runtime
boundaries (Skill has no runtime yet — Phase 10 — so it is
covered by validator tests only, honestly).

Evidence(BaseModel) is instantiated by the evidence gate after
capability-specific semantic validation.

Each boundary test proves the choke rejects a malformed shape
while the neighboring tests prove live shapes still pass.
"""
import pytest

from genesis_os.contracts import (
    Agent,
    Capability,
    Checkpoint,
    ContractViolationError,
    Entity,
    Evidence,
    Execution,
    Objective,
    Observation,
    Policy,
    PolicyDecision,
    Recovery,
    Session,
    Skill,
    Task,
    Verification,
    Workflow,
    has_meaningful_result_evidence,
    require_result_evidence,
)


def _raises_violation(fn):
    with pytest.raises((ContractViolationError, ValueError)):
        fn()


class TestObjectiveContract:
    def test_empty_objective_without_clarification_rejected(self):
        _raises_violation(lambda: Objective(objective="", requires_clarification=False))

    def test_empty_objective_with_clarification_accepted(self):
        o = Objective(objective="", requires_clarification=True,
                      clarification_reason="empty")
        assert o.requires_clarification is True

    def test_gapped_sequences_rejected(self):
        from genesis_os.contracts import ObjectiveStep
        _raises_violation(lambda: Objective(
            objective="do things",
            steps=[ObjectiveStep(step_id="a", text="x", sequence=1),
                   ObjectiveStep(step_id="b", text="y", sequence=3)],
        ))

    def test_live_understand_result_passes(self):
        from agents.workflow_decision import WorkflowDecisionEngine
        from genesis_os.objective_understanding import ObjectiveUnderstanding
        understood = ObjectiveUnderstanding(WorkflowDecisionEngine()).understand("open notepad")
        checked = Objective.from_understanding_result(understood)
        assert checked.objective == "open notepad"
        assert len(checked.steps) >= 1


class TestEntityContract:
    def test_empty_entity_id_rejected(self):
        _raises_violation(lambda: Entity(
            entity_type="file", entity_id="  ", action="opened",
            timestamp="2026-01-01T00:00:00", source_level=3))

    def test_unknown_type_rejected(self):
        _raises_violation(lambda: Entity(
            entity_type="spaceship", entity_id="x", action="opened",
            timestamp="2026-01-01T00:00:00", source_level=3))

    def test_live_record_passes_boundary(self):
        from genesis_os.entity_history import EntityHistory, EntityType, EntityAction
        history = EntityHistory()
        entry = history.record(EntityType.FILE, "notes.txt", EntityAction.OPENED,
                               source_operation="file.open")
        checked = Entity.from_entry(entry)
        assert checked.entity_id == "notes.txt"
        assert checked.entity_type.value == "file"


class TestCapabilityContract:
    def test_empty_capability_id_rejected(self):
        _raises_violation(lambda: Capability(capability_id="", operation="application.open"))

    def test_live_resolve_passes_boundary(self):
        from genesis_os.capability_resolver import CapabilityResolver
        from genesis_os.capabilities import CapabilityRequirement
        resolved = CapabilityResolver().resolve(CapabilityRequirement(
            capability_id="application.open", category="application",
            operation="application.open", description="open",
            required_inputs=frozenset(), optional_inputs=frozenset(),
            required_permissions=frozenset()))
        assert resolved.status.value == "resolved"
        checked = Capability.from_descriptor(resolved.capability)
        assert checked.capability_id == "application.open"


class TestTaskContract:
    def test_bool_confidence_rejected(self):
        _raises_violation(lambda: Task(operation="file.open", confidence=True))

    def test_live_action_plan_passes_boundary(self):
        from genesis_os.action_plan import ActionPlan
        plan = ActionPlan(operation="file.open", target="notes.txt", confidence=0.9)
        checked = Task.from_action_plan(plan)
        assert checked.operation == "file.open"
        assert checked.confidence == 0.9


class TestWorkflowContract:
    def test_duplicate_step_ids_rejected(self):
        from genesis_os.contracts import WorkflowStepRef
        _raises_violation(lambda: Workflow(
            objective="x",
            steps=[WorkflowStepRef(step_id="s1"), WorkflowStepRef(step_id="s1")]))

    def test_empty_workflow_rejected(self):
        _raises_violation(lambda: Workflow(objective="  ", steps=[]))

    def test_live_workflow_plan_passes_boundary(self):
        from genesis_os.action_plan import ActionPlan
        from genesis_os.workflow_models import WorkflowPlan, WorkflowStep
        plan = WorkflowPlan(
            objective="open notepad",
            steps=[WorkflowStep(step_id="s1", plan=ActionPlan(
                operation="application.open", target="notepad"))],
            workflow_id="w1")
        checked = Workflow.from_workflow_plan(plan)
        assert checked.steps[0].operation == "application.open"


class TestExecutionContract:
    def test_read_only_verified_without_executed_accepted(self):
        # System semantics (trustworthy_success + normalization):
        # read-only operations legitimately verify observations
        # without effecting state. The Evidence gate — not an
        # executed flag — carries the anti-false-success weight.
        e = Execution(operation="application.inspect", status="verified",
                      success=True, executed=False, verified=True)
        assert e.verified is True

    def test_malformed_execution_rejected(self):
        _raises_violation(lambda: Execution(
            operation="", status="success", executed=True))
        _raises_violation(lambda: Execution(
            operation="file.open", status="", executed=True))

    def test_desired_state_exempt(self):
        e = Execution(operation="file.open", status="success",
                      success=True, executed=False, verified=True,
                      already_in_desired_state=True)
        assert e.verified is True

    def test_evidence_gate_rejects_bare_verified(self):
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="file.open", target="x", application=None,
            message="ok", executed=True, verified=True, verification={})
        _raises_violation(lambda: require_result_evidence(result))

    def test_evidence_gate_rejects_labels_without_observation(self):
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="file.open", target="x", application=None,
            message="ok", executed=True, verified=True,
            verification={
                "verification_type": "dispatch_only",
                "verification_reason": "provider says it ran",
            })
        _raises_violation(lambda: require_result_evidence(result))

    def test_evidence_gate_rejects_generic_post_state_marker(self):
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="browser.click", target="x", application=None,
            message="ok", executed=True, verified=True,
            verification={"post_state_matches": True})
        _raises_violation(lambda: require_result_evidence(result))

    def test_evidence_gate_rejects_destination_only_copy(self):
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="file.copy", target="x", application=None,
            message="ok", executed=True, verified=True,
            verification={"destination_exists": True})
        _raises_violation(lambda: require_result_evidence(result))

    def test_evidence_gate_rejects_negative_observation(self):
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="file.delete", target="x", application=None,
            message="ok", executed=True, verified=True,
            verification={"file_exists": True})
        _raises_violation(lambda: require_result_evidence(result))

    def test_evidence_gate_accepts_capability_observation(self):
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="application.open", target="x", application="x",
            message="ok", executed=True, verified=True,
            verification={"running": True})
        assert has_meaningful_result_evidence(result) is True
        require_result_evidence(result)

    def test_evidence_gate_accepts_observed_zero_with_provenance(self):
        """A genuine "I checked and found none" observation is real
        information and must keep verifying. clipboard.paste on an
        empty clipboard is the live example: it emits
        ``empty: True`` with ``verification_type``."""
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="clipboard.paste", target="x", application=None,
            message="empty", executed=False, verified=True,
            verification={
                "empty": True,
                "verification_type": "clipboard_query",
                "post_state_matches": True,
            })
        assert has_meaningful_result_evidence(result) is True

    @pytest.mark.parametrize(
        "verification",
        [
            # "the query ran and returned nothing" -- honest observations
            # that must keep verifying. Each of these was a real false
            # negative when the gate required provenance for falsy
            # values, which is why that change was reverted.
            {"battery_present": False},
            {"running": False, "pids": [], "count": 0},
            {"processes": [], "count": 0},
            {"applications": [], "count": 0},
            {"count": 0},
            {"content_length": 0},
            {"row_count": 0},
        ],
    )
    def test_evidence_gate_accepts_falsy_observation_values(
        self, verification
    ):
        """A falsy value can be a genuine observation.

        ``verified=True`` is already required at the top of the gate,
        so a provider asserting it alongside ``count: 0`` or
        ``battery_present: False`` is reporting what it saw. Excluding
        0/False was implemented and reverted: it broke four correct
        cases, including "this machine has no battery".
        """
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="file.open", target="x", application=None,
            message="ok", executed=True, verified=True,
            verification=verification)
        assert has_meaningful_result_evidence(result) is True

    @pytest.mark.parametrize(
        "verification",
        [
            {},
            {"verification_type": "dispatch_only"},
            {"verification_reason": "provider says it ran"},
            {"post_state_matches": True},
            # empty-string / empty-collection keys are excluded
            {"title": "", "items": [], "drives": {}},
        ],
    )
    def test_evidence_gate_rejects_evidence_free_verification(
        self, verification
    ):
        """A verified result with NO substantive observation is still
        rejected -- this is the defect the falsy-value work was
        guarding, and it remains covered."""
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="file.open", target="x", application=None,
            message="ok", executed=True, verified=True,
            verification=verification)
        assert has_meaningful_result_evidence(result) is False

    def test_evidence_gate_still_requires_verified_flag(self):
        """The falsy-value leniency does not extend to the verified
        flag itself: an unverified observation never verifies."""
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="file.open", target="x", application=None,
            message="ok", executed=True, verified=False,
            verification={"count": 0})
        assert has_meaningful_result_evidence(result) is False

    def test_empty_folder_inspect_verifies_without_relying_on_zero_count(self):
        """folder.inspect on a genuinely empty folder must verify via
        its operation-specific ``folder_exists`` rule. Verified with the
        count removed, to prove the zero is not load-bearing."""
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="folder.inspect", target="d", application=None,
            message="ok", executed=False, verified=True,
            verification={"folder_exists": True, "items": [], "count": 0})
        assert has_meaningful_result_evidence(result) is True
        without_count = ActionResult.success_result(
            operation="folder.inspect", target="d", application=None,
            message="ok", executed=False, verified=True,
            verification={"folder_exists": True, "items": []})
        assert has_meaningful_result_evidence(without_count) is True

    @pytest.mark.parametrize(
        "operation",
        ["application.close", "application.window_not_exists"],
    )
    @pytest.mark.parametrize(
        "verification",
        [
            {"running": True},
            {"process_found": True},
            {"running": True, "verification_type": "process_table_inspection"},
        ],
    )
    def test_evidence_gate_rejects_close_verified_by_still_running(
        self, operation, verification
    ):
        """A close certified by 'the application is still running' is a
        contradiction, not evidence.

        Regression: the generic rule
        ``operation.startswith("application.") and isinstance(running, bool)``
        was evaluated first, so a close carrying ``running: True``
        returned True before the close-specific rule could demand
        ``running is False``.
        """
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation=operation, target="x", application="x",
            message="closed", executed=True, verified=True,
            verification=verification)
        assert has_meaningful_result_evidence(result) is False

    @pytest.mark.parametrize(
        "verification",
        [{"running": False}, {"process_found": False}],
    )
    def test_evidence_gate_accepts_close_verified_by_absent_process(
        self, verification
    ):
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="application.close", target="x", application="x",
            message="closed", executed=True, verified=True,
            verification=verification)
        assert has_meaningful_result_evidence(result) is True

    @pytest.mark.parametrize(
        "operation", ["application.open", "application.inspect"]
    )
    def test_non_close_application_ops_keep_bool_running_evidence(
        self, operation
    ):
        """The generic rule must still work for every other
        application.* operation — the fix excludes only the close
        family."""
        from genesis_os.action_result import ActionResult
        for running in (True, False):
            result = ActionResult.success_result(
                operation=operation, target="x", application="x",
                message="ok", executed=True, verified=True,
                verification={"running": running})
            assert has_meaningful_result_evidence(result) is True

    def test_live_executor_result_passes(self):
        from unittest.mock import MagicMock, patch
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan
        os_mgr = MagicMock()
        executor = ActionExecutor(os_mgr)
        plan = ActionPlan(operation="application.open", target="notepad", confidence=0.95)
        provider_result = {
            "success": True, "operation": "application.open",
            "executed": True, "verified": True,
            "verification": {
                "verification_type": "process_table_inspection",
                "running": True,
            },
            "message": "opened",
        }
        with patch.object(executor, "_dispatch", return_value=provider_result):
            result = executor.execute(plan)
        assert result.success is True
        checked = Execution.from_action_result(result)
        assert checked.operation == "application.open"


class TestObservationContract:
    def test_negative_window_count_rejected(self):
        _raises_violation(lambda: Observation(timestamp=1.0, window_count=-1))

    def test_live_snapshot_passes_boundary(self):
        from genesis_os.gui_observer import GUIObserver
        snapshot = GUIObserver().take_snapshot()
        checked = Observation.from_snapshot(snapshot)
        assert checked.window_count >= 0


class TestVerificationContract:
    def test_reasonless_verdict_rejected(self):
        _raises_violation(lambda: Verification(verified=True, reason=""))
        _raises_violation(lambda: Verification.from_verdict("gui.click", {"verified": True}))

    def test_live_verifier_passes_boundary(self):
        from genesis_os.gui_observer import GUIVerifier
        result = GUIVerifier().verify_window_not_exists("definitely-no-such-window-xyz-123")
        checked = Verification.from_gui_result(result, operation="gui.inspect_window")
        assert checked.reason != ""


class TestRecoveryContract:
    def test_recovered_without_plan_rejected(self):
        _raises_violation(lambda: Recovery(
            original_step_id="s1", recovered=True, final_error=None,
            has_final_plan=False))

    def test_recovered_with_error_rejected(self):
        _raises_violation(lambda: Recovery(
            original_step_id="s1", recovered=True, final_error="x",
            has_final_plan=True))

    def test_failed_recovery_accepted(self):
        r = Recovery(original_step_id="s1", recovered=False, final_error="boom")
        assert r.recovered is False


class TestSessionContract:
    def test_task_without_id_rejected(self):
        _raises_violation(lambda: Session(current_task={"objective": "x"}))

    def test_live_serialized_session_passes(self, tmp_path):
        from genesis_os.session_persistence import SessionPersistence
        from genesis_os.session_state import SessionState
        state = SessionState()
        persistence = SessionPersistence(storage_dir=tmp_path)
        assert persistence.save(state) is True
        checked = Session.from_serialized(persistence._serialize_session(state))
        assert checked.task_history_count >= 0


class TestAgentContractWired:
    def test_nameless_agent_rejected(self):
        _raises_violation(lambda: Agent.from_runtime(type("A", (), {"name": "  "})()))

    def test_live_agents_pass_registry(self):
        from agents.agent_registry import AgentRegistry
        from agents.research_agent import ResearchAgent
        registry = AgentRegistry()
        agent = ResearchAgent()
        registry.register(agent)
        checked = Agent.from_runtime(agent)
        assert checked.agent_id == agent.name
        assert "research" in checked.raw_capabilities


class TestPolicyContractWired:
    def test_unknown_status_rejected(self):
        _raises_violation(lambda: PolicyDecision.from_safety_status("maybe"))

    def test_all_live_statuses_map(self):
        assert PolicyDecision.from_safety_status("supported") == PolicyDecision.ALLOW
        assert PolicyDecision.from_safety_status("denied") == PolicyDecision.DENY
        assert PolicyDecision.from_safety_status("unknown") == PolicyDecision.CONFIRM
        assert PolicyDecision.from_safety_status("invalid") == PolicyDecision.DENY

    def test_live_check_produces_mapped_decision(self):
        from genesis_os.execution_safety import ExecutionSafety
        decision = ExecutionSafety.check("application.open")
        assert PolicyDecision.from_safety_status(decision.status) is not None


class TestEvidenceSkillCheckpointPolicy:
    def test_evidence_verdict_adapter(self):
        v = Verification.from_verdict("spreadsheet.sort", {
            "verified": True, "reason": "exists", "output": "x"})
        assert v.operation == "spreadsheet.sort"
        e = Evidence(
            evidence_id="s1:spreadsheet.sort",
            evidence_type="file_exists",
            operation="spreadsheet.sort",
            passed=True,
            reason="exists",
            metadata={"output_path": "x"})
        assert e.passed is True

    def test_evidence_model_rejects_passed_empty_metadata(self):
        _raises_violation(lambda: Evidence(
            evidence_id="empty:verification",
            evidence_type="file_exists",
            operation="file.create",
            passed=True,
            reason="missing payload",
        ))

    def test_evidence_adapter_rejects_verified_control_flag(self):
        from genesis_os.action_result import ActionResult
        result = ActionResult.success_result(
            operation="application.open", target="notepad", application="notepad",
            message="provider claim only", executed=True, verified=True,
            verification={"verified": True},
        )
        _raises_violation(lambda: Evidence.from_result(result))

    def test_skill_rejects_empty_id(self):
        _raises_violation(lambda: Skill(skill_id="  ", name="n"))

    def test_skill_validates_full_definition(self):
        s = Skill(skill_id="file.open.latest", name="Open latest file",
                  required_capabilities=["file.open"],
                  verification_steps=["file exists"],
                  risk_level="low")
        assert s.skill_id == "file.open.latest"

    def test_skill_contract_standalone_validation_rejects_malformed_definition(self):
        skill = Skill(
            skill_id="website.generate",
            name="Generate website",
            required_capabilities=["file.create"],
            verification_steps=["file content matches"],
            risk_level="low",
        )
        assert skill.required_capabilities == ["file.create"]
        _raises_violation(lambda: Skill(skill_id="", name="Generate website"))

    def test_checkpoint_rejects_empty_ids(self):
        from genesis_os.contracts import Checkpoint
        _raises_violation(lambda: Checkpoint(
            checkpoint_id="c", workflow_id="", step_id="s"))

    def test_policy_evaluate(self):
        p = Policy(policy_id="p", name="n")
        assert p.evaluate("anything") == PolicyDecision.ALLOW


class TestPhase1RuntimeBoundaries:
    def test_executor_instantiates_evidence_contract_at_post_execution_boundary(self):
        from unittest.mock import Mock
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "executed": True,
            "verified": True,
            "running": True,
            "message": "opened",
        }
        result = ActionExecutor(os_manager).execute(
            ActionPlan(operation="application.open", target="notepad")
        )

        evidence = result.metadata["evidence_contract"]
        assert evidence["passed"] is True
        assert evidence["metadata"]["running"] is True
        assert "verified" not in evidence["metadata"]

    def test_executor_rejects_malformed_evidence_after_dispatch(self):
        from unittest.mock import Mock
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_manager = Mock()
        os_manager.open_application.return_value = {
            "success": True,
            "operation": "application.open",
            "executed": True,
            "verified": True,
            "verification": {"verified": True},
            "message": "provider claim only",
        }
        result = ActionExecutor(os_manager).execute(
            ActionPlan(operation="application.open", target="notepad")
        )

        assert result.verified is False
        assert result.status == "verification_unavailable"
        assert result.trustworthy_success is False
        os_manager.open_application.assert_called_once_with("notepad")

    def test_task_adapter_rejects_missing_required_field_before_os_dispatch(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from genesis_os.action_executor import ActionExecutor
        from genesis_os.action_plan import ActionPlan

        os_manager = Mock()
        executor = ActionExecutor(os_manager)
        malformed_native_plan = SimpleNamespace(
            target="notepad",
            application=None,
            parameters={},
            confidence=1.0,
        )
        malformed_executor_plan = ActionPlan.model_construct(
            operation="",
            target="notepad",
            application=None,
            parameters={},
            confidence=1.0,
        )

        with pytest.raises(ContractViolationError):
            from genesis_os.contracts import Task
            Task.from_action_plan(malformed_native_plan)

        result = executor.execute(malformed_executor_plan)
        assert result.status == "invalid_plan"
        assert result.executed is False
        assert os_manager.open_application.call_count == 0
