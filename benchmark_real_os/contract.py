"""Genesis OS — Real-OS scenario contract.

A Pydantic schema describing each real-OS benchmark scenario
in a way that makes it impossible to confuse:

    "workflow was planned"             with
    "workflow physically executed"     and
    "outcome was independently verified"

Every scenario is a self-contained, reproducible test that:

    * prepares its own isolated workspace
    * executes a real Genesis capability against the host OS
    * independently verifies the post-condition from OUTSIDE
      the action implementation
    * cleans up after itself
    * records structured evidence for every step
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# ENUMS
# ============================================================


class RealOSCategory(str, Enum):
    """Top-level taxonomy of real-OS scenario categories."""

    APPLICATION = "application"
    GUI = "gui"
    FILESYSTEM = "filesystem"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    BROWSER = "browser"
    SYSTEM = "system"
    CLIPBOARD = "clipboard"
    CAPTURE = "capture"
    COMPOUND = "compound"


class RiskLevel(str, Enum):
    """Risk classification of a real-OS scenario.

    The runner uses this to require confirmation for destructive
    operations and to surface the risk in the report.
    """

    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    MODIFYING = "modifying"
    DESTRUCTIVE = "destructive"


class ExecutionMode(str, Enum):
    """How the scenario exercises Genesis."""

    REAL_OS = "REAL_OS"
    """Exercise the real Genesis OSManager against the host."""

    REAL_OS_LIVE = "REAL_OS_LIVE"
    """Same as REAL_OS but expected to produce a side effect visible
    to a human (window opening, etc.). The runner is free to skip
    these on headless hosts."""


class EvidenceStrength(int, Enum):
    """Honest evidence strength ladder.

    LEVEL_0  No evidence at all.
    LEVEL_1  Internal software state only (e.g. the OSManager
             returned a dict).
    LEVEL_2  Provider dispatch evidence (the provider method was
             actually called and returned a result).
    LEVEL_3  Observable external state (filesystem stat, psutil
             process info, pyperclip paste, real PNG decode).
    LEVEL_4  Postcondition independently verified by a different
             code path than the action (e.g. action wrote file ->
             verifier read file and compared contents).
    LEVEL_5  End-to-end real-machine evidence with controlled
             setup and cleanup.
    """

    LEVEL_0 = 0
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4
    LEVEL_5 = 5


class PassPolicy(str, Enum):
    """How a scenario decides its final pass/fail verdict.

    ALL_POSTCONDITIONS: every expected postcondition must be
        independently verified.
    BEST_EFFORT: physical postconditions are encouraged but
        missing-verification does not auto-fail the scenario.
    """

    ALL_POSTCONDITIONS = "all_postconditions"
    BEST_EFFORT = "best_effort"


class SideEffect(str, Enum):
    """Allowed / forbidden side-effect class for a scenario."""

    CREATE_FILE = "create_file"
    WRITE_FILE = "write_file"
    DELETE_FILE = "delete_file"
    CREATE_FOLDER = "create_folder"
    DELETE_FOLDER = "delete_folder"
    OPEN_APPLICATION = "open_application"
    CLOSE_APPLICATION = "close_application"
    GUI_INTERACTION = "gui_interaction"
    NETWORK_REQUEST = "network_request"
    CLIPBOARD_WRITE = "clipboard_write"
    SCREEN_CAPTURE = "screen_capture"
    SYSTEM_INSPECTION = "system_inspection"
    PROCESS_INSPECTION = "process_inspection"


# ============================================================
# SUPPORTING MODELS
# ============================================================


class Precondition(BaseModel):
    """A single precondition that must hold before the action.

    ``verifier`` is a callable taking no arguments and returning a
    ``(bool, str)`` tuple. The runner evaluates it in the
    prepared workspace.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    description: str
    verifier: Optional[Callable[[], Tuple[bool, str]]] = None
    """Optional callable. The runner resolves it at run time so
    that Pydantic does not pickle callables for JSON output."""

    verifier_id: Optional[str] = None
    """Stable identifier for the verifier so the contract remains
    JSON-serialisable. The runner looks the callable up by ID."""


