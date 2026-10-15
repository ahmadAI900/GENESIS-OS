"""Genesis OS — Real-OS Validation & Benchmark Infrastructure.

A trustworthy validation layer that exercises the real Genesis
execution path on a real machine and independently verifies
physical postconditions.

This module deliberately distinguishes:

    REAL_OS       Genuinely executed on the host machine with
                  independent post-state verification.
    MOCKED        Execution layer is mocked (e.g. _MockOSManager).
                  Used by the legacy 500-task benchmark for
                  cross-host reproducibility.
    SIMULATED     The provider returns a simulated success without
                  touching the real OS (e.g. webbrowser fallback).
    REPLAY        Result was replayed from a recorded trace.
    HYBRID        Mixed semantic + physical evidence; the semantic
                  component passed but the physical post-condition
                  could not be fully verified.
    UNVERIFIED    No independent post-state signal could be obtained.

A scenario may ONLY be labelled ``REAL_OS_PASS`` when:

    1. The intent was semantically understood,
    2. The capability was dispatched to the real provider,
    3. The provider returned a result,
    4. AND an independent verifier (separate from the action
       implementation) confirmed the expected physical
       post-condition on the host.

This package never labels a mocked or simulated OS execution as
``REAL_OS``.
"""

from .contract import (
    RealOSScenario,
    RealOSCategory,
    EvidenceStrength,
    PassPolicy,
    SideEffect,
    RiskLevel,
    ExecutionMode,
    RealOSStep,
    CleanupStep,
)
from .evidence import (
    EvidenceRecord,
    EvidenceKind,
    StepEvidence,
    RealOSScenarioResult,
    RealOSRunSummary,
    FailureTaxonomy,
)
from .runner import RealOSBenchmark, run_benchmark
from .scenarios import (
    REAL_OS_SCENARIOS,
    COMPOUND_REAL_OS_SCENARIOS,
    list_scenarios,
)

__all__ = [
    "RealOSScenario",
    "RealOSCategory",
    "EvidenceStrength",
    "PassPolicy",
    "SideEffect",
    "RiskLevel",
    "ExecutionMode",
    "RealOSStep",
    "CleanupStep",
    "EvidenceRecord",
    "EvidenceKind",
    "StepEvidence",
    "RealOSScenarioResult",
    "RealOSRunSummary",
    "FailureTaxonomy",
    "RealOSBenchmark",
    "run_benchmark",
    "REAL_OS_SCENARIOS",
    "COMPOUND_REAL_OS_SCENARIOS",
    "list_scenarios",
]