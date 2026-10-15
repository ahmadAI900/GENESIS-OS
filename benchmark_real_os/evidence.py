"""Genesis OS — Real-OS evidence model.

This module defines the structured evidence contract used by
the real-OS benchmark runner. Every observation, dispatch,
post-state check and cleanup step records an EvidenceRecord
so the report can answer the question:

    "Did Genesis actually perform this task on a real computer,
     and what evidence proves it?"
"""
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .contract import (
    EvidenceStrength,
    ExecutionMode,
    PassPolicy,
    RealOSScenario,
    SideEffect,
)


# ============================================================
# ENUMS
# ============================================================


class EvidenceKind(str, Enum):
    """What the evidence describes."""

    SEMANTIC = "semantic"
    """The intent was understood at the routing layer."""

    DISPATCH = "dispatch"
    """The capability was dispatched to the real provider."""

    EXECUTION = "execution"
    """The provider method returned a result."""

    OBSERVATION = "observation"
    """A real post-state signal was observed (filesystem, process,
    clipboard, etc.)."""

    VERIFICATION = "verification"
    """The expected post-condition was independently verified."""

    CLEANUP = "cleanup"
    """A cleanup step completed (or failed)."""

    TIMEOUT = "timeout"
    """The step timed out."""

    EXCEPTION = "exception"
    """An exception was raised."""

    RECOVERY = "recovery"
    """The recovery / replanning layer was triggered."""


class ExecutionStatus(str, Enum):
    """Discrete status of a step."""

    OK = "ok"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
    UNVERIFIED = "unverified"
    EXCEPTION = "exception"


class DispatchStatus(str, Enum):
    """How a capability was dispatched."""

    REAL_PROVIDER = "real_provider"
    MOCKED = "mocked"
    SIMULATED = "simulated"
    REPLAYED = "replayed"
    NOT_DISPATCHED = "not_dispatched"


class FailureTaxonomy(str, Enum):
    """Single primary cause class for a failed scenario."""

    UNDERSTANDING = "UNDERSTANDING"
    ROUTING = "ROUTING"
    ENTITY_RESOLUTION = "ENTITY_RESOLUTION"
    TARGET_RESOLUTION = "TARGET_RESOLUTION"
    CAPABILITY_SELECTION = "CAPABILITY_SELECTION"
    PLANNING = "PLANNING"
    DISPATCH = "DISPATCH"
    PROVIDER = "PROVIDER"
    PRECONDITION = "PRECONDITION"
    OBSERVATION = "OBSERVATION"
    VERIFICATION = "VERIFICATION"
    RECOVERY = "RECOVERY"
    CLEANUP = "CLEANUP"
    TIMEOUT = "TIMEOUT"
    PLATFORM = "PLATFORM"
    SECURITY = "SECURITY"
    DEPENDENCY = "DEPENDENCY"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    UNKNOWN = "UNKNOWN"


# ============================================================
# EVIDENCE RECORDS
# ============================================================


@dataclass
class EvidenceRecord:
    """A single piece of evidence about a step."""

    timestamp: str
    """ISO-8601 UTC timestamp."""

    scenario_id: str
    step_id: str
    event_type: EvidenceKind
    capability: Optional[str] = None
    provider: Optional[str] = None
    target: Optional[str] = None
    dispatch_status: DispatchStatus = DispatchStatus.NOT_DISPATCHED
    execution_status: Optional[ExecutionStatus] = None
    observation_status: Optional[ExecutionStatus] = None
    verification_status: Optional[ExecutionStatus] = None
    pre_state: Dict[str, Any] = field(default_factory=dict)
    post_state: Dict[str, Any] = field(default_factory=dict)
    artifact_path: Optional[str] = None
    process_id: Optional[int] = None
    window_title: Optional[str] = None
    file_hash: Optional[str] = None
    file_size: Optional[int] = None
    browser_url: Optional[str] = None
    clipboard_value: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exception: Optional[str] = None
    verification_reason: Optional[str] = None
    evidence_strength: EvidenceStrength = EvidenceStrength.LEVEL_0
    source: str = "scenario_runner"
    """Where the evidence came from (runner, verifier, runner helper)."""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["dispatch_status"] = self.dispatch_status.value
        d["execution_status"] = self.execution_status.value if self.execution_status else None
        d["observation_status"] = self.observation_status.value if self.observation_status else None
        d["verification_status"] = self.verification_status.value if self.verification_status else None
        d["evidence_strength"] = int(self.evidence_strength)
        return d


@dataclass
class StepEvidence:
    """Aggregated evidence for a single RealOSStep."""

    step_id: str
    description: str
    capability: str
    target: Optional[str] = None
    started_at: str = ""
    finished_at: str = ""
    duration: float = 0.0
    execution_status: ExecutionStatus = ExecutionStatus.UNVERIFIED
    dispatch_status: DispatchStatus = DispatchStatus.NOT_DISPATCHED
    evidence_strength: EvidenceStrength = EvidenceStrength.LEVEL_0
    records: List[EvidenceRecord] = field(default_factory=list)
    semantic_pass: bool = False
    execution_pass: bool = False
    verification_pass: bool = False
    failure_reason: Optional[str] = None
    failure_taxonomy: FailureTaxonomy = FailureTaxonomy.UNKNOWN

    def add_record(self, record: EvidenceRecord) -> None:
        self.records.append(record)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "capability": self.capability,
            "target": self.target,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "execution_status": self.execution_status.value,
            "dispatch_status": self.dispatch_status.value,
            "evidence_strength": int(self.evidence_strength),
            "records": [r.to_dict() for r in self.records],
            "semantic_pass": self.semantic_pass,
            "execution_pass": self.execution_pass,
            "verification_pass": self.verification_pass,
            "failure_reason": self.failure_reason,
            "failure_taxonomy": self.failure_taxonomy.value,
        }


