"""
ITEM 19C (T15) -- a verification gate must fail, never skip, when its
subject stops producing the thing it verifies.

test_security_agent_measures_password_deterministically used to treat a
missing password_analysis as a pytest.skip("regex did not match; ensure
gate text present"): if the SecurityAgent's deterministic regex/entropy
analysis ever broke, the suite would go GREEN (skipped) instead of red,
hiding the regression behind a message nobody reads.

The fix replaces the skip with an assert. These meta-tests drive the
gate with a SecurityAgent.run that returns metadata WITHOUT
password_analysis and require an AssertionError (test failed), not a
Skipped outcome; a source pin keeps pytest.skip out of the gate.
"""
import inspect
import textwrap

from _pytest.outcomes import Skipped

import test_level2_5_agent_tools as gate_module


def _outcome_without_password_analysis(monkeypatch):
    """Run the gate with analysis missing; return passed/failed/skipped."""
    from agents.security_agent import SecurityAgent

    def run_without_analysis(self, request):
        return {
            "response": "Security assessment: the password is weak.",
            "metadata": {},
            "agents": [],
            "confidence": 0.0,
        }

    monkeypatch.setattr(SecurityAgent, "run", run_without_analysis)

    try:
        gate_module.test_security_agent_measures_password_deterministically()
    except Skipped:
        return "skipped"
    except AssertionError:
        return "failed"
    return "passed"


def test_password_gate_fails_when_analysis_is_missing(monkeypatch):
    outcome = _outcome_without_password_analysis(monkeypatch)

    assert outcome == "failed", (
        "when password_analysis is missing the gate must FAIL; a skip "
        f"turns a broken analysis path green (outcome was: {outcome})"
    )


def test_password_gate_source_contains_no_skip():
    src = textwrap.dedent(
        inspect.getsource(
            gate_module.test_security_agent_measures_password_deterministically
        )
    )

    assert "pytest.skip" not in src, (
        "the password gate must not offer a skip path"
    )
    assert "password_analysis" in src
