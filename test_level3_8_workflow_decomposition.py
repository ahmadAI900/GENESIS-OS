"""Genesis OS — Level 3.8.3 decomposition tests."""

from genesis_os.objective_understanding import (
    ObjectiveStepIntent,
    ObjectiveUnderstandingResult,
)
from genesis_os.workflow_decomposer import (
    WorkflowDecomposer,
    DecompositionResult,
)
from genesis_os.action_plan import ActionPlan


def make_intent(
    *,
    step_id,
    sequence,
    text,
    operation,
    target,
    application=None,
    confidence=0.98,
):
    decision = {
        "level": 3,
        "mode": "os",
        "operation": operation,
        "target": target,
        "application": application,
        "task": text,
        "confidence": confidence,
        "parameters": {},
        "reason": (
            "Resolved by WorkflowDecisionEngine"
        ),
        "source": "WorkflowDecisionEngine",
    }

    return ObjectiveStepIntent(
        step_id=step_id,
        text=text,
        sequence=sequence,
        decision=decision,
        confidence=confidence,
        level=3,
        mode="os",
        operation=operation,
        target=target,
        application=application,
    )


def make_understanding(*intents):

    return ObjectiveUnderstandingResult(
        objective=(
            "Open Chrome and search for music, "
            "then open Word."
        ),
        steps=tuple(intents),
        confidence=min(
            intent.confidence
            for intent in intents
        ),
        requires_clarification=False,
        metadata={
            "version": "3.8.2"
        },
    )


def test_single_intent_becomes_single_step():

    understanding = make_understanding(
        make_intent(
            step_id="objective-step-1",
            sequence=1,
            text="open Chrome",
            operation="application.open",
            target="Chrome",
            application="Chrome",
        )
    )

    result = (
        WorkflowDecomposer().decompose(
            understanding
        )
    )

    assert isinstance(
        result,
        DecompositionResult,
    )

    assert result.decomposed is True
    assert result.executable is True
    assert result.workflow is not None

    assert len(
        result.workflow.steps
    ) == 1

    step = result.workflow.steps[0]

    assert step.step_id == "step-1"

    assert step.depends_on == ()

    assert (
        step.plan.operation
        == "application.open"
    )

    assert (
        step.plan.target
        == "Chrome"
    )


def test_multiple_intents_preserve_order():

    understanding = make_understanding(

        make_intent(
            step_id="objective-step-1",
            sequence=1,
            text="open Chrome",
            operation="application.open",
            target="Chrome",
            application="Chrome",
        ),

        make_intent(
            step_id="objective-step-2",
            sequence=2,
            text="search for music",
            operation="browser.search",
            target="music",
        ),

        make_intent(
            step_id="objective-step-3",
            sequence=3,
            text="open Word",
            operation="application.open",
            target="Word",
            application="Word",
        ),
    )

    result = (
        WorkflowDecomposer().decompose(
            understanding
        )
    )

    assert result.executable is True

    workflow = result.workflow

    assert workflow is not None

    assert len(
        workflow.steps
    ) == 3

    assert [
        step.plan.operation
        for step in workflow.steps
    ] == [
        "application.open",
        "browser.search",
        "application.open",
    ]


def test_steps_have_sequential_dependencies():

    understanding = make_understanding(

        make_intent(
            step_id="objective-step-1",
            sequence=1,
            text="open Chrome",
            operation="application.open",
            target="Chrome",
            application="Chrome",
        ),

        make_intent(
            step_id="objective-step-2",
            sequence=2,
            text="search for music",
            operation="browser.search",
            target="music",
        ),

        make_intent(
            step_id="objective-step-3",
            sequence=3,
            text="open Word",
            operation="application.open",
            target="Word",
            application="Word",
        ),
    )

    result = (
        WorkflowDecomposer().decompose(
            understanding
        )
    )

    workflow = result.workflow

    assert workflow is not None

    assert workflow.steps[0].depends_on == ()

    assert workflow.steps[1].depends_on == (
        "step-1",
    )

    assert workflow.steps[2].depends_on == (
        "step-2",
    )


