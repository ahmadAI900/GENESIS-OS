"""Level 3.8.2 objective-understanding contract tests."""

from genesis_os.objective_understanding import (
    ObjectiveUnderstanding,
)


class FakeDecisionEngine:

    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def decide(self, text):
        self.calls.append(text)
        return self.decisions[text]


def _decision(
    text,
    *,
    operation="application.open",
    target="Chrome",
    confidence=0.97,
):
    return {
        "level": 3,
        "mode": "os",
        "task": text,
        "intent": operation,
        "operation": operation,
        "target": target,
        "application": (
            target
            if operation.startswith(
                "application."
            )
            else None
        ),
        "parameters": {},
        "confidence": confidence,
        "reason": "test",
    }


def test_explicit_workflow_boundaries_are_understood():

    objective = (
        "open Chrome, search for music, "
        "then open Word"
    )

    decisions = {
        "open Chrome": _decision(
            "open Chrome"
        ),
        "search for music": _decision(
            "search for music",
            operation="browser.search",
            target="music",
        ),
        "open Word": _decision(
            "open Word",
            target="Word",
        ),
    }

    engine = FakeDecisionEngine(
        decisions
    )

    result = ObjectiveUnderstanding(
        engine
    ).understand(
        objective
    )

    assert [
        step.text
        for step in result.steps
    ] == [
        "open Chrome",
        "search for music",
        "open Word",
    ]

    assert result.fully_level3 is True
    assert result.executable is True
    assert result.requires_clarification is False


def test_and_is_only_a_boundary_when_followed_by_an_action():

    parser = ObjectiveUnderstanding(
        FakeDecisionEngine({})
    )

    assert parser.split_objective(
        "open the folder named research and development"
    ) == (
        "open the folder named research and development",
    )

    assert parser.split_objective(
        "open Chrome and search for music"
    ) == (
        "open Chrome",
        "search for music",
    )


def test_non_level3_step_is_never_executable():

    text = "explain this sentence"

    engine = FakeDecisionEngine({
        text: {
            "level": 1,
            "mode": "conversation",
            "task": text,
            "confidence": 0.99,
        }
    })

    result = ObjectiveUnderstanding(
        engine
    ).understand(text)

    assert result.requires_clarification is True
    assert result.executable is False
    assert result.steps[0].clarification_reason


def test_low_confidence_desktop_intent_requires_clarification():

    text = "open something"

    engine = FakeDecisionEngine({
        text: _decision(
            text,
            target=None,
            confidence=0.72,
        ),
    })

    result = ObjectiveUnderstanding(
        engine
    ).understand(text)

    assert result.requires_clarification is True
    assert result.executable is False


def test_empty_objective_is_safe():

    result = ObjectiveUnderstanding(
        FakeDecisionEngine({})
    ).understand("   ")

    assert result.requires_clarification is True
    assert result.steps == ()
    assert result.executable is False


def test_understanding_never_executes():

    text = "open Chrome"

    engine = FakeDecisionEngine({
        text: _decision(text)
    })

    result = ObjectiveUnderstanding(
        engine
    ).understand(text)

    assert engine.calls == [text]

    assert (
        result.steps[0].decision["operation"]
        == "application.open"
    )