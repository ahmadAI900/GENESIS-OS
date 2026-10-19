"""Item 20B (S15): a model flag must not waive the target requirement.

THE HOLE (reproduced against the pre-fix code, fail-before red)
---------------------------------------------------------------
``ActionPlan._conditional_target_requirement`` waived the
"target is required for this operation" contract whenever
``parameters`` carried any of::

    requires_runtime_resolution / source_is_anaphoric / anaphoric_target

``parameters`` is deserialized from model-controlled JSON. So a model
payload of::

    {"operation": "file.delete", "target": null,
     "parameters": {"source_is_anaphoric": true}}

constructed a targetless plan for an operation whose contract REQUIRES
a target -- the model decided that a safety invariant did not apply to
its own payload, exactly the class of hole S14's grant forgery and
this batch's other items are about.

THE FIX
-------
The waiver reads only ``plan.runtime_resolution``, a record that
refuses direct construction and is minted only by trusted code
(``ActionPlan.from_decision``) for DETERMINISTIC-origin anaphoric
decisions. Model-origin decisions (LLM resolver, marked
``_semantic_resolution``) get no record and fail closed on the
ordinary target contract. JSON-shaped values for the field are
refused on every construction route (``__init__`` guard and a field
validator, so ``model_validate`` cannot slip past).
"""

from __future__ import annotations

import pytest

from pydantic import ValidationError as PydanticValidationError

from genesis_os.action_plan import (
    ActionPlan,
    ActionPlanValidationError,
)

MODEL_FLAGS = [
    pytest.param(
        {"requires_runtime_resolution": True},
        id="requires_runtime_resolution",
    ),
    pytest.param(
        {"source_is_anaphoric": True},
        id="source_is_anaphoric",
    ),
    pytest.param(
        {"anaphoric_target": True},
        id="anaphoric_target",
    ),
]


def _refused(exc: BaseException) -> bool:
    """The project convention (test_phase1): accept either error,
    plus the __init__ guard's TypeError -- model_validate reaches
    that guard first on this route, and both are refusals."""
    return (
        isinstance(exc, ActionPlanValidationError)
        or isinstance(exc, PydanticValidationError)
        or isinstance(exc, TypeError)
    )


# --------------------------------------------------------------------------
# 1. The model flag, by itself, waives nothing (fail-before red)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("flag", MODEL_FLAGS)
def test_a_model_flag_on_a_targetless_target_required_plan_is_refused(flag):
    """The hole: the flag lived in model-reachable parameters."""
    with pytest.raises(Exception) as exc_info:
        ActionPlan(
            operation="file.delete",
            target=None,
            parameters=dict(flag),
        )

    assert _refused(exc_info.value), (
        f"a targetless file.delete constructed because parameters "
        f"carried {flag!r}; a model-supplied key waived the target "
        "requirement"
    )


def test_from_decision_model_origin_gets_no_waiver():
    """`_semantic_resolution` marks LLM-resolver output. No record."""
    with pytest.raises(Exception) as exc_info:
        ActionPlan.from_decision(
            {
                "level": 3,
                "mode": "os",
                "operation": "file.delete",
                "target": "",
                "parameters": {
                    "source_is_anaphoric": True,
                    "requires_runtime_resolution": True,
                    "_semantic_resolution": True,
                },
            }
        )

    assert _refused(exc_info.value), (
        "an LLM-origin decision waived the target requirement with "
        "its own flagged parameters"
    )


# --------------------------------------------------------------------------
# 2. The trusted channel exists and is what waives (fail-before red:
#    the field did not exist / forged values took the wrong path)
# --------------------------------------------------------------------------


def test_deterministic_anaphoric_decision_still_constructs():
    """The legitimate flow must keep working -- with a real record."""
    plan = ActionPlan.from_decision(
        {
            "level": 3,
            "mode": "os",
            "operation": "file.open",
            "target": "",
            "parameters": {
                "source_is_anaphoric": True,
                "requires_runtime_resolution": True,
            },
        }
    )

    assert plan.target is None
    record = getattr(plan, "runtime_resolution", None)
    assert record is not None, (
        "a deterministic-origin anaphoric plan must carry the trusted "
        "runtime-resolution record that now performs the waiver"
    )
    assert record.operation == "file.open", (
        "the record must be bound to the plan's own operation"
    )


def test_json_shaped_waiver_is_refused_on_the_keyword_path():
    """dict/str/bool for the field is the S15 forgery shape."""
    with pytest.raises(TypeError, match="runtime_resolution"):
        ActionPlan(
            operation="file.delete",
            target=None,
            parameters={"source_is_anaphoric": True},
            runtime_resolution={"requires_runtime_resolution": True},
        )


def test_json_shaped_waiver_is_refused_on_the_model_validate_path():
    """model_validate bypasses __init__, so the field validator holds
    the same line (fail-before: rejected only as an extra key)."""
    with pytest.raises(Exception) as exc_info:
        ActionPlan.model_validate(
            {
                "operation": "file.delete",
                "target": None,
                "parameters": {"source_is_anaphoric": True},
                "runtime_resolution": True,
            }
        )

    assert _refused(exc_info.value)
    assert "RuntimeResolutionRecord" in str(exc_info.value), (
        "the model_validate route accepted a non-record waiver (or "
        "refused it only as an unknown key, which extra='forbid' "
        "would mask)"
    )


def test_a_waiver_built_for_one_operation_cannot_waive_another():
    from genesis_os.runtime_resolution import (
        issue_runtime_resolution_record,
    )

    record = issue_runtime_resolution_record(operation="file.rename")
    with pytest.raises(Exception) as exc_info:
        ActionPlan(
            operation="file.delete",
            target=None,
            parameters={"source_is_anaphoric": True},
            runtime_resolution=record,
        )

    assert _refused(exc_info.value)
    assert "target is required" in str(exc_info.value), (
        "a record minted for file.rename waived the target "
        "requirement for a file.delete plan"
    )


def test_direct_construction_of_the_record_is_refused():
    from genesis_os.runtime_resolution import (
        RuntimeResolutionError,
        RuntimeResolutionRecord,
    )

    with pytest.raises(RuntimeResolutionError):
        RuntimeResolutionRecord(operation="file.delete")


# --------------------------------------------------------------------------
# 3. Controls: shapes the fix must NOT break (green before and after)
# --------------------------------------------------------------------------


def test_targetless_operations_still_need_no_waiver():
    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "Hello from Genesis"},
    )

    assert plan.target is None


def test_a_plan_with_a_target_is_unaffected_by_the_flags():
    plan = ActionPlan.from_decision(
        {
            "level": 3,
            "mode": "os",
            "operation": "document.read",
            "target": "C:/Users/me/report.pdf",
            "parameters": {
                "anaphoric_target": True,
                "_semantic_resolution": True,
            },
        }
    )

    assert plan.target == "C:/Users/me/report.pdf"
    assert getattr(plan, "runtime_resolution", None) is None


def test_targetless_file_search_needs_no_record():
    plan = ActionPlan.from_decision(
        {
            "level": 3,
            "mode": "os",
            "operation": "file.search",
            "target": "",
            "parameters": {"query": "*.txt"},
        }
    )

    assert plan.target is None
