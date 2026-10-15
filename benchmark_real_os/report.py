"""Genesis OS — Real-OS benchmark report generator.

Produces two artefacts:

    * GENESIS_REAL_OS_RESULTS.json  (machine-readable)
    * GENESIS_REAL_OS_BENCHMARK_REPORT.md  (human-readable)

The reports intentionally distinguish:

    SEMANTIC PASS     intent was understood at routing layer
    EXECUTION PASS    provider dispatched and returned success
    VERIFICATION PASS post-condition independently verified
    REAL-OS PASS      all three + cleanup OK + independent verifier
                      saw the real external state satisfy the
                      post-condition
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .evidence import (
    EvidenceStrength,
    FailureTaxonomy,
    RealOSRunSummary,
    RealOSScenarioResult,
)


# ============================================================
# JSON REPORT
# ============================================================


def write_json_report(
    results: List[RealOSScenarioResult],
    summary: RealOSRunSummary,
    output_path: str,
) -> str:
    payload = {
        "summary": summary.to_dict(),
        "scenarios": [r.to_dict() for r in results],
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return output_path


# ============================================================
# MARKDOWN REPORT
# ============================================================


def write_markdown_report(
    results: List[RealOSScenarioResult],
    summary: RealOSRunSummary,
    output_path: str,
    capability_registry_total: Optional[int] = None,
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append("# Genesis OS — Real-OS Validation Benchmark Report")
    lines.append("")
    lines.append(f"_Started: {summary.started_at}_")
    lines.append(f"_Finished: {summary.finished_at}_")
    lines.append(f"_Total duration: {summary.duration:.2f}s_")
    lines.append("")

    # Headline numbers
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- **TOTAL SCENARIOS:** {summary.total}")
    lines.append(f"- **PASSED:** {summary.passed}")
    lines.append(f"- **FAILED:** {summary.failed}")
    lines.append(f"- **TIMED OUT:** {summary.timed_out}")
    lines.append(f"- **CLEANUP FAILURES:** {summary.cleanup_failures}")
    lines.append(f"- **UNVERIFIED:** {summary.unverified}")
    lines.append(f"- **SKIPPED:** {summary.skipped}")
    lines.append(f"- **PASS RATE:** {summary.pass_rate * 100:.1f}%")
    lines.append(f"- **REAL-OS PASS RATE:** {summary.real_os_pass_rate * 100:.1f}%")
    lines.append("")

    lines.append("## Evidence Layer Pass Counts")
    lines.append("")
    lines.append(f"- SEMANTIC PASS: {summary.semantic_passes}")
    lines.append(f"- EXECUTION PASS: {summary.execution_passes}")
    lines.append(f"- VERIFICATION PASS: {summary.verification_passes}")
    lines.append(f"- REAL-OS PASS: {summary.real_os_passes}")
    lines.append("")
    lines.append(
        "**Note:** A semantic pass means routing understood the request; "
        "an execution pass means the provider was dispatched and returned "
        "success; a verification pass means an independent code path "
        "checked the real external state; a REAL-OS pass requires all "
        "three plus successful cleanup."
    )
    lines.append("")

    lines.append("## Evidence Strength Distribution")
    lines.append("")
    if summary.evidence_level_distribution:
        lines.append("| Level | Description | Steps |")
        lines.append("|---|---|---|")
        for level, count in sorted(summary.evidence_level_distribution.items()):
            label = _evidence_level_label(int(level))
            lines.append(f"| {level} | {label} | {count} |")
    else:
        lines.append("(no evidence collected)")
    lines.append("")

    lines.append("## Capability Coverage")
    lines.append("")
    if summary.capability_coverage:
        lines.append("| Capability | Scenarios |")
        lines.append("|---|---|")
        for cap, count in sorted(summary.capability_coverage.items()):
            lines.append(f"| `{cap}` | {count} |")
    else:
        lines.append("(no capabilities recorded)")
    lines.append("")

    if capability_registry_total is not None:
        tested = len(summary.capability_coverage)
        lines.append("### Registry vs Real-OS Coverage")
        lines.append("")
        lines.append(f"- Registered capabilities: {capability_registry_total}")
        lines.append(f"- Capabilities touched by real-OS scenarios: {tested}")
        lines.append(
            f"- Capabilities not yet physically tested: "
            f"{max(0, capability_registry_total - tested)}"
        )
        lines.append("")

    lines.append("## Category Pass Rate")
    lines.append("")
    if summary.category_pass_rate:
        lines.append("| Category | Pass Rate |")
        lines.append("|---|---|")
        for cat, rate in sorted(summary.category_pass_rate.items()):
            lines.append(f"| {cat} | {rate * 100:.1f}% |")
    else:
        lines.append("(no categories)")
    lines.append("")

    lines.append("## Failures")
    lines.append("")
    if summary.failures:
        for f in summary.failures:
            lines.append(f"### {f['scenario_id']} — {f['name']}")
            lines.append("")
            lines.append(f"- **Status:** {f['status']}")
            lines.append(f"- **Taxonomy:** {f['failure_taxonomy']}")
            lines.append(f"- **Request:** `{f['natural_language_request']}`")
            lines.append(f"- **Reason:** {f['failure_reason']}")
            lines.append("")
    else:
        lines.append("(no failures)")
    lines.append("")

    lines.append("## Per-Scenario Results")
    lines.append("")
    for r in results:
        lines.append(f"### {r.scenario_id} — {r.name}")
        lines.append("")
        lines.append(f"- **Status:** {r.status}")
        lines.append(f"- **Passed:** {r.passed}")
        lines.append(f"- **Mode:** {r.mode.value}")
        lines.append(f"- **Risk:** {r.risk}")
        lines.append(f"- **Request:** `{r.natural_language_request}`")
        lines.append(f"- **Capabilities exercised:** {r.expected_capabilities}")
        if r.actual_capability:
            lines.append(f"- **Actual capability:** {r.actual_capability}")
        if r.failure_reason:
            lines.append(f"- **Failure reason:** {r.failure_reason}")
        if r.failure_taxonomy:
            lines.append(f"- **Failure taxonomy:** {r.failure_taxonomy.value}")
        for step in r.steps:
            lines.append(
                f"  - Step `{step.step_id}` capability=`{step.capability}` "
                f"exec_status={step.execution_status.value} "
                f"dispatch={step.dispatch_status.value} "
                f"strength=L{int(step.evidence_strength)}"
            )
        for c in r.cleanup:
            lines.append(
                f"  - Cleanup `{c.description}` success={c.success} "
                f"detail={c.detail!r}"
            )
        lines.append("")

    lines.append("## Environment")
    lines.append("")
    env = summary.environment or {}
    for k, v in sorted(env.items()):
        if k == "providers" and isinstance(v, dict):
            lines.append(f"- {k}:")
            for pk, pv in sorted(v.items()):
                lines.append(f"  - {pk}: {pv}")
        else:
            lines.append(f"- {k}: {v}")
    lines.append("")

    lines.append("## Honest Conclusion")
    lines.append("")
    lines.append(
        "This benchmark reports ONLY what was physically executed on "
        "the host machine during this run. A scenario is labelled "
        "REAL-OS PASS only when an independent code path (separate "
        "from the action implementation) confirmed the real external "
        "state satisfied the expected post-condition."
    )
    lines.append("")
    lines.append(
        "A semantic pass alone does NOT prove real execution. A "
        "provider-side success flag alone does NOT prove real "
        "execution. An evidence level of 1 or 2 is honest about "
        "being internal. Use this report together with the JSON "
        "results to inspect per-step evidence."
    )
    lines.append("")

    text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return output_path


def _evidence_level_label(level: int) -> str:
    return {
        0: "LEVEL_0 — No evidence",
        1: "LEVEL_1 — Internal software state only",
        2: "LEVEL_2 — Provider dispatch evidence",
        3: "LEVEL_3 — Observable external state",
        4: "LEVEL_4 — Post-condition independently verified",
        5: "LEVEL_5 — End-to-end real-machine with controlled setup + cleanup",
    }.get(level, f"LEVEL_{level}")


def write_reports(
    results: List[RealOSScenarioResult],
    summary: RealOSRunSummary,
    json_path: str,
    markdown_path: str,
    capability_registry_total: Optional[int] = None,
) -> Dict[str, str]:
    return {
        "json": write_json_report(results, summary, json_path),
        "markdown": write_markdown_report(
            results, summary, markdown_path, capability_registry_total
        ),
    }