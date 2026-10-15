"""Genesis OS — Real-OS Validation & Benchmark Entry Point.

Run with::

    python -m benchmark_real_os

Produces:
    GENESIS_REAL_OS_RESULTS.json
    GENESIS_REAL_OS_BENCHMARK_REPORT.md
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Ensure backend is on sys.path.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from .runner import RealOSBenchmark
from .scenarios import REAL_OS_SCENARIOS, COMPOUND_REAL_OS_SCENARIOS
from .report import write_reports


def main() -> int:
    workspace = os.environ.get(
        "GENESIS_REAL_OS_WORKSPACE",
        os.path.join(os.path.dirname(__file__), "..", "..", "genesis_real_os_workspace"),
    )
    output_dir = os.environ.get(
        "GENESIS_REAL_OS_OUTPUT",
        os.path.join(os.path.dirname(__file__), "..", ".."),
    )

    print("=" * 60)
    print("Genesis OS — Real-OS Validation Benchmark")
    print("=" * 60)
    print(f"Scenarios: {len(REAL_OS_SCENARIOS)} single-step + {len(COMPOUND_REAL_OS_SCENARIOS)} compound")
    print(f"Workspace: {workspace}")
    print(f"Output:    {output_dir}")
    print()

    runner = RealOSBenchmark(workspace_root=workspace)
    scenarios = REAL_OS_SCENARIOS + COMPOUND_REAL_OS_SCENARIOS

    t0 = time.time()
    results = runner.run_scenarios(scenarios)
    summary = runner.summary()
    elapsed = time.time() - t0

    print(f"Completed in {elapsed:.1f}s")
    print(f"  Total:      {summary.total}")
    print(f"  Passed:     {summary.passed}")
    print(f"  Failed:     {summary.failed}")
    print(f"  Timed out:  {summary.timed_out}")
    print(f"  Skipped:    {summary.skipped}")
    print(f"  Cleanup:    {summary.cleanup_failures}")
    print(f"  Unverified: {summary.unverified}")
    print(f"  REAL-OS:    {summary.real_os_passes}")
    print()

    json_path = os.path.join(output_dir, "GENESIS_REAL_OS_RESULTS.json")
    md_path = os.path.join(output_dir, "GENESIS_REAL_OS_BENCHMARK_REPORT.md")

    # Get capability registry count for the report
    try:
        from genesis_os.capability_registry import CapabilityRegistry
        reg_total = CapabilityRegistry.count()
    except Exception:
        reg_total = None

    paths = write_reports(results, summary, json_path, md_path, reg_total)
    print(f"JSON report:  {paths['json']}")
    print(f"MD report:    {paths['markdown']}")
    print()

    if summary.failed > 0:
        print("FAILURES:")
        for f in summary.failures:
            print(f"  {f['scenario_id']}: {f['failure_reason']}")
    print()
    print("Done.")
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