class ExpectedPostcondition(BaseModel):
    """A single expected post-condition with its own verifier.

    The verifier MUST be implemented in a different code path
    from the action implementation. This is the rule that makes
    "independent verification" meaningful.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    description: str
    verifier: Optional[Callable[[], Tuple[bool, str]]] = None
    verifier_id: Optional[str] = None

    evidence_kind: str = "filesystem"
    """One of: filesystem, document, spreadsheet, browser,
    process, application, clipboard, capture, system, gui."""

    artifact_path: Optional[str] = None
    """Optional file / artifact path the verifier may inspect."""

    expected_value: Optional[str] = None
    """Optional expected value for verifiers that need it
    (e.g. verify_file_contains needs expected_substring)."""

    verifier_kwargs: Dict[str, Any] = Field(default_factory=dict)
    """Optional additional keyword arguments for the verifier
    (e.g. sheet_name, cell for verify_xlsx_value)."""


class CleanupStep(BaseModel):
    """A single cleanup action.

    Each cleanup step has its own verifier so a failed cleanup
    is visible in the report (the scenario is marked
    FAILED_CLEANUP)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    description: str
    action: Optional[Callable[[], Dict[str, Any]]] = None
    verifier: Optional[Callable[[], Tuple[bool, str]]] = None
    action_id: Optional[str] = None
    verifier_id: Optional[str] = None


class RealOSStep(BaseModel):
    """A single capability invocation within a compound scenario.

    For single-step scenarios there is exactly one RealOSStep."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    description: str
    intent: str
    """e.g. 'application.open', 'file.create', 'spreadsheet.sort'.

    This MUST match a registered Genesis capability or the runner
    will mark the step as UNSUPPORTED_CAPABILITY."""

    target: Optional[str] = None
    routing_text: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    expected_postconditions: List[ExpectedPostcondition] = Field(
        default_factory=list
    )
    timeout_seconds: float = 30.0


class VerificationRequirement(BaseModel):
    """What level of evidence this scenario requires."""

    min_evidence_strength: EvidenceStrength = EvidenceStrength.LEVEL_4
    requires_independent_verification: bool = True
    requires_cleanup: bool = True
    """When True the scenario must report cleanup_ok=True to pass."""


# ============================================================
# SCENARIO CONTRACT
# ============================================================


class RealOSScenario(BaseModel):
    """A single real-OS validation scenario.

    The contract is intentionally explicit so that every scenario
    document is self-contained and reproducible.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    scenario_id: str
    """Stable unique identifier (e.g. ``realos_fs_create_file``)."""

    name: str
    description: str
    category: RealOSCategory
    risk_level: RiskLevel
    platform: str = "windows"
    """The scenario declares its expected host platform. The runner
    may skip scenarios that do not match the host platform."""

    preconditions: List[Precondition] = Field(default_factory=list)
    natural_language_request: str
    expected_intent: str
    expected_capabilities: List[str] = Field(default_factory=list)
    expected_agents: List[str] = Field(default_factory=list)
    expected_workflow_shape: str = "single_step"

    execution_mode: ExecutionMode = ExecutionMode.REAL_OS

    allowed_side_effects: List[SideEffect] = Field(default_factory=list)
    forbidden_side_effects: List[SideEffect] = Field(default_factory=list)

    steps: List[RealOSStep] = Field(default_factory=list)
    """For single-step scenarios a single RealOSStep is provided.

    For compound scenarios multiple steps are listed in execution
    order."""

    expected_postconditions: List[ExpectedPostcondition] = Field(
        default_factory=list
    )

    verification_requirements: VerificationRequirement = Field(
        default_factory=VerificationRequirement
    )

    cleanup: List[CleanupStep] = Field(default_factory=list)
    timeout_seconds: float = 60.0

    pass_policy: PassPolicy = PassPolicy.ALL_POSTCONDITIONS

    artifacts: List[str] = Field(default_factory=list)
    """Static artifact paths that may be created. The runner uses
    these for evidence collection."""

    evidence_requirements: List[str] = Field(default_factory=list)
    """List of evidence kinds the scenario expects to produce
    (e.g. 'file_hash', 'process_id', 'clipboard_value')."""

    tags: List[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("scenario_id")
    @classmethod
    def _id_must_be_unique_prefixed(cls, value: str) -> str:
        v = (value or "").strip()
        if not v:
            raise ValueError("scenario_id is required")
        if not v.startswith(("realos_", "realcomp_")):
            raise ValueError(
                "scenario_id must start with 'realos_' or 'realcomp_' "
                f"(got {value!r})"
            )
        return v

    @field_validator("steps")
    @classmethod
    def _at_least_one_step(cls, value: List[RealOSStep]) -> List[RealOSStep]:
        if not value:
            raise ValueError("At least one RealOSStep is required")
        return value

    def expected_capability_id(self) -> Optional[str]:
        """Return the first expected capability (helper for the runner)."""
        if self.expected_capabilities:
            return self.expected_capabilities[0]
        return None

    def postcondition_descriptions(self) -> List[str]:
        return [p.description for p in self.expected_postconditions]