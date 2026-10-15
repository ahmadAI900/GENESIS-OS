"""
Genesis OS — 500-Task Acceptance Benchmark Report
==================================================

Aggregates the per-scenario results from `runner.py` and
produces a human-readable report plus a JSON dump.

The report distinguishes:

    - REAL benchmark results: every scenario was driven
      through the actual WorkflowDecisionEngine and (for
      L3) the actual ActionExecutor with a MOCKED OS layer
      so the test is deterministic and reproducible.
    - SIMULATED-ONLY scenarios: tasks that genuinely need
      the host OS / network (e.g. real GUI control, real
      file resolution on the user's actual downloads
      folder) are flagged so they are not reported as
      architectural failures.

Pass criterion: a scenario passes when ALL required
metrics are True. Compound and recovery scenarios are
scored as described in the directive: planning,
execution, observation, verification, recovery, and
final outcome must all hold.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from benchmark.runner import (
    BenchmarkRunner,
    MetricScore,
    ScenarioResult,
)


# =========================================================
# AGGREGATION
# =========================================================


def aggregate(results: List[ScenarioResult]) -> Dict[str, Any]:
    """Aggregate per-scenario results into a summary."""

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    simulated_only = sum(1 for r in results if r.scenario.simulated_only)

    by_category: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "passed": 0, "failed": 0}
    )
    by_metric: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "passed": 0, "failed": 0}
    )
    by_level: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "passed": 0, "failed": 0}
    )

    failures: List[Dict[str, Any]] = []

    for r in results:
        cat = r.scenario.category
        by_category[cat]["total"] += 1
        if r.passed:
            by_category[cat]["passed"] += 1
        else:
            by_category[cat]["failed"] += 1
            failures.append(
                {
                    "scenario_id": r.scenario.scenario_id,
                    "category": cat,
                    "user_request": r.scenario.user_request,
                    "expected_level": r.scenario.expected_level,
                    "expected_mode": r.scenario.expected_mode,
                    "expected_intent": r.scenario.expected_intent,
                    "level_reached": r.level_reached,
                    "mode_reached": r.mode_reached,
                    "intent_reached": r.intent_reached,
                    "target_reached": r.target_reached,
                    "failed_metrics": [
                        m.metric for m in r.metrics if not m.passed
                    ],
                }
            )

        for m in r.metrics:
            by_metric[m.metric]["total"] += 1
            if m.passed:
                by_metric[m.metric]["passed"] += 1
            else:
                by_metric[m.metric]["failed"] += 1

        by_level[str(r.scenario.expected_level)]["total"] += 1
        if r.passed:
            by_level[str(r.scenario.expected_level)]["passed"] += 1
        else:
            by_level[str(r.scenario.expected_level)]["failed"] += 1

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "simulated_only": simulated_only,
        "pass_rate": (passed / total) if total else 0.0,
        "by_category": dict(by_category),
        "by_metric": dict(by_metric),
        "by_level": dict(by_level),
        "failures": failures,
    }


# =========================================================
# TEXT REPORT
# =========================================================


def render_text_report(agg: Dict[str, Any]) -> str:
    """Render the aggregated result as a human-readable
    report."""

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("            GENESIS OS — 500-TASK ACCEPTANCE BENCHMARK")
    lines.append("=" * 72)
    lines.append("")

    lines.append(f"Total scenarios:      {agg['total']}")
    lines.append(f"Passed:               {agg['passed']}")
    lines.append(f"Failed:               {agg['failed']}")
    lines.append(f"Simulated-only:       {agg['simulated_only']}")
    lines.append(f"Overall pass rate:    {agg['pass_rate'] * 100:.1f}%")
    lines.append("")

    lines.append("By category:")
    lines.append("-" * 72)
    for cat in sorted(agg["by_category"].keys()):
        info = agg["by_category"][cat]
        rate = (info["passed"] / info["total"]) * 100 if info["total"] else 0.0
        lines.append(
            f"  {cat:<40s} {info['passed']:>4d}/{info['total']:<4d} ({rate:5.1f}%)"
        )
    lines.append("")

    lines.append("By metric:")
    lines.append("-" * 72)
    for metric in (
        "understanding", "routing", "entity_resolution", "constraint_resolution",
        "capability_selection", "agent_selection", "planning", "execution",
        "observation", "verification", "recovery", "final_outcome",
    ):
        info = agg["by_metric"].get(metric, {"total": 0, "passed": 0, "failed": 0})
        rate = (info["passed"] / info["total"]) * 100 if info["total"] else 0.0
        lines.append(
            f"  {metric:<32s} {info['passed']:>4d}/{info['total']:<4d} ({rate:5.1f}%)"
        )
    lines.append("")

    lines.append("By expected level:")
    lines.append("-" * 72)
    for lvl in sorted(agg["by_level"].keys()):
        info = agg["by_level"][lvl]
        rate = (info["passed"] / info["total"]) * 100 if info["total"] else 0.0
        lines.append(
            f"  Level {lvl:<28s} {info['passed']:>4d}/{info['total']:<4d} ({rate:5.1f}%)"
        )
    lines.append("")

    if agg["failures"]:
        lines.append(f"Failures (showing up to 20 of {len(agg['failures'])}):")
        lines.append("-" * 72)
        for f in agg["failures"][:20]:
            lines.append(
                f"  [{f['scenario_id']}] {f['user_request']!r}"
            )
            lines.append(
                f"      expected: level={f['expected_level']} "
                f"mode={f['expected_mode']} intent={f['expected_intent']!r}"
            )
            lines.append(
                f"      got:      level={f['level_reached']} "
                f"mode={f['mode_reached']} intent={f['intent_reached']!r}"
            )
            lines.append(
                f"      failed:   {', '.join(f['failed_metrics'])}"
            )
        lines.append("")

    lines.append("=" * 72)
    lines.append("REAL vs SIMULATED:")
    lines.append(
        f"  - {agg['total'] - agg['simulated_only']} scenarios were driven through the REAL"
    )
    lines.append(
        f"    WorkflowDecisionEngine + ActionExecutor with a mocked OS layer."
    )
    lines.append(
        f"  - {agg['simulated_only']} scenarios are flagged simulated-only because"
    )
    lines.append(
        f"    they require a real filesystem / GUI / network that the"
    )
    lines.append(
        f"    benchmark environment does not provide."
    )
    lines.append("=" * 72)

    return "\n".join(lines)


# =========================================================
# JSON REPORT
# =========================================================


def render_json_report(agg: Dict[str, Any]) -> str:
    return json.dumps(agg, indent=2, default=str)


# =========================================================
# ENTRY POINT
# =========================================================


def main() -> int:
    runner = BenchmarkRunner()
    results = runner.run()
    agg = aggregate(results)
    text = render_text_report(agg)
    print(text)

    json_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "BENCHMARK_RESULTS.json"
    )
    json_path = os.path.abspath(json_path)
    with open(json_path, "w", encoding="utf-8") as fh:
        fh.write(render_json_report(agg))
    print(f"\nJSON report written to: {json_path}")

    return 0 if agg["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "aggregate",
    "render_text_report",
    "render_json_report",
    "main",
]
