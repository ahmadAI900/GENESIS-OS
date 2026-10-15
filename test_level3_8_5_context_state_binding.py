from genesis_os.workflow_context import (
    WorkflowContext,
    ContextValue,
)

from genesis_os.workflow_binding import (
    WorkflowDataBinder,
    InvalidBindingError,
    UnresolvedBindingError,
)

from genesis_os.workflow_state import (
    StepRuntimeStatus,
    WorkflowRuntimeStatus,
    WorkflowStateStore,
)


def test_context_stores_and_retrieves_value():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    context.set(
        "current.file",
        r"C:\results.xlsx",
        source="file_discovery",
    )

    assert (
        context.get("current.file")
        == r"C:\results.xlsx"
    )


def test_context_preserves_provenance():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    context.set(
        "current.file",
        r"C:\results.xlsx",
        source="file_discovery",
        step_id="step-1",
        confidence=0.97,
        evidence={
            "name": "results.xlsx"
        },
    )

    entry = context.get_entry(
        "current.file"
    )

    assert entry is not None

    assert (
        entry.source
        == "file_discovery"
    )

    assert (
        entry.step_id
        == "step-1"
    )

    assert (
        entry.confidence
        == 0.97
    )


def test_step_output_is_addressable():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    context.set_step_output(
        "step-1",
        "file",
        r"C:\results.xlsx",
        source="action_result",
    )

    assert (
        context.get_step_output(
            "step-1",
            "file",
        )
        == r"C:\results.xlsx"
    )


def test_binding_resolves_step_output():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    context.set_step_output(
        "step-1",
        "file",
        r"C:\results.xlsx",
        source="action_result",
    )

    binder = WorkflowDataBinder(
        context
    )

    result = binder.resolve(
        "${steps.step-1.outputs.file}"
    )

    assert (
        result
        == r"C:\results.xlsx"
    )


def test_binding_preserves_native_type():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    context.set_step_output(
        "step-1",
        "count",
        42,
        source="action_result",
    )

    binder = WorkflowDataBinder(
        context
    )

    result = binder.resolve(
        "${steps.step-1.outputs.count}"
    )

    assert result == 42
    assert isinstance(
        result,
        int,
    )


def test_binding_can_embed_scalar():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    context.set_step_output(
        "step-1",
        "filename",
        "results.xlsx",
        source="action_result",
    )

    binder = WorkflowDataBinder(
        context
    )

    result = binder.resolve(
        "Open ${steps.step-1.outputs.filename}"
    )

    assert (
        result
        == "Open results.xlsx"
    )


def test_missing_binding_fails_safely():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    binder = WorkflowDataBinder(
        context
    )

    try:
        binder.resolve(
            "${steps.step-99.outputs.file}"
        )
    except UnresolvedBindingError:
        return

    assert False, (
        "Missing workflow binding must "
        "raise UnresolvedBindingError."
    )


def test_unsupported_expression_is_rejected():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    binder = WorkflowDataBinder(
        context
    )

    try:
        binder.resolve(
            "${python.os.system}"
        )
    except InvalidBindingError:
        return

    assert False, (
        "Unsupported binding namespace "
        "must be rejected."
    )


def test_complex_object_cannot_be_embedded_in_string():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    context.set_step_output(
        "step-1",
        "data",
        {
            "name": "student",
        },
        source="action_result",
    )

    binder = WorkflowDataBinder(
        context
    )

    try:
        binder.resolve(
            "Student: "
            "${steps.step-1.outputs.data}"
        )
    except InvalidBindingError:
        return

    assert False, (
        "Complex objects must not be silently "
        "stringified into bindings."
    )


def test_context_versions_increment():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    initial = context.version

    context.set(
        "a",
        1,
        source="test",
    )

    context.set(
        "b",
        2,
        source="test",
    )

    assert context.version > initial


def test_context_snapshot_can_be_retrieved():

    context = WorkflowContext(
        workflow_id="wf-001"
    )

    context.set(
        "file",
        "one.xlsx",
        source="test",
    )

    version = context.version

    context.set(
        "file",
        "two.xlsx",
        source="test",
    )

    snapshot = context.snapshot_at(
        version
    )

    assert (
        snapshot.get("file")
        == "one.xlsx"
    )


def test_state_registers_step():

    state = WorkflowStateStore(
        "wf-001"
    )

    state.register_step(
        "step-1"
    )

    step = state.get_step(
        "step-1"
    )

    assert (
        step.status
        == StepRuntimeStatus.PENDING
    )


def test_state_tracks_running_step():

    state = WorkflowStateStore(
        "wf-001"
    )

    state.register_step(
        "step-1"
    )

    state.transition_step(
        "step-1",
        StepRuntimeStatus.RUNNING,
    )

    step = state.get_step(
        "step-1"
    )

    assert (
        step.status
        == StepRuntimeStatus.RUNNING
    )

    assert step.attempts == 1

    assert (
        state.active_step_id
        == "step-1"
    )


def test_state_tracks_verified_step():

    state = WorkflowStateStore(
        "wf-001"
    )

    state.register_step(
        "step-1"
    )

    state.transition_step(
        "step-1",
        StepRuntimeStatus.RUNNING,
    )

    state.transition_step(
        "step-1",
        StepRuntimeStatus.VERIFIED,
        verification={
            "verified": True
        },
    )

    step = state.get_step(
        "step-1"
    )

    assert (
        step.status
        == StepRuntimeStatus.VERIFIED
    )

    assert (
        step.verification["verified"]
        is True
    )

    assert (
        state.active_step_id
        is None
    )


def test_state_preserves_history():

    state = WorkflowStateStore(
        "wf-001"
    )

    state.register_step(
        "step-1"
    )

    state.transition_step(
        "step-1",
        StepRuntimeStatus.RUNNING,
    )

    state.transition_step(
        "step-1",
        StepRuntimeStatus.SUCCEEDED,
    )

    history = state.history()

    assert len(history) >= 3

    assert (
        history[-1].steps["step-1"].status
        == StepRuntimeStatus.SUCCEEDED
    )
def test_step_output_flows_into_next_step():

    context = WorkflowContext(
        workflow_id="wf-data-flow"
    )

    state = WorkflowStateStore(
        "wf-data-flow"
    )

    state.register_step(
        "step-1"
    )

    state.register_step(
        "step-2"
    )

    # Step 1 discovered a real file.
    context.set_step_output(
        "step-1",
        "file",
        r"C:\Downloads\student_results.xlsx",
        source="file_discovery",
        confidence=0.96,
    )

    state.transition_step(
        "step-1",
        StepRuntimeStatus.SUCCEEDED,
    )

    binder = WorkflowDataBinder(
        context
    )

    # Step 2's conceptual input references
    # the result of Step 1.
    value = binder.resolve(
        "${steps.step-1.outputs.file}"
    )

    assert (
        value
        == r"C:\Downloads\student_results.xlsx"
    )