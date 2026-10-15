from core.result import GenesisResult
from core.reliability import ReliabilityGuard


def test_success_result():

    result = GenesisResult.ok(
        data={"value": 42},
        source="test",
    )

    assert result.success is True
    assert result.data["value"] == 42
    assert result.error is None
    assert result.source == "test"


def test_failure_result():

    result = GenesisResult.fail(
        error="Something failed",
        code="TEST_ERROR",
        source="test",
    )

    assert result.success is False
    assert result.data is None
    assert result.error == "Something failed"
    assert result.code == "TEST_ERROR"
    assert result.source == "test"


def test_result_boolean_success():

    result = GenesisResult.ok()

    assert bool(result) is True


def test_result_boolean_failure():

    result = GenesisResult.fail(
        "failed"
    )

    assert bool(result) is False


def test_result_serialization():

    result = GenesisResult.ok(
        data="hello",
        source="test",
    )

    data = result.to_dict()

    assert data["success"] is True
    assert data["data"] == "hello"
    assert data["source"] == "test"


def test_reliability_guard_success():

    def operation():

        return 123

    result = ReliabilityGuard.call(
        operation,
        source="test",
    )

    assert result.success is True
    assert result.data == 123


def test_reliability_guard_failure():

    def operation():

        raise RuntimeError(
            "simulated failure"
        )

    result = ReliabilityGuard.call(
        operation,
        source="test",
    )

    assert result.success is False
    assert result.error == "simulated failure"
    assert result.code == "UNEXPECTED_ERROR"
    assert result.source == "test"


def test_safe_value():

    assert (
        ReliabilityGuard.safe_value(
            None,
            "fallback",
        )
        == "fallback"
    )

    assert (
        ReliabilityGuard.safe_value(
            "hello",
            "fallback",
        )
        == "hello"
    )


def test_safe_string():

    assert (
        ReliabilityGuard.safe_string(
            None
        )
        == ""
    )

    assert (
        ReliabilityGuard.safe_string(
            123
        )
        == "123"
    )


def test_safe_dict():

    assert (
        ReliabilityGuard.safe_dict(
            None
        )
        == {}
    )

    assert (
        ReliabilityGuard.safe_dict(
            {"x": 1}
        )
        == {"x": 1}
    )