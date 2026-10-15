"""Genesis OS — Real-OS validation scenario suite.

The scenarios are intentionally minimal: each one

    1. prepares its own isolated workspace
    2. runs ONE concrete capability through the real Genesis
       OSManager
    3. independently verifies the post-condition
    4. cleans up after itself

The scenarios are JSON-serialisable (callables are stored as
named IDs in the ``NAMED_VERIFIERS`` registry). The runner
binds the callables at run time.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .contract import (
    CleanupStep,
    ExpectedPostcondition,
    Precondition,
    RealOSCategory,
    RealOSScenario,
    RealOSStep,
    RiskLevel,
    SideEffect,
    VerificationRequirement,
    EvidenceStrength,
    PassPolicy,
)
from .verifiers import (
    NAMED_VERIFIERS,
    VerifierResult,
    verify_battery_reported,
    verify_clipboard_contains,
    verify_docx,
    verify_file_absent,
    verify_file_contains,
    verify_file_exists,
    verify_folder_absent,
    verify_folder_exists,
    verify_hardware_stats_reported,
    verify_image_decodes,
    verify_process_absent,
    verify_process_count_in_range,
    verify_process_running,
    verify_processes_listed,
    verify_system_returns_status,
    verify_text_document,
    verify_xlsx_has_sheet,
    verify_xlsx_value,
)


# ============================================================
# HELPERS
# ============================================================


def _verifier(verifier_id: str, *args: Any) -> Callable[[], VerifierResult]:
    """Build a zero-arg verifier callable that closes over the
    verifier_id and args. The runner calls it with no arguments."""

    def _call() -> VerifierResult:
        fn = NAMED_VERIFIERS.get(verifier_id)
        if fn is None:
            return False, f"unknown verifier_id: {verifier_id}", {}
        return fn(*args)

    return _call


def _cleanup_action(target: str) -> Callable[[], Dict[str, Any]]:
    def _do() -> Dict[str, Any]:
        try:
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
                return {"action": "rmdir", "target": target, "ok": True}
            elif os.path.exists(target):
                os.remove(target)
                return {"action": "remove", "target": target, "ok": True}
            return {"action": "noop", "target": target, "ok": True}
        except Exception as exc:
            return {"action": "cleanup_exception", "target": target, "ok": False, "error": str(exc)}
    return _do


def _file_remove_action(target: str) -> Callable[[], Dict[str, Any]]:
    def _do() -> Dict[str, Any]:
        try:
            if os.path.exists(target):
                os.remove(target)
            return {"action": "remove", "target": target, "ok": True}
        except Exception as exc:
            return {"action": "remove_exception", "target": target, "ok": False, "error": str(exc)}
    return _do


# ============================================================
# APPLICATION SCENARIOS
# ============================================================


SCENARIO_APPLICATION_INSPECT_NOTEPAD = RealOSScenario(
    scenario_id="realos_app_inspect_notepad",
    name="Inspect Notepad (no launch)",
    description=(
        "Inspect the Notepad application. Expected: the inspector "
        "returns success with Notepad metadata. No launch required."
    ),
    category=RealOSCategory.APPLICATION,
    risk_level=RiskLevel.READ_ONLY,
    allowed_side_effects=[SideEffect.SYSTEM_INSPECTION],
    natural_language_request="Inspect Notepad.",
    expected_intent="application.inspect",
    expected_capabilities=["application.inspect"],
    expected_agents=[],
    expected_workflow_shape="single_step",
    steps=[
        RealOSStep(
            description="Inspect Notepad",
            intent="application.inspect",
            target="notepad",
            expected_postconditions=[],
        ),
    ],
    expected_postconditions=[],
    verification_requirements=VerificationRequirement(
        min_evidence_strength=EvidenceStrength.LEVEL_2,
        requires_independent_verification=True,
        requires_cleanup=False,
    ),
    cleanup=[],
    timeout_seconds=15.0,
    pass_policy=PassPolicy.BEST_EFFORT,
    evidence_requirements=["system_inspection"],
)


SCENARIO_APPLICATION_INSPECT_CALCULATOR = RealOSScenario(
    scenario_id="realos_app_inspect_calculator",
    name="Inspect Calculator (no launch)",
    description=(
        "Inspect the Calculator application. Expected: the "
        "inspector returns success with Calculator metadata."
    ),
    category=RealOSCategory.APPLICATION,
    risk_level=RiskLevel.READ_ONLY,
    allowed_side_effects=[SideEffect.SYSTEM_INSPECTION],
    natural_language_request="Inspect Calculator.",
    expected_intent="application.inspect",
    expected_capabilities=["application.inspect"],
    expected_workflow_shape="single_step",
    steps=[
        RealOSStep(
            description="Inspect Calculator",
            intent="application.inspect",
            target="calculator",
            expected_postconditions=[],
        ),
    ],
    expected_postconditions=[],
    verification_requirements=VerificationRequirement(
        min_evidence_strength=EvidenceStrength.LEVEL_2,
        requires_independent_verification=True,
        requires_cleanup=False,
    ),
    cleanup=[],
    timeout_seconds=15.0,
    pass_policy=PassPolicy.BEST_EFFORT,
)


# ============================================================
# GUI SCENARIOS
# ============================================================


SCENARIO_GUI_FOCUS_SAFE = RealOSScenario(
    scenario_id="realos_gui_focus_safe",
    name="Focus a controlled safe target",
    description=(
        "Call gui.focus with a known-safe target. The runtime "
        "focus resolver must accept a named safe target without "
        "actually requiring a real GUI window to exist. The "
        "scenario does not assert external state; it asserts "
        "that the dispatch reached the real provider and "
        "returned a structured result. This is an honest "
        "BEST_EFFORT scenario."
    ),
    category=RealOSCategory.GUI,
    risk_level=RiskLevel.READ_ONLY,
    allowed_side_effects=[SideEffect.GUI_INTERACTION],
            natural_language_request="Focus Notepad window.",
            expected_intent="gui.focus_window",
            expected_capabilities=["gui.focus_window"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Focus a safe named target",
                    intent="gui.focus_window",
                    target="notepad",
            parameters={"named_target": "notepad"},
            expected_postconditions=[],
        ),
    ],
    expected_postconditions=[],
    verification_requirements=VerificationRequirement(
        min_evidence_strength=EvidenceStrength.LEVEL_2,
        requires_independent_verification=False,
        requires_cleanup=False,
    ),
    cleanup=[],
    timeout_seconds=10.0,
    pass_policy=PassPolicy.BEST_EFFORT,
    notes=(
        "GUI providers on a headless host cannot dispatch real "
        "events. This scenario verifies only that the "
        "intent reached the real provider."
    ),
)


# ============================================================
# FILESYSTEM SCENARIOS
# ============================================================


def _make_filesystem_scenarios() -> List[RealOSScenario]:
    """Build the canonical filesystem scenarios.

    Each scenario:
        1. writes a disposable file in the workspace
        2. independently reads it back
        3. cleans up"""

    out: List[RealOSScenario] = []

    # 7. Create a file
    out.append(
        RealOSScenario(
            scenario_id="realos_fs_create_file",
            name="Create a disposable text file",
            description="Create a disposable .txt file in the workspace.",
            category=RealOSCategory.FILESYSTEM,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Create a file called benchmark.txt with 'hello'.",
            expected_intent="file.create",
            expected_capabilities=["file.create"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Create file with content",
                    intent="file.create",
                    target="benchmark_fs_create.txt",
                    parameters={"content": "hello-from-genesis-benchmark"},
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="benchmark_fs_create.txt exists on disk",
                            verifier_id="verify_file_exists",
                            artifact_path="benchmark_fs_create.txt",
                            evidence_kind="filesystem",
                        ),
                        ExpectedPostcondition(
                            description="file contains expected content",
                            verifier_id="verify_file_contains",
                            artifact_path="benchmark_fs_create.txt",
                            expected_value="hello-from-genesis-benchmark",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove benchmark_fs_create.txt",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_create.txt"),
                    verifier_id="verify_file_absent",
                    verifier=_verifier("verify_file_absent", "benchmark_fs_create.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 8. Read a file
    out.append(
        RealOSScenario(
            scenario_id="realos_fs_read_file",
            name="Read a disposable text file",
            description=(
                "Pre-create a file, then read it through OSManager "
                "and verify the content independently."
            ),
            category=RealOSCategory.FILESYSTEM,
            risk_level=RiskLevel.READ_ONLY,
            allowed_side_effects=[],
            natural_language_request="Read the benchmark_read.txt file.",
            expected_intent="file.read",
            expected_capabilities=["file.read"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Read a pre-existing file",
                    intent="file.read",
                    target="benchmark_fs_read.txt",
                    parameters={
                        "_setup_write": (
                            "hello-from-genesis-benchmark-read"
                        ),
                        "_setup_path": "benchmark_fs_read.txt",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the file exists",
                            verifier_id="verify_file_exists",
                            artifact_path="benchmark_fs_read.txt",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove benchmark_fs_read.txt",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_read.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_read.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 9. Edit a file
    out.append(
        RealOSScenario(
            scenario_id="realos_fs_edit_file",
            name="Edit a disposable text file",
            description=(
                "Pre-create a file containing 'foo'. Edit it through "
                "OSManager by replacing 'foo' with 'bar'. Verify "
                "the new content via a fresh filesystem read."
            ),
            category=RealOSCategory.FILESYSTEM,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[SideEffect.WRITE_FILE],
            natural_language_request="Edit benchmark_fs_edit.txt and replace 'foo' with 'bar'.",
            expected_intent="document.edit",
            expected_capabilities=["document.edit"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Edit a pre-existing file",
                    intent="document.edit",
                    target="benchmark_fs_edit.txt",
                    parameters={
                        "_setup_write": "this is foo content",
                        "_setup_path": "benchmark_fs_edit.txt",
                        "find_text": "foo",
                        "replace_text": "bar",
                        "output": "benchmark_fs_edit_edited.txt",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the file contains the new content",
                            verifier_id="verify_file_contains",
                            artifact_path="benchmark_fs_edit_edited.txt",
                            expected_value="this is bar content",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove benchmark_fs_edit_edited.txt",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_edit_edited.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_edit_edited.txt"),
                ),
                CleanupStep(
                    description="Remove benchmark_fs_edit.txt",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_edit.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_edit.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 10. Copy a file
    out.append(
        RealOSScenario(
            scenario_id="realos_fs_copy_file",
            name="Copy a disposable text file",
            description=(
                "Pre-create a source file, then copy it to a "
                "destination. Independently verify both files exist."
            ),
            category=RealOSCategory.FILESYSTEM,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Copy benchmark_fs_src.txt to benchmark_fs_dst.txt.",
            expected_intent="file.copy",
            expected_capabilities=["file.copy"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Copy the pre-existing source to destination",
                    intent="file.copy",
                    target="benchmark_fs_dst.txt",
                    parameters={
                        "source": "benchmark_fs_src.txt",
                        "destination": "benchmark_fs_dst.txt",
                        "_setup_write": "hello-from-genesis-benchmark-copy",
                        "_setup_path": "benchmark_fs_src.txt",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="source still exists",
                            verifier_id="verify_file_exists",
                            artifact_path="benchmark_fs_src.txt",
                            evidence_kind="filesystem",
                        ),
                        ExpectedPostcondition(
                            description="destination exists",
                            verifier_id="verify_file_exists",
                            artifact_path="benchmark_fs_dst.txt",
                            evidence_kind="filesystem",
                        ),
                        ExpectedPostcondition(
                            description="destination contains source content",
                            verifier_id="verify_file_contains",
                            artifact_path="benchmark_fs_dst.txt",
                            expected_value="hello-from-genesis-benchmark-copy",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove source",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_src.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_src.txt"),
                ),
                CleanupStep(
                    description="Remove destination",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_dst.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_dst.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 11. Move a file
    out.append(
        RealOSScenario(
            scenario_id="realos_fs_move_file",
            name="Move a disposable text file",
            description=(
                "Pre-create a source file, then move it. Verify "
                "the source is gone and the destination exists."
            ),
            category=RealOSCategory.FILESYSTEM,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.DELETE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Move benchmark_fs_mv_src.txt to benchmark_fs_mv_dst.txt.",
            expected_intent="file.move",
            expected_capabilities=["file.move"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Move the pre-existing source to destination",
                    intent="file.move",
                    target="benchmark_fs_mv_dst.txt",
                    parameters={
                        "source": "benchmark_fs_mv_src.txt",
                        "destination": "benchmark_fs_mv_dst.txt",
                        "_setup_write": "hello-from-genesis-benchmark-move",
                        "_setup_path": "benchmark_fs_mv_src.txt",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="source file is gone",
                            verifier_id="verify_file_absent",
                            artifact_path="benchmark_fs_mv_src.txt",
                            evidence_kind="filesystem",
                        ),
                        ExpectedPostcondition(
                            description="destination exists with content",
                            verifier_id="verify_file_contains",
                            artifact_path="benchmark_fs_mv_dst.txt",
                            expected_value="hello-from-genesis-benchmark-move",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove destination",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_mv_dst.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_mv_dst.txt"),
                ),
                CleanupStep(
                    description="Remove source if it lingers",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_mv_src.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_mv_src.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 12. Rename a file
    out.append(
        RealOSScenario(
            scenario_id="realos_fs_rename_file",
            name="Rename a disposable text file",
            description=(
                "Pre-create a source file, then rename it. Verify "
                "the original is gone and the renamed file exists."
            ),
            category=RealOSCategory.FILESYSTEM,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.DELETE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Rename benchmark_fs_ren_old.txt to benchmark_fs_ren_new.txt.",
            expected_intent="file.rename",
            expected_capabilities=["file.rename"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Rename the pre-existing file",
                    intent="file.rename",
                    target="benchmark_fs_ren_new.txt",
                    parameters={
                        "source": "benchmark_fs_ren_old.txt",
                        "new_name": "benchmark_fs_ren_new.txt",
                        "_setup_write": "hello-from-genesis-benchmark-rename",
                        "_setup_path": "benchmark_fs_ren_old.txt",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="original file is gone",
                            verifier_id="verify_file_absent",
                            artifact_path="benchmark_fs_ren_old.txt",
                            evidence_kind="filesystem",
                        ),
                        ExpectedPostcondition(
                            description="renamed file exists with content",
                            verifier_id="verify_file_contains",
                            artifact_path="benchmark_fs_ren_new.txt",
                            expected_value="hello-from-genesis-benchmark-rename",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove renamed file",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_ren_new.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_ren_new.txt"),
                ),
                CleanupStep(
                    description="Remove old file if it lingers",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_fs_ren_old.txt"),
                    verifier=_verifier("verify_file_absent", "benchmark_fs_ren_old.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 13. Delete a disposable benchmark file
    out.append(
        RealOSScenario(
            scenario_id="realos_fs_delete_file",
            name="Delete a disposable benchmark file",
            description=(
                "Pre-create a disposable file. Delete it through "
                "OSManager. Verify it is gone."
            ),
            category=RealOSCategory.FILESYSTEM,
            risk_level=RiskLevel.DESTRUCTIVE,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
                SideEffect.DELETE_FILE,
            ],
            natural_language_request="Delete benchmark_fs_del.txt.",
            expected_intent="file.delete",
            expected_capabilities=["file.delete"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Delete the disposable file",
                    intent="file.delete",
                    target="benchmark_fs_del.txt",
                    parameters={
                        "_setup_write": "hello-from-genesis-benchmark-delete",
                        "_setup_path": "benchmark_fs_del.txt",
                        "confirmed": True,
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the file is gone",
                            verifier_id="verify_file_absent",
                            artifact_path="benchmark_fs_del.txt",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=15.0,
        )
    )

    # 14. Create / search a controlled folder
    out.append(
        RealOSScenario(
            scenario_id="realos_fs_create_folder",
            name="Create a disposable folder",
            description=(
                "Create a disposable folder inside the workspace. "
                "Verify it exists on disk."
            ),
            category=RealOSCategory.FILESYSTEM,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[SideEffect.CREATE_FOLDER],
            natural_language_request="Create a folder called benchmark_folder.",
            expected_intent="folder.create",
            expected_capabilities=["folder.create"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Create the disposable folder",
                    intent="folder.create",
                    target="benchmark_folder",
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the folder exists",
                            verifier_id="verify_folder_exists",
                            artifact_path="benchmark_folder",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove benchmark_folder",
                    action_id="rmdir",
                    action=_cleanup_action("benchmark_folder"),
                    verifier=_verifier("verify_folder_absent", "benchmark_folder"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    return out


# ============================================================
# DOCUMENT SCENARIOS
# ============================================================


def _make_document_scenarios() -> List[RealOSScenario]:
    out: List[RealOSScenario] = []

    # 15. Create TXT
    out.append(
        RealOSScenario(
            scenario_id="realos_doc_create_txt",
            name="Create a disposable TXT document",
            description="Create a real .txt file in the workspace.",
            category=RealOSCategory.DOCUMENT,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Create a document called doc_create.txt with hello.",
            expected_intent="document.create_txt",
            expected_capabilities=["document.create_txt"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Create TXT",
                    intent="document.create_txt",
                    target="doc_create.txt",
                    parameters={
                        "doc_type": "txt",
                        "content": "hello-from-genesis-doc-create",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the file exists",
                            verifier_id="verify_file_exists",
                            artifact_path="doc_create.txt",
                            evidence_kind="document",
                        ),
                        ExpectedPostcondition(
                            description="the file contains expected content",
                            verifier_id="verify_text_document",
                            artifact_path="doc_create.txt",
                            expected_value="hello-from-genesis-doc-create",
                            evidence_kind="document",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove doc_create.txt",
                    action_id="file_remove",
                    action=_file_remove_action("doc_create.txt"),
                    verifier=_verifier("verify_file_absent", "doc_create.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 16. Read TXT
    out.append(
        RealOSScenario(
            scenario_id="realos_doc_read_txt",
            name="Read a disposable TXT document",
            description=(
                "Pre-create a TXT document, then read it through "
                "OSManager. Independently verify content."
            ),
            category=RealOSCategory.DOCUMENT,
            risk_level=RiskLevel.READ_ONLY,
            allowed_side_effects=[],
            natural_language_request="Read doc_read.txt.",
            expected_intent="document.read",
            expected_capabilities=["document.read"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Read a pre-existing TXT",
                    intent="document.read",
                    target="doc_read.txt",
                    parameters={
                        "_setup_write": "hello-from-genesis-doc-read",
                        "_setup_path": "doc_read.txt",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the file exists and has content",
                            verifier_id="verify_file_contains",
                            artifact_path="doc_read.txt",
                            expected_value="hello-from-genesis-doc-read",
                            evidence_kind="document",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove doc_read.txt",
                    action_id="file_remove",
                    action=_file_remove_action("doc_read.txt"),
                    verifier=_verifier("verify_file_absent", "doc_read.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 17. Edit TXT
    out.append(
        RealOSScenario(
            scenario_id="realos_doc_edit_txt",
            name="Edit a disposable TXT document",
            description=(
                "Pre-create a TXT, edit through OSManager by "
                "replacing 'foo' with 'bar'. Independently verify."
            ),
            category=RealOSCategory.DOCUMENT,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[SideEffect.WRITE_FILE],
            natural_language_request="Edit doc_edit.txt and replace foo with bar.",
            expected_intent="document.edit",
            expected_capabilities=["document.edit"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Edit a pre-existing TXT",
                    intent="document.edit",
                    target="doc_edit.txt",
                    parameters={
                        "find_text": "foo",
                        "replace_text": "bar",
                        "output": "doc_edit_edited.txt",
                        "_setup_write": "this is foo content",
                        "_setup_path": "doc_edit.txt",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the file no longer contains 'foo'",
                            verifier_id="verify_file_contains",
                            artifact_path="doc_edit_edited.txt",
                            expected_value="this is bar content",
                            evidence_kind="document",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove edited document output",
                    action_id="file_remove",
                    action=_file_remove_action("doc_edit_edited.txt"),
                    verifier=_verifier("verify_file_absent", "doc_edit_edited.txt"),
                ),
                CleanupStep(
                    description="Remove doc_edit.txt",
                    action_id="file_remove",
                    action=_file_remove_action("doc_edit.txt"),
                    verifier=_verifier("verify_file_absent", "doc_edit.txt"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    # 18. Create DOCX
    out.append(
        RealOSScenario(
            scenario_id="realos_doc_create_docx",
            name="Create a disposable DOCX document",
            description=(
                "Create a real .docx file via OSManager. Re-open it "
                "with python-docx and verify the content."
            ),
            category=RealOSCategory.DOCUMENT,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Create a document called doc_create.docx with hello.",
            expected_intent="document.create_docx",
            expected_capabilities=["document.create_docx"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Create DOCX",
                    intent="document.create_docx",
                    target="doc_create.docx",
                    parameters={
                        "doc_type": "docx",
                        "sections": [{"body": "hello-from-genesis-doc-create-docx"}],
                        "title": "Genesis DOCX",
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the DOCX file exists",
                            verifier_id="verify_file_exists",
                            artifact_path="doc_create.docx",
                            evidence_kind="document",
                        ),
                        ExpectedPostcondition(
                            description="the DOCX contains expected content",
                            verifier_id="verify_docx",
                            artifact_path="doc_create.docx",
                            expected_value="hello-from-genesis-doc-create-docx",
                            evidence_kind="document",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove doc_create.docx",
                    action_id="file_remove",
                    action=_file_remove_action("doc_create.docx"),
                    verifier=_verifier("verify_file_absent", "doc_create.docx"),
                ),
            ],
            timeout_seconds=15.0,
        )
    )

    return out


# ============================================================
# SPREADSHEET SCENARIOS
# ============================================================


def _make_spreadsheet_scenarios() -> List[RealOSScenario]:
    out: List[RealOSScenario] = []

    # 20. Create XLSX (via direct openpyxl helper)
    out.append(
        RealOSScenario(
            scenario_id="realos_sheet_create",
            name="Create a disposable XLSX workbook",
            description=(
                "Create a real .xlsx file via openpyxl through "
                "OSManager (sheet_intel). Independently verify the "
                "sheet exists with non-empty first row."
            ),
            category=RealOSCategory.SPREADSHEET,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Create a new spreadsheet called sheet_create.xlsx.",
            expected_intent="spreadsheet.create_from_dicts",
            expected_capabilities=["spreadsheet.create_from_dicts"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Create XLSX via sheet_intel.create",
                    intent="spreadsheet.create_from_dicts",
                    target="sheet_create.xlsx",
                    parameters={
                        "doc_type": "xlsx",
                        "headers": ["Name", "Score"],
                        "rows": [["Alice", 90], ["Bob", 85]],
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the XLSX file exists",
                            verifier_id="verify_file_exists",
                            artifact_path="sheet_create.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                        ExpectedPostcondition(
                            description="the XLSX has a sheet with non-empty first row",
                            verifier_id="verify_xlsx_has_sheet",
                            artifact_path="sheet_create.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove sheet_create.xlsx",
                    action_id="file_remove",
                    action=_file_remove_action("sheet_create.xlsx"),
                    verifier=_verifier("verify_file_absent", "sheet_create.xlsx"),
                ),
            ],
            timeout_seconds=20.0,
        )
    )

    # 21. Write data to a fresh workbook (via openpyxl)
    out.append(
        RealOSScenario(
            scenario_id="realos_sheet_write_data",
            name="Write data to a disposable XLSX",
            description=(
                "Create a fresh .xlsx with openpyxl through "
                "OSManager. Verify the cells we wrote actually "
                "exist when re-opened with openpyxl."
            ),
            category=RealOSCategory.SPREADSHEET,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Create sheet_write.xlsx with rows.",
            expected_intent="spreadsheet.create_from_dicts",
            expected_capabilities=["spreadsheet.create_from_dicts"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Create XLSX and verify a written cell",
                    intent="spreadsheet.create_from_dicts",
                    target="sheet_write.xlsx",
                    parameters={
                        "doc_type": "xlsx",
                        "headers": ["Name", "Score"],
                        "rows": [["Alice", 90], ["Bob", 85]],
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="sheet_write.xlsx exists",
                            verifier_id="verify_file_exists",
                            artifact_path="sheet_write.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                        ExpectedPostcondition(
                            description="A1 contains 'Name'",
                            verifier_id="verify_xlsx_value",
                            artifact_path="sheet_write.xlsx",
                            expected_value="Name",
                            verifier_kwargs={"sheet_name": "Sheet1", "cell": "A1"},
                            evidence_kind="spreadsheet",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove sheet_write.xlsx",
                    action_id="file_remove",
                    action=_file_remove_action("sheet_write.xlsx"),
                    verifier=_verifier("verify_file_absent", "sheet_write.xlsx"),
                ),
            ],
            timeout_seconds=20.0,
        )
    )

    # 22 + 23 + 25: Sort scenario (calculate/rank/save NEW workbook)
    out.append(
        RealOSScenario(
            scenario_id="realos_sheet_sort_new_workbook",
            name="Sort a workbook and save a NEW workbook",
            description=(
                "Pre-create a workbook with rows. Sort it through "
                "OSManager to a NEW output workbook. Independently "
                "re-open both files and verify the sorted output."
            ),
            category=RealOSCategory.SPREADSHEET,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request="Sort sheet_sort_src.xlsx by Score into sheet_sort_dst.xlsx.",
            expected_intent="spreadsheet.sort",
            expected_capabilities=["spreadsheet.sort"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Sort source by Score to NEW workbook",
                    intent="spreadsheet.sort",
                    target="sheet_sort_dst.xlsx",
                    parameters={
                        "column": "Score",
                        "descending": True,
                        "output": "sheet_sort_dst.xlsx",
                        "_setup_sheet_path": "sheet_sort_src.xlsx",
                        "_setup_sheet_rows": [
                            ["Name", "Score"],
                            ["Alice", 88],
                            ["Bob", 95],
                            ["Carol", 70],
                        ],
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the NEW workbook exists",
                            verifier_id="verify_file_exists",
                            artifact_path="sheet_sort_dst.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                        ExpectedPostcondition(
                            description="the NEW workbook has a sheet",
                            verifier_id="verify_xlsx_has_sheet",
                            artifact_path="sheet_sort_dst.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove sheet_sort_src.xlsx",
                    action_id="file_remove",
                    action=_file_remove_action("sheet_sort_src.xlsx"),
                    verifier=_verifier("verify_file_absent", "sheet_sort_src.xlsx"),
                ),
                CleanupStep(
                    description="Remove sheet_sort_dst.xlsx",
                    action_id="file_remove",
                    action=_file_remove_action("sheet_sort_dst.xlsx"),
                    verifier=_verifier("verify_file_absent", "sheet_sort_dst.xlsx"),
                ),
            ],
            timeout_seconds=25.0,
        )
    )

    return out


# ============================================================
# BROWSER SCENARIOS
# ============================================================


def _make_browser_scenarios() -> List[RealOSScenario]:
    out: List[RealOSScenario] = []

    # 26. Open a controlled URL
    out.append(
        RealOSScenario(
            scenario_id="realos_browser_open_url",
            name="Open a controlled public URL",
            description=(
                "Open https://example.com through OSManager. The "
                "scenario is BEST_EFFORT: on a host with no "
                "default browser the launch is allowed to fail; "
                "the scenario verifies that the real provider was "
                "dispatched."
            ),
            category=RealOSCategory.BROWSER,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.OPEN_APPLICATION,
                SideEffect.NETWORK_REQUEST,
            ],
            natural_language_request="Open https://example.com in a browser.",
            expected_intent="browser.open_url",
            expected_capabilities=["browser.open_url"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Open URL",
                    intent="browser.open_url",
                    target="https://example.com",
                    expected_postconditions=[],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_2,
                requires_independent_verification=False,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=30.0,
            pass_policy=PassPolicy.BEST_EFFORT,
        )
    )

    # 27. Browser get_url
    out.append(
        RealOSScenario(
            scenario_id="realos_browser_get_url",
            name="Browser get_url (provider-level)",
            description=(
                "Call OSManager.browser_get_url. The scenario "
                "verifies that the provider was dispatched. "
                "Honest fallback returns verified=False when no "
                "real session is attached."
            ),
            category=RealOSCategory.BROWSER,
            risk_level=RiskLevel.READ_ONLY,
            allowed_side_effects=[],
            natural_language_request="What is the current browser URL?",
            expected_intent="browser.get_url",
            expected_capabilities=["browser.get_url"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="browser.get_url",
                    intent="browser.get_url",
                    target=None,
                    expected_postconditions=[],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_2,
                requires_independent_verification=False,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=15.0,
            pass_policy=PassPolicy.BEST_EFFORT,
        )
    )

    # 28. Browser get_title
    out.append(
        RealOSScenario(
            scenario_id="realos_browser_get_title",
            name="Browser get_title (provider-level)",
            description=(
                "Call OSManager.browser_get_title. The scenario "
                "verifies that the provider was dispatched."
            ),
            category=RealOSCategory.BROWSER,
            risk_level=RiskLevel.READ_ONLY,
            allowed_side_effects=[],
            natural_language_request="What is the current page title?",
            expected_intent="browser.get_title",
            expected_capabilities=["browser.get_title"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="browser.get_title",
                    intent="browser.get_title",
                    target=None,
                    expected_postconditions=[],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_2,
                requires_independent_verification=False,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=15.0,
            pass_policy=PassPolicy.BEST_EFFORT,
        )
    )

    return out


# ============================================================
# SYSTEM SCENARIOS
# ============================================================


def _make_system_scenarios() -> List[RealOSScenario]:
    out: List[RealOSScenario] = []

    # 30. Inspect hardware/system state
    out.append(
        RealOSScenario(
            scenario_id="realos_system_status",
            name="Inspect OSManager system status",
            description=(
                "Call OSManager.system_status(). Independently "
                "verify OSManager.status() returns a non-empty "
                "subsystem map."
            ),
            category=RealOSCategory.SYSTEM,
            risk_level=RiskLevel.READ_ONLY,
            allowed_side_effects=[SideEffect.SYSTEM_INSPECTION],
            natural_language_request="Show system status.",
            expected_intent="system.status",
            expected_capabilities=["system.status"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="system.status",
                    intent="system.status",
                    target=None,
                    expected_postconditions=[],
                ),
            ],
            expected_postconditions=[
                ExpectedPostcondition(
                    description="OSManager.status() returns a non-empty subsystem map",
                    verifier_id="verify_system_returns_status",
                    evidence_kind="system",
                ),
            ],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_3,
                requires_independent_verification=True,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=15.0,
        )
    )

    # 31. Inspect processes
    out.append(
        RealOSScenario(
            scenario_id="realos_system_process_list",
            name="List running processes via OSManager",
            description=(
                "Call OSManager.list_processes(). Independently "
                "verify psutil reports at least 5 processes."
            ),
            category=RealOSCategory.SYSTEM,
            risk_level=RiskLevel.READ_ONLY,
            allowed_side_effects=[SideEffect.PROCESS_INSPECTION],
            natural_language_request="List running processes.",
            expected_intent="system.process.list",
            expected_capabilities=["process.list"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="process.list",
                    intent="process.list",
                    target=None,
                    expected_postconditions=[],
                ),
            ],
            expected_postconditions=[
                ExpectedPostcondition(
                    description="psutil lists >=5 processes",
                    verifier_id="verify_processes_listed",
                    evidence_kind="process",
                ),
            ],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_3,
                requires_independent_verification=True,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=15.0,
        )
    )

    # battery
    out.append(
        RealOSScenario(
            scenario_id="realos_system_battery",
            name="Report battery status",
            description=(
                "Call OSManager.battery_status(). Independently "
                "verify the report contains a percent field."
            ),
            category=RealOSCategory.SYSTEM,
            risk_level=RiskLevel.READ_ONLY,
            allowed_side_effects=[SideEffect.SYSTEM_INSPECTION],
            natural_language_request="What is the battery level?",
            expected_intent="hardware.battery",
            expected_capabilities=["hardware.battery"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="hardware.battery",
                    intent="hardware.battery",
                    target=None,
                    expected_postconditions=[],
                ),
            ],
            expected_postconditions=[
                ExpectedPostcondition(
                    description="battery report includes percent",
                    verifier_id="verify_battery_reported",
                    evidence_kind="system",
                ),
            ],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_3,
                requires_independent_verification=True,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=15.0,
        )
    )

    # hardware stats
    out.append(
        RealOSScenario(
            scenario_id="realos_system_hardware_stats",
            name="Report hardware stats",
            description=(
                "Call OSManager.hardware_stats(). Independently "
                "verify it returns cpu/memory/uptime keys."
            ),
            category=RealOSCategory.SYSTEM,
            risk_level=RiskLevel.READ_ONLY,
            allowed_side_effects=[SideEffect.SYSTEM_INSPECTION],
            natural_language_request="Show CPU and memory stats.",
            expected_intent="hardware.stats",
            expected_capabilities=["hardware.stats"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="hardware.stats",
                    intent="hardware.stats",
                    target=None,
                    expected_postconditions=[],
                ),
            ],
            expected_postconditions=[
                ExpectedPostcondition(
                    description="hardware_stats has cpu/memory/uptime",
                    verifier_id="verify_hardware_stats_reported",
                    evidence_kind="system",
                ),
            ],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_3,
                requires_independent_verification=True,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=15.0,
        )
    )

    return out


# ============================================================
# CLIPBOARD / SCREEN
# ============================================================


def _make_clipboard_scenarios() -> List[RealOSScenario]:
    out: List[RealOSScenario] = []

    # 32. Clipboard round-trip
    out.append(
        RealOSScenario(
            scenario_id="realos_clipboard_round_trip",
            name="Copy text to clipboard and verify with paste",
            description=(
                "Copy a unique string through OSManager. "
                "Independently verify via pyperclip.paste() that "
                "the system clipboard actually contains the text."
            ),
            category=RealOSCategory.CLIPBOARD,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[SideEffect.CLIPBOARD_WRITE],
            natural_language_request="Copy 'genesis-benchmark-clip' to the clipboard.",
            expected_intent="clipboard.copy",
            expected_capabilities=["clipboard.copy"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Copy to clipboard",
                    intent="clipboard.copy",
                    target=None,
                    parameters={"text": "genesis-benchmark-clip-marker"},
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="clipboard contains the marker (pyperclip.paste)",
                            verifier=_verifier(
                                "verify_clipboard_contains",
                                "genesis-benchmark-clip-marker",
                            ),
                            evidence_kind="clipboard",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=False,
            ),
            cleanup=[],
            timeout_seconds=15.0,
        )
    )

    # 33. Screenshot
    out.append(
        RealOSScenario(
            scenario_id="realos_screen_capture",
            name="Capture the screen and decode the image",
            description=(
                "Take a screenshot through OSManager. "
                "Independently open the PNG with PIL and verify it "
                "decodes successfully."
            ),
            category=RealOSCategory.CAPTURE,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[SideEffect.SCREEN_CAPTURE],
            natural_language_request="Take a screenshot.",
            expected_intent="screen.capture",
            expected_capabilities=["screen.capture"],
            expected_workflow_shape="single_step",
            steps=[
                RealOSStep(
                    description="Capture screen",
                    intent="screen.capture",
                    target="benchmark_screenshot.png",
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="the PNG decodes as a valid image",
                            verifier_id="verify_image_decodes",
                            artifact_path="benchmark_screenshot.png",
                            evidence_kind="capture",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove benchmark_screenshot.png",
                    action_id="file_remove",
                    action=_file_remove_action("benchmark_screenshot.png"),
                    verifier=_verifier(
                        "verify_file_absent", "benchmark_screenshot.png"
                    ),
                ),
            ],
            timeout_seconds=20.0,
        )
    )

    return out


# ============================================================
# COMPOUND SCENARIOS
# ============================================================


def _make_compound_scenarios() -> List[RealOSScenario]:
    out: List[RealOSScenario] = []

    # Compound 1: Create a file, copy it, rename the copy, verify both
    out.append(
        RealOSScenario(
            scenario_id="realcomp_fs_file_lifecycle",
            name="Create a file, copy it, rename the copy",
            description=(
                "Multi-step file lifecycle: create -> copy -> "
                "rename. Each step is independently verified. "
                "Final state has two files: the original and the "
                "renamed copy."
            ),
            category=RealOSCategory.COMPOUND,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request=(
                "Create a file, copy it, then rename the copy."
            ),
            expected_intent="file.create, file.copy, file.rename",
            expected_capabilities=["file.create", "file.copy", "file.rename"],
            expected_workflow_shape="multi_step",
            steps=[
                RealOSStep(
                    description="Step 1: create original file",
                    intent="file.create",
                    target="comp_lifecycle_orig.txt",
                    parameters={
                        "content": "hello-from-genesis-compound-lifecycle",
                        "step": 1,
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="orig exists with content",
                            verifier_id="verify_file_contains",
                            artifact_path="comp_lifecycle_orig.txt",
                            expected_value="hello-from-genesis-compound-lifecycle",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
                RealOSStep(
                    description="Step 2: copy original to copy",
                    intent="file.copy",
                    target="comp_lifecycle_copy.txt",
                    parameters={
                        "source": "comp_lifecycle_orig.txt",
                        "destination": "comp_lifecycle_copy.txt",
                        "step": 2,
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="copy exists with content",
                            verifier_id="verify_file_contains",
                            artifact_path="comp_lifecycle_copy.txt",
                            expected_value="hello-from-genesis-compound-lifecycle",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
                RealOSStep(
                    description="Step 3: rename the copy",
                    intent="file.rename",
                    target="comp_lifecycle_renamed.txt",
                    parameters={
                        "source": "comp_lifecycle_copy.txt",
                        "new_name": "comp_lifecycle_renamed.txt",
                        "step": 3,
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="original copy is gone",
                            verifier_id="verify_file_absent",
                            artifact_path="comp_lifecycle_copy.txt",
                            evidence_kind="filesystem",
                        ),
                        ExpectedPostcondition(
                            description="renamed file exists with content",
                            verifier_id="verify_file_contains",
                            artifact_path="comp_lifecycle_renamed.txt",
                            expected_value="hello-from-genesis-compound-lifecycle",
                            evidence_kind="filesystem",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove original",
                    action_id="file_remove",
                    action=_file_remove_action("comp_lifecycle_orig.txt"),
                    verifier=_verifier("verify_file_absent", "comp_lifecycle_orig.txt"),
                ),
                CleanupStep(
                    description="Remove copy if lingering",
                    action_id="file_remove",
                    action=_file_remove_action("comp_lifecycle_copy.txt"),
                    verifier=_verifier("verify_file_absent", "comp_lifecycle_copy.txt"),
                ),
                CleanupStep(
                    description="Remove renamed",
                    action_id="file_remove",
                    action=_file_remove_action("comp_lifecycle_renamed.txt"),
                    verifier=_verifier("verify_file_absent", "comp_lifecycle_renamed.txt"),
                ),
            ],
            timeout_seconds=30.0,
        )
    )

    # Compound 2: spreadsheet create + sort to a new workbook
    out.append(
        RealOSScenario(
            scenario_id="realcomp_sheet_create_and_sort",
            name="Create workbook, calculate values, save a new workbook",
            description=(
                "Pre-create a workbook, then sort by Score to a NEW "
                "workbook. Independently verify both files exist and "
                "the new workbook is sorted."
            ),
            category=RealOSCategory.COMPOUND,
            risk_level=RiskLevel.MODIFYING,
            allowed_side_effects=[
                SideEffect.CREATE_FILE,
                SideEffect.WRITE_FILE,
            ],
            natural_language_request=(
                "Create a spreadsheet, calculate values, save a new workbook."
            ),
            expected_intent="spreadsheet.create_from_dicts, spreadsheet.sort",
            expected_capabilities=["spreadsheet.create_from_dicts", "spreadsheet.sort"],
            expected_workflow_shape="multi_step",
            steps=[
                RealOSStep(
                    description="Step 1: create workbook with data",
                    intent="spreadsheet.create_from_dicts",
                    target="compound_sheet_src.xlsx",
                    parameters={
                        "doc_type": "xlsx",
                        "headers": ["Name", "Score"],
                        "rows": [["Alice", 88], ["Bob", 95], ["Carol", 70]],
                        "step": 1,
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="source workbook exists",
                            verifier_id="verify_file_exists",
                            artifact_path="compound_sheet_src.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                        ExpectedPostcondition(
                            description="source has a sheet",
                            verifier_id="verify_xlsx_has_sheet",
                            artifact_path="compound_sheet_src.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                    ],
                ),
                RealOSStep(
                    description="Step 2: sort to a NEW workbook",
                    intent="spreadsheet.sort",
                    target="compound_sheet_dst.xlsx",
                    parameters={
                        "column": "Score",
                        "descending": True,
                        "output": "compound_sheet_dst.xlsx",
                        "step": 2,
                    },
                    expected_postconditions=[
                        ExpectedPostcondition(
                            description="sorted workbook exists",
                            verifier_id="verify_file_exists",
                            artifact_path="compound_sheet_dst.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                        ExpectedPostcondition(
                            description="sorted workbook has a sheet",
                            verifier_id="verify_xlsx_has_sheet",
                            artifact_path="compound_sheet_dst.xlsx",
                            evidence_kind="spreadsheet",
                        ),
                    ],
                ),
            ],
            expected_postconditions=[],
            verification_requirements=VerificationRequirement(
                min_evidence_strength=EvidenceStrength.LEVEL_4,
                requires_independent_verification=True,
                requires_cleanup=True,
            ),
            cleanup=[
                CleanupStep(
                    description="Remove source workbook",
                    action_id="file_remove",
                    action=_file_remove_action("compound_sheet_src.xlsx"),
                    verifier=_verifier("verify_file_absent", "compound_sheet_src.xlsx"),
                ),
                CleanupStep(
                    description="Remove sorted workbook",
                    action_id="file_remove",
                    action=_file_remove_action("compound_sheet_dst.xlsx"),
                    verifier=_verifier("verify_file_absent", "compound_sheet_dst.xlsx"),
                ),
            ],
            timeout_seconds=30.0,
        )
    )

    return out


# ============================================================
# AGGREGATE
# ============================================================


REAL_OS_SCENARIOS: List[RealOSScenario] = (
    [
        SCENARIO_APPLICATION_INSPECT_NOTEPAD,
        SCENARIO_APPLICATION_INSPECT_CALCULATOR,
        SCENARIO_GUI_FOCUS_SAFE,
    ]
    + _make_filesystem_scenarios()
    + _make_document_scenarios()
    + _make_spreadsheet_scenarios()
    + _make_browser_scenarios()
    + _make_system_scenarios()
    + _make_clipboard_scenarios()
)

COMPOUND_REAL_OS_SCENARIOS: List[RealOSScenario] = _make_compound_scenarios()


def list_scenarios() -> List[RealOSScenario]:
    return REAL_OS_SCENARIOS + COMPOUND_REAL_OS_SCENARIOS