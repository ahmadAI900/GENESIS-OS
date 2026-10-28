"""Phase 0 mixed-objective bridge regression.

RECONSTRUCTED 2026-10-04. This file was destroyed by a bulk-edit bug and
restored from the contract it was written to prove, not from a backup.
Its cited source is
``backend/PHASE_1_PYDANTIC_CONTRACTS_2026-09-25.md`` section 6,
"Phase 0 Bridge Consistency Check". The contract language, verbatim:

    "The Phase 0 mixed-objective bridge remains consistent with the
    Phase 1 contract boundaries:

    1. `backend/genesis.py:3105-3108` routes a mixed objective through
       `GenesisRuntime.execute_mixed_audited(..., self.unified_executor)`.
    2. `backend/genesis_os/unified_executor.py:674-696` derives the
       Coding Agent `file.create` target, and `:985-990` dispatches
       refined steps through the workflow engine.
    3. `backend/genesis_os/workflow_engine.py:91-96` validates the
       Workflow contract before planner validation.
    4. `backend/genesis_os/action_executor.py:713-725` validates the
       Task contract before dispatch.
    5. `backend/genesis_os/action_executor.py:821-835` validates
       Execution and Evidence after dispatch.

    No mixed path bypasses the workflow or executor contract boundary.
    The existing bridge regression passes"

and, on what the probe is and is not allowed to claim:

    "The probe uses a deterministic agent and OS-manager test double;
    it is bridge regression evidence, not a new claim of real OS
    execution."

Line numbers in the citation have drifted since it was written; the
symbols it names are asserted instead, and each is checked against
production in the assertions below.

Every test in this file is offline with respect to the OS: the agent is
deterministic and the OS manager is a test double, exactly as the
contract requires. The module-level ``live`` mark is the coarse bucket
T24 exists to override: the tier snapshot classifies this test as
``runtime``, and ``hermetic_capabilities`` stubs pyautogui and the
browser probes so the real ``GenesisOS`` can be built in the fast gate.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.base_agent import BaseAgent
from genesis import GenesisOS
from genesis_os import contracts
from runtime.genesis_runtime import GenesisRuntime

pytestmark = [
    pytest.mark.live,
    pytest.mark.usefixtures("hermetic_capabilities"),
]

OBJECTIVE = "open notepad and write python code for a calculator"
AGENT_CODE = "def calculator():\n    return 42\n"


class DeterministicCodingAgent(BaseAgent):
    """The contract's 'deterministic agent': fixed output, no model."""

    def __init__(self) -> None:
        super().__init__(
            "Coding Agent", "Writes code", ["code", "debug"],
        )

    def run(self, task, context=None):
        return {"code": AGENT_CODE, "language": "python"}

    def can_handle(self, task):
        return "code" in str(task).lower()


def _os_manager_double():
    """The contract's 'OS-manager test double'.

    Records what the bridge asks the OS to do and answers with the dict
    shape a real OSManager returns, so the contract boundaries after
    dispatch are genuinely exercised. Deliberately not a real
    OSManager: the contract states this probe is bridge evidence and
    makes no claim about real OS execution.
    """
    os_manager = Mock()
    os_manager.dispatched = []
    os_manager.events = []

    def answered(*args, **record):
        return {
            "success": True,
            "executed": True,
            "verified": True,
            "message": "recorded by test double",
        }

    def counted(*args, **record):
        os_manager.dispatched.append(args[0] if args else None)
        os_manager.events.append("dispatch")
        return answered(*args, **record)

    os_manager.create_file = Mock(side_effect=counted)
    os_manager.open_application = Mock(side_effect=counted)
    os_manager.open_file = Mock(side_effect=counted)
    os_manager.inspect_application = Mock(side_effect=counted)
    return os_manager


def _contract_spies(monkeypatch, events):
    """Record every contract boundary (contract items 3-5) in call order.

    An ordered event log rather than counters, because the contract's
    claim is about ORDER: the Workflow contract runs before planner
    validation, the Task contract before dispatch, and the Execution
    and Evidence contracts after it. Counters cannot show that.
    """
    boundaries = {
        "workflow": (
            contracts.Workflow, "from_workflow_plan",
        ),
        "task": (contracts.Task, "from_action_plan"),
        "execution": (contracts.Execution, "from_action_result"),
        "evidence": (contracts.Evidence, "from_result"),
    }
    for label, (owner, attribute) in boundaries.items():
        original = getattr(owner, attribute)

        def counted(*args, _original=original, _label=label, **kwargs):
            events.append(_label)
            return _original(*args, **kwargs)

        monkeypatch.setattr(owner, attribute, counted, raising=True)