@dataclass
class CleanupEvidence:
    """Evidence of a single cleanup step."""

    description: str
    success: bool
    detail: str = ""
    error: Optional[str] = None


# ============================================================
# SCENARIO RESULT
# ============================================================


@dataclass
class RealOSScenarioResult:
    """Final structured result for one real-OS scenario."""

    scenario_id: str
    name: str
    mode: ExecutionMode
    started_at: str
    finished_at: str
    duration: float
    passed: bool
    """True iff semantic + execution + verification all pass and
    cleanup did not fail."""

    status: str
    """One of: PASS, FAIL, TIMED_OUT, SKIPPED, FAILED_CLEANUP,
    UNVERIFIED, EXCEPTION."""

    steps: List[StepEvidence] = field(default_factory=list)
    evidence: List[EvidenceRecord] = field(default_factory=list)
    cleanup: List[CleanupEvidence] = field(default_factory=list)
    failure_reason: Optional[str] = None
    failure_taxonomy: FailureTaxonomy = FailureTaxonomy.UNKNOWN
    verification_summary: Dict[str, Any] = field(default_factory=dict)
    risk: str = "read_only"
    artifacts: List[str] = field(default_factory=list)
    environment: Dict[str, Any] = field(default_factory=dict)
    natural_language_request: str = ""
    expected_capabilities: List[str] = field(default_factory=list)
    actual_capability: Optional[str] = None
    category: str = ""

    @property
    def semantic_pass(self) -> bool:
        return any(s.semantic_pass for s in self.steps) if self.steps else False

    @property
    def execution_pass(self) -> bool:
        return all(s.execution_pass for s in self.steps) if self.steps else False

    @property
    def verification_pass(self) -> bool:
        return all(s.verification_pass for s in self.steps) if self.steps else False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "mode": self.mode.value,
            "category": self.category,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "passed": self.passed,
            "status": self.status,
            "natural_language_request": self.natural_language_request,
            "expected_capabilities": self.expected_capabilities,
            "actual_capability": self.actual_capability,
            "semantic_pass": self.semantic_pass,
            "execution_pass": self.execution_pass,
            "verification_pass": self.verification_pass,
            "steps": [s.to_dict() for s in self.steps],
            "cleanup": [
                {
                    "description": c.description,
                    "success": c.success,
                    "detail": c.detail,
                    "error": c.error,
                }
                for c in self.cleanup
            ],
            "failure_reason": self.failure_reason,
            "failure_taxonomy": self.failure_taxonomy.value,
            "verification_summary": self.verification_summary,
            "risk": self.risk,
            "artifacts": self.artifacts,
            "environment": self.environment,
        }


# ============================================================
# RUN SUMMARY
# ============================================================


@dataclass
class RealOSRunSummary:
    """Top-level summary produced by the runner."""

    started_at: str
    finished_at: str
    duration: float
    total: int
    passed: int
    failed: int
    timed_out: int
    skipped: int
    cleanup_failures: int
    unverified: int
    semantic_passes: int
    execution_passes: int
    verification_passes: int
    real_os_passes: int
    """REAL_OS_PASS count = passed + verified-by-real-host-evidence."""

    pass_rate: float
    real_os_pass_rate: float
    evidence_level_distribution: Dict[str, int] = field(default_factory=dict)
    capability_coverage: Dict[str, int] = field(default_factory=dict)
    category_pass_rate: Dict[str, float] = field(default_factory=dict)
    environment: Dict[str, Any] = field(default_factory=dict)
    failures: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "skipped": self.skipped,
            "cleanup_failures": self.cleanup_failures,
            "unverified": self.unverified,
            "semantic_passes": self.semantic_passes,
            "execution_passes": self.execution_passes,
            "verification_passes": self.verification_passes,
            "real_os_passes": self.real_os_passes,
            "pass_rate": self.pass_rate,
            "real_os_pass_rate": self.real_os_pass_rate,
            "evidence_level_distribution": self.evidence_level_distribution,
            "capability_coverage": self.capability_coverage,
            "category_pass_rate": self.category_pass_rate,
            "environment": self.environment,
            "failures": self.failures,
        }


# ============================================================
# ENVIRONMENT METADATA
# ============================================================


def collect_environment_metadata() -> Dict[str, Any]:
    """Collect safe environment metadata for the run report.

    NEVER records API keys, tokens, passwords, or any private
    user data."""

    env: Dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "hostname": socket.gethostname() if hasattr(socket, "hostname") else "unknown",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    try:
        env["git_commit"] = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        env["git_commit"] = None

    try:
        env["git_branch"] = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        env["git_branch"] = None

    providers: Dict[str, str] = {}

    def _probe(module: str) -> Optional[str]:
        try:
            mod = __import__(module)
            v = getattr(mod, "__version__", None)
            return str(v) if v else "available"
        except Exception:
            return None

    for label, mod in (
        ("openpyxl", "openpyxl"),
        ("python-docx", "docx"),
        ("PIL", "PIL"),
        ("playwright", "playwright"),
        ("selenium", "selenium"),
        ("pyautogui", "pyautogui"),
        ("psutil", "psutil"),
        ("pyperclip", "pyperclip"),
        ("pydantic", "pydantic"),
    ):
        v = _probe(mod)
        if v is not None:
            providers[label] = v

    env["providers"] = providers
    return env