def test_decomposition_never_executes():

    understanding = make_understanding(
        make_intent(
            step_id="objective-step-1",
            sequence=1,
            text="open Chrome",
            operation="application.open",
            target="Chrome",
            application="Chrome",
        )
    )

    result = (
        WorkflowDecomposer().decompose(
            understanding
        )
    )

    assert result.workflow is not None

    assert isinstance(
        result.workflow.steps[0].plan,
        ActionPlan,
    )


def test_clarification_blocks_decomposition():

    intent = ObjectiveStepIntent(
        step_id="objective-step-1",
        text="open something",
        sequence=1,
        decision={
            "level": 3,
            "mode": "os",
            "operation": "application.open",
            "target": None,
            "confidence": 0.42,
        },
        confidence=0.42,
        level=3,
        mode="os",
        operation="application.open",
        target=None,
        requires_clarification=True,
        clarification_reason=(
            "The application target is ambiguous."
        ),
    )

    understanding = (
        ObjectiveUnderstandingResult(
            objective="open something",
            steps=(intent,),
            confidence=0.42,
            requires_clarification=True,
            clarification_reason=(
                "The application target is ambiguous."
            ),
        )
    )

    result = (
        WorkflowDecomposer().decompose(
            understanding
        )
    )

    assert result.executable is False
    assert result.workflow is None
    assert (
        result.requires_clarification
        is True
    )


def test_unknown_capability_cannot_become_executable():

    intent = make_intent(
        step_id="objective-step-1",
        sequence=1,
        text="perform unknown operation",
        operation="genesis.unknown.operation",
        target="test",
    )

    understanding = (
        make_understanding(intent)
    )

    result = (
        WorkflowDecomposer().decompose(
            understanding
        )
    )

    assert result.executable is False
    assert result.workflow is None
    assert result.requires_clarification is True


def test_workflow_id_is_preserved():

    understanding = make_understanding(
        make_intent(
            step_id="objective-step-1",
            sequence=1,
            text="open Chrome",
            operation="application.open",
            target="Chrome",
            application="Chrome",
        )
    )

    result = (
        WorkflowDecomposer().decompose(
            understanding,
            workflow_id="workflow-test-001",
        )
    )

    assert result.workflow is not None

    assert (
        result.workflow.workflow_id
        == "workflow-test-001"
    )


def test_intent_metadata_is_preserved():

    understanding = make_understanding(
        make_intent(
            step_id="objective-step-1",
            sequence=1,
            text="open Chrome",
            operation="application.open",
            target="Chrome",
            application="Chrome",
        )
    )

    result = (
        WorkflowDecomposer().decompose(
            understanding
        )
    )

    workflow = result.workflow

    assert workflow is not None

    step = workflow.steps[0]

    assert (
        step.metadata["intent_step_id"]
        == "objective-step-1"
    )

    assert (
        step.metadata["intent_text"]
        == "open Chrome"
    )

    assert (
        step.metadata["operation"]
        == "application.open"
    )
    def test_objective_to_workflow_preserves_architecture():

        understanding = make_understanding(

            make_intent(
                step_id="objective-step-1",
                sequence=1,
                text="open Chrome",
                operation="application.open",
                target="Chrome",
                application="Chrome",
            ),

            make_intent(
                step_id="objective-step-2",
                sequence=2,
                text="search for music",
                operation="browser.search",
                target="music",
            ),
        )

        result = (
            WorkflowDecomposer().decompose(
                understanding,
                workflow_id="objective-test",
            )
        )

        assert result.executable is True

        workflow = result.workflow

        assert workflow is not None

    # Objective
        assert workflow.objective == (
            understanding.objective
        )

    # Intent → ActionPlan
        assert (
            workflow.steps[0].plan.operation
            == "application.open"
        )

        assert (
            workflow.steps[1].plan.operation
            == "browser.search"
        )

    # Step dependency
        assert workflow.steps[1].depends_on == (
            "step-1",
        )

    # No executable callback / arbitrary command
        for step in workflow.steps:
            assert isinstance(
                step.plan,
                ActionPlan,
            )