def test_production_mixed_objective_bridges_coding_output_to_os_action(
    monkeypatch, workspace_root, request
):
    """Contract items (1)-(5): the bridge exists and bypasses nothing."""
    # Run inside the armed workspace, not the package directory. The
    # bridge derives a relative `file.create` target; S16 makes the gate
    # resolve that target to an absolute path, so a tmp_path outside the
    # workspace would be a Tier 1 write and correctly demand a grant.
    # The bridge contract needs the ordinary in-workspace path.
    monkeypatch.chdir(workspace_root)
    genesis = GenesisOS()
    request.addfinalizer(genesis.shutdown)

    # Deterministic agent replaces the real Coding Agent, so the probe
    # never reaches a model and its output is fixed.
    genesis.unified_executor.agent_registry.register(
        DeterministicCodingAgent(),
    )

    # OS-manager test double at every point the workflow engine holds
    # one, so nothing touches the real machine.
    double = _os_manager_double()
    workflow_engine = genesis.unified_executor.workflow_engine
    monkeypatch.setattr(workflow_engine.executor, "os_manager", double)
    monkeypatch.setattr(workflow_engine, "_os_manager", double)

    # Ordered log of every boundary crossing on the mixed path.
    events = []
    double.dispatched = []
    double.events = events
    _contract_spies(monkeypatch, events)

    real_planner_validate = workflow_engine.planner.validate

    def recording_planner_validate(workflow):
        events.append("planner")
        return real_planner_validate(workflow)

    monkeypatch.setattr(
        workflow_engine.planner, "validate", recording_planner_validate,
    )

    result = genesis.genesis_runtime.execute_mixed_audited(
        OBJECTIVE, genesis.unified_executor,
    )

    os_results = list(getattr(result, "os_results", []) or [])
    operations = [entry.get("operation") for entry in os_results]

    # --- (2) Coding Agent output became a real OS action -------------
    # `refine_os_steps_from_agent_results` derives a `file.create`
    # step from the agent's structured output when the agent named no
    # file path. The deterministic agent names none, so the derived
    # target is the planner's default for a python payload.
    assert "file.create" in operations, (
        f"coding output was not bridged to an OS action: {operations}"
    )
    assert double.create_file.called, (
        f"file.create reached os_results but not the OS manager: {os_results}"
    )
    # `ActionExecutor` passes the plan's `content` parameter to
    # `OSManager.create_file` positionally.
    args, kwargs = double.create_file.call_args
    assert AGENT_CODE in "".join(str(a) for a in args[1:2]), (
        "the bridged file.create did not carry the agent's code"
    )
    # Item 3B-3b: confirmed is no longer forwarded to OS managers;
    # authorization is decided once, above, by the gate + grant.
    assert "confirmed" not in kwargs, (
        f"confirmed must not be injected into file.create kwargs: {kwargs}"
    )

    # --- (3) Workflow contract validated BEFORE planner validation --
    # The contract's claim is an ORDER, not merely that both ran, so
    # the event log is what is asserted.
    assert events.count("workflow") >= 1, (
        "the Workflow contract was never validated on the mixed path"
    )
    assert events.index("workflow") < events.index("planner"), (
        f"planner validation ran before the Workflow contract: {events}"
    )

    # --- (4) Task contract validated before dispatch -----------------
    # Every OS operation that reached the OS layer was validated as a
    # Task first. Counting dispatches rather than `os_results` entries
    # keeps the assertion honest: `os_results` omits steps that failed
    # earlier in the pipeline.
    assert double.dispatched, "no OS operation was dispatched at all"
    assert events.count("task") == len(double.dispatched), (
        f"Task contract ran {events.count('task')}x for "
        f"{len(double.dispatched)} dispatch(es): a step reached "
        f"dispatch unvalidated"
    )
    assert events.index("task") < events.index("dispatch"), (
        f"an OS operation was dispatched before its Task contract: "
        f"{events}"
    )

    # --- (5) Execution and Evidence validated after dispatch ---------
    assert events.count("execution") == len(double.dispatched)
    assert events.count("evidence") == len(double.dispatched)
    assert events.index("dispatch") < events.index("execution"), (
        f"the Execution contract ran before dispatch: {events}"
    )

    # --- (1) genesis.py routes mixed objectives through the audited
    #         runtime with its own unified_executor -------------------
    assert isinstance(genesis.genesis_runtime, GenesisRuntime)
    routed = []
    real_routed = genesis.genesis_runtime.execute_mixed_audited

    def recording_route(goal, executor):
        routed.append((goal, executor))
        return real_routed(goal, executor)

    monkeypatch.setattr(
        genesis.genesis_runtime,
        "execute_mixed_audited",
        recording_route,
    )
    genesis._handle_level3_request(
        OBJECTIVE, {"level": 3, "mode": "os"},
    )
    assert routed, (
        "genesis.py did not route the mixed objective through "
        "execute_mixed_audited"
    )
    assert routed[-1][1] is genesis.unified_executor