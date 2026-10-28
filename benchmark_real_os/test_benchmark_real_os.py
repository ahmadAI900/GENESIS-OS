"""Regression tests for the real-OS benchmark framework.

These tests validate the contract models, evidence structures, scenario
definitions, report generation, and runner plumbing WITHOUT actually
executing any real-OS actions.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: RealOSBenchmark deliberately uses a real OSManager.
# --------------------------------------------------------------
pytestmark = pytest.mark.live

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from benchmark_real_os.contract import (
    CleanupStep,
    ExecutionMode,
    RealOSCategory,
    Precondition,
    RealOSScenario,
    RealOSStep,
    EvidenceStrength,
    PassPolicy,
)
from benchmark_real_os.evidence import (
    EvidenceKind,
    EvidenceRecord,
    FailureTaxonomy,
    RealOSRunSummary,
    RealOSScenarioResult,
    StepEvidence,
)
from benchmark_real_os.scenarios import (
    REAL_OS_SCENARIOS,
    COMPOUND_REAL_OS_SCENARIOS,
    list_scenarios,
)
from benchmark_real_os.verifiers import (
    verify_file_contains,
    verify_file_exists,
    verify_process_running,
)
from benchmark_real_os.report import (
    write_json_report,
    write_markdown_report,
    write_reports,
)


# ── CONTRACTS ─────────────────────────────────────────────────────


class TestScenarioContract:
    def test_all_scenarios_have_unique_ids(self):
        ids = [s.scenario_id for s in REAL_OS_SCENARIOS]
        assert len(ids) == len(set(ids)), "Duplicate scenario IDs found"

    def test_all_scenarios_have_at_least_one_step(self):
        for s in REAL_OS_SCENARIOS:
            assert len(s.steps) >= 1, f"{s.scenario_id} has no steps"

    def test_all_scenarios_have_category(self):
        for s in REAL_OS_SCENARIOS:
            assert s.category in RealOSCategory

    def test_all_scenarios_have_pass_policy(self):
        for s in REAL_OS_SCENARIOS:
            assert s.pass_policy in PassPolicy

    def test_cleanup_steps_are_valid(self):
        for s in REAL_OS_SCENARIOS:
            for c in s.cleanup:
                assert isinstance(c, CleanupStep)

    def test_compound_scenarios_have_multiple_steps(self):
        for s in COMPOUND_REAL_OS_SCENARIOS:
            assert len(s.steps) >= 2, f"Compound {s.scenario_id} has < 2 steps"

    def test_preconditions_are_valid(self):
        for s in REAL_OS_SCENARIOS:
            for pre in s.preconditions:
                assert isinstance(pre, Precondition)


class TestStepContract:
    def test_steps_have_intent(self):
        for s in REAL_OS_SCENARIOS:
            for step in s.steps:
                assert step.intent, f"Step in {s.scenario_id} missing intent"


class TestCompoundScenarios:
    def test_compound_scenarios_have_expected_postconditions(self):
        for s in COMPOUND_REAL_OS_SCENARIOS:
            has_posts = any(
                len(step.expected_postconditions) > 0 for step in s.steps
            )
            assert has_posts, f"{s.scenario_id} has no expected_postconditions"


# ── EVIDENCE MODEL ────────────────────────────────────────────────


class TestEvidenceRecord:
    def test_creation(self):
        er = EvidenceRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            scenario_id="test_001",
            step_id="step1",
            event_type=EvidenceKind.OBSERVATION,
            post_state={"ok": True},
            evidence_strength=EvidenceStrength.LEVEL_3,
        )
        assert er.scenario_id == "test_001"
        assert er.evidence_strength == EvidenceStrength.LEVEL_3

    def test_default_values(self):
        er = EvidenceRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            scenario_id="test",
            step_id="s",
            event_type=EvidenceKind.SEMANTIC,
            post_state={},
            evidence_strength=EvidenceStrength.LEVEL_0,
        )
        assert er.capability is None
        assert er.process_id is None
        assert er.file_hash is None


class TestStepEvidence:
    def test_creation(self):
        se = StepEvidence(
            step_id="s1",
            description="test step",
            capability="file.write",
            target="/tmp/test.txt",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        assert se.execution_pass is False  # default, not None
        assert se.verification_pass is False
        assert se.records == []


class TestScenarioResult:
    def test_creation(self):
        now = datetime.now(timezone.utc).isoformat()
        sr = RealOSScenarioResult(
            scenario_id="test_001",
            name="Test",
            mode=ExecutionMode.REAL_OS,
            started_at=now, finished_at=now, duration=1.0,
            passed=True, status="PASS",
        )
        assert sr.passed is True
        assert sr.steps == []


class TestRunSummary:
    def test_build_from_results(self):
        now = datetime.now(timezone.utc).isoformat()
        sr1 = RealOSScenarioResult(
            scenario_id="t1", name="T1",
            mode=ExecutionMode.REAL_OS,
            started_at=now, finished_at=now, duration=1.0,
            passed=True, status="PASS",
        )
        sr2 = RealOSScenarioResult(
            scenario_id="t2", name="T2",
            mode=ExecutionMode.REAL_OS,
            started_at=now, finished_at=now, duration=1.0,
            passed=False, status="FAIL",
            failure_reason="test failure",
            failure_taxonomy=FailureTaxonomy.UNDERSTANDING,
        )
        summary = RealOSRunSummary(
            started_at=now, finished_at=now, duration=2.0,
            total=2, passed=1, failed=1, timed_out=0,
            skipped=0, cleanup_failures=0, unverified=0,
            semantic_passes=1, execution_passes=1,
            verification_passes=1, real_os_passes=1,
            pass_rate=0.5, real_os_pass_rate=0.5,
        )
        assert summary.total == 2
        assert summary.passed == 1
        assert summary.failed == 1
        assert summary.real_os_passes == 1


# ── VERIFIERS ─────────────────────────────────────────────────────


class TestVerifiers:
    def test_file_exists_positive(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("hello", encoding="utf-8")
        passed, detail, evidence = verify_file_exists(str(p))
        assert passed is True

    def test_file_exists_negative(self, tmp_path):
        passed, detail, evidence = verify_file_exists(str(tmp_path / "nonexistent.txt"))
        assert passed is False

    def test_file_contains_positive(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("hello world", encoding="utf-8")
        passed, detail, evidence = verify_file_contains(str(p), "hello")
        assert passed is True

    def test_file_contains_negative(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("hello world", encoding="utf-8")
        passed, detail, evidence = verify_file_contains(str(p), "xyz")
        assert passed is False

    def test_process_running_returns_tuple(self):
        passed, detail, evidence = verify_process_running("python")
        assert isinstance(passed, bool)


# ── REPORT GENERATION ─────────────────────────────────────────────


class TestReportGeneration:
    def _make_result(self, scenario_id="t1", status="PASS", taxonomy=None):
        now = datetime.now(timezone.utc).isoformat()
        return RealOSScenarioResult(
            scenario_id=scenario_id,
            name=f"Test {scenario_id}",
            mode=ExecutionMode.REAL_OS,
            started_at=now, finished_at=now, duration=1.0,
            passed=(status == "PASS"), status=status,
            failure_reason="test" if status == "FAIL" else None,
            failure_taxonomy=taxonomy or FailureTaxonomy.UNKNOWN,
            category="filesystem",
        )

    def _make_summary(self, results):
        now = datetime.now(timezone.utc).isoformat()
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        total = len(results)
        return RealOSRunSummary(
            started_at=now, finished_at=now, duration=float(total),
            total=total, passed=passed, failed=failed, timed_out=0,
            skipped=0, cleanup_failures=0, unverified=0,
            semantic_passes=passed, execution_passes=passed,
            verification_passes=passed, real_os_passes=passed,
            pass_rate=passed / total if total else 0.0,
            real_os_pass_rate=passed / total if total else 0.0,
        )

    def test_json_report_writes_valid_json(self, tmp_path):
        results = [
            self._make_result("t1", "PASS"),
            self._make_result("t2", "FAIL", FailureTaxonomy.TIMEOUT),
        ]
        summary = self._make_summary(results)
        json_path = str(tmp_path / "results.json")
        write_json_report(results, summary, json_path)
        assert os.path.exists(json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "summary" in data
        assert "scenarios" in data
        assert len(data["scenarios"]) == 2

    def test_markdown_report_writes_file(self, tmp_path):
        results = [self._make_result("t1", "PASS")]
        summary = self._make_summary(results)
        md_path = str(tmp_path / "report.md")
        write_markdown_report(results, summary, md_path)
        assert os.path.exists(md_path)
        content = Path(md_path).read_text(encoding="utf-8")
        assert "Real-OS Validation Benchmark Report" in content

    def test_write_reports_returns_both_paths(self, tmp_path):
        results = [self._make_result("t1", "PASS")]
        summary = self._make_summary(results)
        paths = write_reports(
            results, summary,
            str(tmp_path / "r.json"),
            str(tmp_path / "r.md"),
        )
        assert os.path.exists(paths["json"])
        assert os.path.exists(paths["markdown"])


# ── SCENARIO INVENTORY ────────────────────────────────────────────


class TestScenarioInventory:
    def test_minimum_single_step_scenarios(self):
        assert len(REAL_OS_SCENARIOS) >= 25, (
            f"Expected >= 25 single-step scenarios, got {len(REAL_OS_SCENARIOS)}"
        )

    def test_minimum_compound_scenarios(self):
        assert len(COMPOUND_REAL_OS_SCENARIOS) >= 2, (
            f"Expected >= 2 compound scenarios, got {len(COMPOUND_REAL_OS_SCENARIOS)}"
        )

    def test_list_scenarios_includes_all(self):
        all_scenarios = list_scenarios()
        assert len(all_scenarios) >= len(REAL_OS_SCENARIOS) + len(COMPOUND_REAL_OS_SCENARIOS)

    def test_categories_covered(self):
        covered = {s.category for s in REAL_OS_SCENARIOS}
        required = {
            RealOSCategory.APPLICATION,
            RealOSCategory.FILESYSTEM,
            RealOSCategory.DOCUMENT,
            RealOSCategory.SPREADSHEET,
            RealOSCategory.BROWSER,
            RealOSCategory.SYSTEM,
        }
        assert required.issubset(covered), f"Missing: {required - covered}"

    def test_all_scenarios_have_unique_natural_language_requests(self):
        requests = [s.natural_language_request for s in REAL_OS_SCENARIOS]
        assert len(requests) == len(set(requests)), "Duplicate natural_language_requests"

    def test_each_category_has_at_least_one_scenario(self):
        from collections import Counter
        cat_counts = Counter(s.category for s in REAL_OS_SCENARIOS)
        for cat, count in cat_counts.items():
            assert count >= 1, f"Category {cat.value} has {count} scenario(s)"


# ── RUNNER (MOCKED OS MANAGER) ────────────────────────────────────


class TestRunnerWithMockOSM:
    pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

    def test_runner_initializes(self, tmp_path):
        from benchmark_real_os.runner import RealOSBenchmark
        runner = RealOSBenchmark(workspace_root=str(tmp_path))
        assert runner.workspace_root == tmp_path

    def test_runner_build_decision(self, tmp_path):
        from benchmark_real_os.runner import RealOSBenchmark
        runner = RealOSBenchmark(workspace_root=str(tmp_path))
        scenario = REAL_OS_SCENARIOS[0]
        step = scenario.steps[0]
        decision = runner._build_decision(scenario, step)
        assert "intent" in decision
        assert "target" in decision
        assert "parameters" in decision

    # -----------------------------------------------------------------
    # DISPATCH PATH  [REWRITTEN 2026-10-04]
    # -----------------------------------------------------------------
    # The five `test_runner_osm_call_args_*` tests that used to live here
    # asserted the shape of the arguments a direct OSManager call would
    # receive. That code path no longer exists: `RealOSBenchmark.
    # _dispatch` now builds an ActionPlan and executes it through the
    # production `ActionExecutor` exclusively, and its docstring states
    # the reason -- "The benchmark uses the production executor
    # exclusively; it does not silently fall back to a direct OSManager
    # call."
    #
    # Asserting argument shapes for a removed fallback would pin a
    # capability the benchmark no longer has, so these tests now pin the
    # contract that replaced it: EVERY step reaches the executor, and
    # the executor is the only dispatch route.

    _REGISTERED_STEPS = (
        ("document.create", "/tmp/doc.docx",
         {"title": "Test", "sections": []}),
        ("file.create", "/tmp/test.txt", {"content": "hello"}),
        ("file.open", "/tmp/test.txt", {}),
        ("folder.open", "/tmp", {}),
    )

    # The benchmark's own scenarios name intents that are not
    # registered Genesis capabilities. With the direct OSManager
    # fallback gone, those are now rejected by the executor and the
    # runner reports NOT_DISPATCHED. That is the honest outcome, and
    # the second half of the contract: the runner must say so rather
    # than quietly reaching around the executor.
    _UNREGISTERED_STEPS = (
        ("system.process.list", "/not/used", {"name": "python"}),
        ("file.write", "/tmp/test.txt", {"content": "hello"}),
        ("spreadsheet.create", "/tmp/sheet.xlsx",
         {"headers": ["A", "B"], "rows": [["1", "2"]]}),
        ("browser.navigate", "https://example.com", {}),
    )

    @staticmethod
    def _runner(tmp_path):
        from benchmark_real_os.runner import RealOSBenchmark
        return RealOSBenchmark(workspace_root=str(tmp_path))

    def _dispatch_with_mock_executor(self, runner, tmp_path, intent,
                                     target, parameters):
        """Drive `_dispatch` with a recording ActionExecutor stand-in."""
        recorded = {}

        class _RecordingResult:
            def to_dict(self):
                return {
                    "success": True,
                    "operation": recorded["plan"].operation,
                }

        class _RecordingExecutor:
            def execute(self, plan):
                recorded["plan"] = plan
                return _RecordingResult()

        runner.executor = _RecordingExecutor()
        step = RealOSStep(description="probe", intent=intent,
                          target=target, parameters=parameters)
        scenario = REAL_OS_SCENARIOS[0]
        decision = runner._build_decision(scenario, step)
        status, payload, raw = runner._dispatch(
            scenario, step, decision, tmp_path
        )
        return recorded, status, payload, raw

    def test_every_step_dispatches_through_the_action_executor(self, tmp_path):
        """No registered intent bypasses the executor."""
        for intent, target, parameters in self._REGISTERED_STEPS:
            recorded, _, _, _ = self._dispatch_with_mock_executor(
                self._runner(tmp_path),
                tmp_path, intent, target, parameters,
            )
            assert "plan" in recorded, (
                f"{intent!r} was never handed to the ActionExecutor"
            )
            assert recorded["plan"].operation == intent

    def test_dispatch_reports_a_real_provider_status(self, tmp_path):
        """The executor path is reported as a real dispatch."""
        from benchmark_real_os.evidence import DispatchStatus

        for intent, target, parameters in self._REGISTERED_STEPS:
            _, status, payload, _ = self._dispatch_with_mock_executor(
                self._runner(tmp_path),
                tmp_path, intent, target, parameters,
            )
            assert status == DispatchStatus.REAL_PROVIDER, (
                f"{intent!r} reported {status!r} instead of a real "
                f"executor dispatch"
            )
            assert payload["success"] is True

    def test_dispatch_carries_the_steps_parameters_to_the_executor(self, tmp_path):
        """The step's parameters reach the executor intact.

        This is the part of the old arg-shape tests that still had
        value: the step's own parameters must not be dropped between
        `_build_decision` and the plan.
        """
        for intent, target, parameters in self._REGISTERED_STEPS:
            if not parameters:
                continue
            recorded, _, _, _ = self._dispatch_with_mock_executor(
                self._runner(tmp_path),
                tmp_path, intent, target, parameters,
            )
            carried = recorded["plan"].parameters
            for key in parameters:
                assert key in carried, (
                    f"{intent!r}: parameter {key!r} was dropped before "
                    f"dispatch; plan carried {sorted(carried)}"
                )

    def test_unregistered_intent_fails_closed_instead_of_falling_back(
        self, tmp_path
    ):
        """An unregistered intent must NOT reach around the executor.

        This is the anti-regression for the removed fallback: the runner
        has to report the rejection, not quietly call OSManager itself.
        """
        from benchmark_real_os.evidence import DispatchStatus

        for intent, target, parameters in self._UNREGISTERED_STEPS:
            recorded, status, payload, _ = self._dispatch_with_mock_executor(
                self._runner(tmp_path),
                tmp_path, intent, target, parameters,
            )
            assert "plan" not in recorded, (
                f"{intent!r} unexpectedly reached the executor"
            )
            assert status == DispatchStatus.NOT_DISPATCHED, (
                f"{intent!r} reported {status!r} instead of failing closed"
            )
            assert "direct OSManager fallback is disabled" in (
                payload.get("error", "")
            ), payload

    def test_runner_has_no_direct_osmanager_fallback(self, tmp_path):
        """The removed fallback must stay removed.

        Structural, so it cannot come back unnoticed: the runner must
        not define a helper that builds a direct OSManager call.
        """
        runner = self._runner(tmp_path)
        assert not hasattr(runner, "_build_osm_call_args")
        assert hasattr(runner, "_dispatch")

    def test_runner_cleanup_with_callable_action(self, tmp_path):
        from benchmark_real_os.runner import RealOSBenchmark
        runner = RealOSBenchmark(workspace_root=str(tmp_path))
        test_file = tmp_path / "to_delete.txt"
        test_file.write_text("delete me", encoding="utf-8")
        step = CleanupStep(
            description="Remove test file",
            action=lambda: {"deleted": True},
            verifier=lambda: (True, "file absent", {}),
        )
        ok, detail, taxonomy = runner._run_cleanup(step)
        assert isinstance(ok, bool)

    def test_runner_cleanup_failure(self, tmp_path):
        from benchmark_real_os.runner import RealOSBenchmark
        runner = RealOSBenchmark(workspace_root=str(tmp_path))
        step = CleanupStep(
            description="Nonexistent cleanup",
            action=lambda: {"deleted": False},
            verifier=lambda: (False, "still exists", {}),
        )
        ok, detail, taxonomy = runner._run_cleanup(step)
        assert isinstance(ok, bool)
