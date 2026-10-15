from genesis_os.target_models import (
    TargetQuery,
    TargetCandidate,
)
from genesis_os.target_resolution import (
    TargetResolver,
)


def test_high_confidence_target_resolves():

    query = TargetQuery(
        text="student results",
        target_type="file",
    )

    candidates = [
        TargetCandidate(
            target_id="file-1",
            target_type="file",
            display_name="student_results.xlsx",
            value=r"C:\Users\Test\Downloads\student_results.xlsx",
            confidence=0.96,
            source="file_intelligence",
        ),
    ]

    result = TargetResolver().resolve(
        query,
        candidates,
    )

    assert result.successful is True
    assert result.resolved is not None

    assert (
        result.resolved.value
        == r"C:\Users\Test\Downloads\student_results.xlsx"
    )


def test_low_confidence_target_requires_clarification():

    query = TargetQuery(
        text="results",
        target_type="file",
    )

    candidates = [
        TargetCandidate(
            target_id="file-1",
            target_type="file",
            display_name="results.xlsx",
            value=r"C:\results.xlsx",
            confidence=0.61,
            source="file_intelligence",
        ),
    ]

    result = TargetResolver().resolve(
        query,
        candidates,
    )

    assert result.successful is False
    assert (
        result.requires_clarification
        is True
    )


def test_ambiguous_targets_require_clarification():

    query = TargetQuery(
        text="results",
        target_type="file",
    )

    candidates = [
        TargetCandidate(
            target_id="file-1",
            target_type="file",
            display_name="results.xlsx",
            value=r"C:\results.xlsx",
            confidence=0.93,
            source="file_intelligence",
        ),
        TargetCandidate(
            target_id="file-2",
            target_type="file",
            display_name="student_results.xlsx",
            value=r"C:\student_results.xlsx",
            confidence=0.90,
            source="file_intelligence",
        ),
    ]

    result = TargetResolver().resolve(
        query,
        candidates,
    )

    assert result.successful is False
    assert (
        result.requires_clarification
        is True
    )

    assert (
        "ambiguous"
        in result.clarification_reason.lower()
    )


def test_empty_candidates_require_clarification():

    query = TargetQuery(
        text="missing file",
        target_type="file",
    )

    result = TargetResolver().resolve(
        query,
        (),
    )

    assert result.successful is False
    assert (
        result.requires_clarification
        is True
    )


def test_best_candidate_wins_when_confident():

    query = TargetQuery(
        text="report",
        target_type="file",
    )

    candidates = [
        TargetCandidate(
            target_id="file-1",
            target_type="file",
            display_name="old_report.xlsx",
            value=r"C:\old_report.xlsx",
            confidence=0.71,
            source="file_intelligence",
        ),
        TargetCandidate(
            target_id="file-2",
            target_type="file",
            display_name="final_report.xlsx",
            value=r"C:\final_report.xlsx",
            confidence=0.97,
            source="file_intelligence",
        ),
    ]

    result = TargetResolver().resolve(
        query,
        candidates,
    )

    assert result.successful is True
    assert result.resolved is not None

    assert (
        result.resolved.display_name
        == "final_report.xlsx"
    )
from genesis_os.target_discovery import (
    TargetDiscovery,
    )


class FakeFileProvider:

    def discover(self, query):

        return [
            {
                "id": "file-1",
                "name": "student_results.xlsx",
                "path": (
                    r"C:\Users\Test\Downloads"
                    r"\student_results.xlsx"
                ),
                "confidence": 0.95,
                "source": "file_intelligence",
            }
        ]


    def test_dynamic_file_discovery():

        discovery = TargetDiscovery(
            file_provider=FakeFileProvider()
        )

        query = TargetQuery(
            text="student results",
            target_type="file",
        )

        candidates = discovery.discover(
            query
        )

        assert len(candidates) == 1

        assert (
            candidates[0].display_name
            == "student_results.xlsx"
        )   

        assert (
            candidates[0].target_type
            == "file"
        )


    def test_dynamic_discovery_and_resolution():

        discovery = TargetDiscovery(
            file_provider=FakeFileProvider()
        )

        query = TargetQuery(
            text="student results",
            target_type="file",
        )

        result = (
            discovery.discover_and_resolve(
                query
            )
        )

        assert result.successful is True

        assert result.resolved is not None

        assert (
            result.resolved.display_name
            == "student_results.xlsx"
        )