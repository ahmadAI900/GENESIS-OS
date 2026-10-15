# Genesis OS — Phase 1 Pydantic Contract Closure

**Closure date:** 2026-09-25  
**Workspace:** `C:\Users\Muhammad\Desktop\gemini_cli`  
**Scope:** Phase 1 only: the 15 Pydantic gate contracts, their production validation boundaries, the Evidence gate correction, malformed-input rejection, and the explicit Skill ownership decision.  
**Dependency boundary:** Pydantic and the Python standard library only. No Semantic Kernel, embeddings, Agent Framework, or other Phase 2 dependency was added.  
**Status:** **CLOSED** for the Phase 1 specification.

## 1. Scope and Objectives

Phase 1 makes cross-layer state explicit without mass-converting the native dataclass runtime. The contract module is `backend/genesis_os/contracts.py`; native shapes are validated at the boundary that owns them.

The closure objectives are:

1. Keep all 15 roadmap contracts as validated Pydantic models.
2. Reject malformed structural inputs at real runtime boundaries.
3. Require capability-specific evidence before a result can be reported as verified.
4. Instantiate and serialize a real `Evidence` object at the post-execution boundary.
5. Preserve native runtime compatibility with small `from_*` adapters rather than rewriting `ActionResult` and the other dataclasses.
6. Do not pretend that a model with no runtime consumer is a runtime integration. The `Skill` model is explicitly left to Phase 10.

`ActionResult` remains the existing dataclass. No mass conversion or capability-level verification rewrite was performed.

Implementation and evidence files:

- `backend/genesis_os/contracts.py`
- `backend/genesis_os/action_executor.py`
- `backend/test_phase1_contracts_maturity.py`
- `backend/test_phase1_actionplan_pydantic_contract.py`
- `backend/test_phase0_mixed_data_flow.py`
- `backend/pytest.ini`
- This artifact: `backend/PHASE_1_PYDANTIC_CONTRACTS_2026-09-25.md`

## 2. Evidence Gate Defect and Correction

### Defect

Before this closure, `Evidence.from_result()` derived `passed` from an unconditional control value rather than from capability-specific evidence. A direct call of that adapter with `verification={"verified": True}` would therefore synthesize an Evidence object with `passed=True`. The provider control flag `verification["verified"]` was treated as a provider claim, not proof. In addition, `ActionExecutor._enforce_execution_contract()` called the semantic evidence check without instantiating and serializing an `Evidence` object at the boundary, so the result could carry no auditable evidence contract at all.

The pre-existing boolean semantic prefilter rejected the same bare `verified=True` payload before the model was reached when it was called through the production `ActionExecutor` path. That distinction is important: the old adapter was tautological and unauditable, but this specific probe was **not** an already-realized false-success through `ActionExecutor`. The final behavior closes both the direct-adapter tautology and the missing boundary instantiation.

### Correction

- `backend/genesis_os/contracts.py:333-337` adds a Pydantic model validator: an `Evidence` object with `passed=True` and empty metadata is invalid.
- `backend/genesis_os/contracts.py:347-389` now requires a mapping, requires an operation, removes the control-only `verified` key from the Evidence metadata, derives `passed` from the result's verified state, and rejects a verified claim when `has_meaningful_result_evidence()` is false.
- `backend/genesis_os/contracts.py:534-546` makes `require_result_evidence()` return the validated `Evidence` object and re-checks the capability-specific semantic predicate.
- `backend/genesis_os/action_executor.py:821-835` instantiates `EvidenceContract.from_result(result)`, validates it, and stores `result.metadata["evidence_contract"]` on success. On failure it sets `verified=False`, `status="verification_unavailable"`, `trustworthy_success=False`, and records the rejection reason.
- `backend/genesis_os/action_executor.py:2233-2333` retains the legacy `verification["verified"]` field for downstream compatibility, but the control flag is excluded from the Pydantic Evidence payload. It is never counted as capability-specific evidence.

The genuine capability-specific path requires real evidence such as `running=True` for `application.open`; a provider assertion such as `verification={"verified": True}` is not enough.

### Before and after

**Before (pre-fix source behavior):** the direct Evidence adapter synthesized `passed=True`, while the production `ActionExecutor` prefilter rejected the same payload before it could be reported as verified. The pre-fix tree was not archived as a runnable binary, so the comparison below is a deterministic replay of the pre-fix functions reconstructed from the pre-fix source and executed through the real `ActionExecutor` normalization/dispatch path. It is labeled as a replay rather than presented as an archived old-runtime capture.

**Captured pre-fix-path replay:**

```text
{"old_action_executor_result": {"dispatch_calls": 1, "rejection": "result for 'application.open' claims verified=True without capability-specific evidence", "status": "verification_unavailable", "trustworthy_success": false, "verified": false}, "old_direct_evidence_adapter": {"evidence_id": "application.open:verification", "evidence_type": "dispatch_confirmed", "metadata": {"verified": true}, "operation": "application.open", "passed": true, "reason": ""}}
```

This is the precise finding: the old direct adapter was wrong, but the old production gate did not emit a false verified result for this exact malformed input. The fix removes the adapter tautology, rejects the control flag in the model, and makes the post-execution boundary construct and serialize the real Evidence contract.

**After (real captured probe output):** the genuine result passes with `running=True`; the malformed provider claim is dispatched once but is downgraded to an untrustworthy result and never becomes verified. These lines are copied verbatim from the current probe run:

```text
GENUINE_EVIDENCE={"dispatch_calls": 1, "evidence_contract": {"actual": null, "evidence_id": "application.open:verification", "evidence_type": "file_exists", "expected": null, "metadata": {"running": true}, "operation": "application.open", "passed": true, "provider": null, "reason": "", "timestamp": null}, "status": "verified", "success": true, "trustworthy_success": true, "verified": true}
MALFORMED_EVIDENCE={"dispatch_calls": 1, "rejection": "verified result lacks capability-specific evidence", "status": "verification_unavailable", "success": true, "trustworthy_success": false, "verified": false}
```

The direct model-level rejection is covered by `backend/test_phase1_contracts_maturity.py:334-341`: `Evidence(passed=True, metadata={})` raises a validation error before it can be serialized. The direct adapter rejection is covered by `backend/test_phase1_contracts_maturity.py:343-350`.

## 3. Skill Contract Ownership

`Skill` is a real Pydantic model at `backend/genesis_os/contracts.py:95-124`, but the current production code has no Skill runtime: no registry, loader, planner, or executor consumer exists. The only current uses found by the production sweep are the model definition and Phase 1 tests.

The standalone tests are:

- `backend/test_phase1_contracts_maturity.py:352-353` — empty/blank `skill_id` is rejected.
- `backend/test_phase1_contracts_maturity.py:355-360` — a complete valid definition is accepted.
- `backend/test_phase1_contracts_maturity.py:362-371` — a complete valid definition is accepted and an empty `skill_id` is rejected in the same standalone model test.

Captured probe output:

```text
SKILL_CONTRACT={"malformed_rejection": {"message": "1 validation error for Skill\nskill_id\n  String should have at least 1 character [type=string_too_short, input_value='', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/string_too_short", "type": "ValidationError"}, "valid": {"description": "", "metadata": {}, "name": "Generate website", "parameters": [], "purpose": "", "recovery_steps": [], "required_capabilities": ["file.create"], "requires_confirmation": false, "risk_level": "low", "skill_id": "website.generate", "tags": [], "verification_steps": ["file content matches"], "version": "1.0", "workflow_pattern": "sequential"}}
```

**Decision:** the Skill model is contract-complete for standalone structural validation, but Skill runtime integration is explicitly deferred to **Phase 10**. Phase 1 does not claim a Skill registry, loader, planner, or executor. This is an ownership record, not a hidden conformance gap.

## 4. Malformed-Input Probes and Boundary Evidence

The following are real package-boundary probes, not descriptions of intended behavior. The probe used a real `ActionExecutor` and a recording OS-manager double; `dispatch_calls` is the observable dispatch count.

| Probe | Malformed input | Real boundary | Dispatch | Result |
|---|---|---|---:|---|
| Invalid `ActionPlan` | `ActionPlan(operation="unknown.operation", target="notepad")` | Pydantic `ActionPlan` construction | 0 | `ValidationError`: unknown Genesis capability |
| Missing Task field | native plan without `operation`, plus a `model_construct` malformed plan fed to `ActionExecutor.execute()` | `Task.from_action_plan()` and `ActionExecutor` type/structure gate | 0 | `ContractViolationError` at the adapter; executor returns `invalid_plan`, `executed=False` |
| Malformed Evidence | provider returns `verification={"verified": True}` with no capability signal | `ActionExecutor._enforce_execution_contract()` after dispatch | 1 | `verified=False`, `trustworthy_success=False`, `status=verification_unavailable` |

The complete captured output from the boundary probe is:

```text
GENUINE_EVIDENCE={"dispatch_calls": 1, "evidence_contract": {"actual": null, "evidence_id": "application.open:verification", "evidence_type": "file_exists", "expected": null, "metadata": {"running": true}, "operation": "application.open", "passed": true, "provider": null, "reason": "", "timestamp": null}, "status": "verified", "success": true, "trustworthy_success": true, "verified": true}
MALFORMED_EVIDENCE={"dispatch_calls": 1, "rejection": "verified result lacks capability-specific evidence", "status": "verification_unavailable", "success": true, "trustworthy_success": false, "verified": false}
MALFORMED_ACTION_PLAN={"dispatch_calls": 0, "rejection": {"message": "1 validation error for ActionPlan\noperation\n  Value error, Unknown Genesis capability: unknown.operation. [type=value_error, input_value='unknown.operation', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/value_error", "type": "ValidationError"}}
MALFORMED_TASK={"dispatch_calls": 0, "rejection": {"message": "invalid Task shape: 1 validation error for Task\noperation\n  String should have at least 1 character [type=string_too_short, input_value='', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/string_too_short", "type": "ContractViolationError"}}
SKILL_CONTRACT={"malformed_rejection": {"message": "1 validation error for Skill\nskill_id\n  String should have at least 1 character [type=string_too_short, input_value='', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/string_too_short", "type": "ValidationError"}, "valid": {"description": "", "metadata": {}, "name": "Generate website", "parameters": [], "purpose": "", "recovery_steps": [], "required_capabilities": ["file.create"], "requires_confirmation": false, "risk_level": "low", "skill_id": "website.generate", "tags": [], "verification_steps": ["file content matches"], "version": "1.0", "workflow_pattern": "sequential"}}
```

The Evidence probe dispatches once because Evidence is a post-execution contract. That is intentional. The pre-dispatch malformed ActionPlan/Task probes have zero dispatch, and the post-dispatch Evidence failure cannot produce a trustworthy verified result. The pre-fix-path replay in Section 2 confirms that the old production prefilter also rejected this exact Evidence payload; the before/after claim is therefore about the direct adapter and boundary auditability, not about claiming that this specific input was previously a false success at the executor boundary.

## 5. Complete 15-Contract Matrix

The matrix records the production validation boundary for every contract. `Adapter` means the Pydantic model has a compatibility adapter for the existing native shape; it does not mean the native dataclass was replaced.

| # | Contract | Production boundary (`file:line`) | Adapter | Phase 1 disposition |
|---:|---|---|---|---|
| 1 | Objective | `backend/genesis_os/objective_understanding.py:399,503` | `from_understanding_result` | Active boundary validation |
| 2 | Entity | `backend/genesis_os/entity_history.py:130` | `from_entry` | Active boundary validation |
| 3 | Capability | `backend/genesis_os/capability_resolver.py:212,366` | `from_descriptor` | Active boundary validation |
| 4 | Skill | No production consumer; model at `backend/genesis_os/contracts.py:95-124` | N/A — no native runtime shape | Explicit **Phase 10** deferral; standalone validation only |
| 5 | Task | `backend/genesis_os/action_executor.py:713-725` | `from_action_plan` | Active pre-dispatch validation |
| 6 | Workflow | `backend/genesis_os/workflow_engine.py:91-96` | `from_workflow_plan` | Active pre-planner validation |
| 7 | Agent | `backend/agents/agent_registry.py:12-19` | `from_runtime` | Active registration validation |
| 8 | Execution | `backend/genesis_os/action_executor.py:809-835` | `from_action_result` | Active post-execution validation |
| 9 | Observation | `backend/genesis_os/gui_observer.py:119-128` | `from_snapshot` | Active snapshot-source validation |
| 10 | Verification | `backend/genesis_os/gui_observer.py:24-33` | `from_gui_result`; `from_verdict` for verdict dicts | Active verdict validation |
| 11 | Recovery | `backend/genesis_os/recovery_engine.py:207-224` | `from_recovery_result` | Active outcome validation |
| 12 | Policy | `backend/genesis_os/execution_safety.py:100-111` | `from_safety_config` | Active first-use validation |
| 13 | Evidence | `backend/genesis_os/action_executor.py:821-835` | `from_result` | Active post-execution gate; corrected in this closure |
| 14 | Session | `backend/genesis_os/session_persistence.py:36-43` | `from_serialized` | Active pre-persist validation |
| 15 | Checkpoint | `backend/genesis_os/workflow_engine.py:497-539` | `from_step_completion` | Active in-memory checkpoint validation; durable resume remains Phase 16 |

**Matrix result: 15/15 accounted for.** Fourteen contracts have production adapters; Skill is the one explicit no-runtime deferral. No row is presented as runtime-wired without a production consumer.

## 6. Phase 0 Bridge Consistency Check

The Phase 0 mixed-objective bridge remains consistent with the Phase 1 contract boundaries:

1. `backend/genesis.py:3105-3108` routes a mixed objective through `GenesisRuntime.execute_mixed_audited(..., self.unified_executor)`.
2. `backend/genesis_os/unified_executor.py:674-696` derives the Coding Agent `file.create` target, and `:985-990` dispatches refined steps through the workflow engine.
3. `backend/genesis_os/workflow_engine.py:91-96` validates the Workflow contract before planner validation.
4. `backend/genesis_os/action_executor.py:713-725` validates the Task contract before dispatch.
5. `backend/genesis_os/action_executor.py:821-835` validates Execution and Evidence after dispatch.

No mixed path bypasses the workflow or executor contract boundary. The existing bridge regression passes:

```text
.                                                                        [100%]
1 passed, 3 warnings in 14.17s
```

Command:

```text
python -m pytest test_phase0_mixed_data_flow.py -q -p no:cacheprovider
```

This confirms the Phase 0 bridge change did not create a contract-boundary bypass. The probe uses a deterministic agent and OS-manager test double; it is bridge regression evidence, not a new claim of real OS execution.

## 7. Regression and Tool Checks

### Targeted Phase 1 contracts

Command:

```text
python -m pytest test_phase1_contracts_maturity.py test_phase1_actionplan_pydantic_contract.py test_level3_3_execution_maturity.py -q -p no:cacheprovider
```

Final result:

```text
91 passed in 8.42s
```

The contract maturity file alone reports:

```text
49 passed in 10.82s
```

### Full configured collection

Command:

```text
python -m pytest --collect-only -q -p no:cacheprovider
```

Result:

```text
2067 tests collected in 73.82s (0:01:13)
```

The configured collection still excludes the eight import-time, live, or platform-dependent files listed in `backend/pytest.ini:2-10`; they are not silently counted as passes.

### Full regression

Command:

```text
python -m pytest -q -p no:cacheprovider
```

Final result on the final tree:

```text
2067 passed, 57 warnings in 1032.26s (0:17:12)
```

There were zero failures, zero errors, and zero skipped tests in the final run. The warnings are the existing deprecation warnings from legacy imports.

An intermediate run after the first Evidence refactor produced `2064 passed, 2 failed` because removing the legacy `verification["verified"]` key broke two compatibility assertions. The key was restored for the native `ActionResult.verification` shape while remaining excluded from the Pydantic Evidence payload. The final 2067-pass run supersedes that intermediate result.

### Syntax and tooling availability

```text
python -m compileall -q .        PASS (no output)
```

The repository has no project lint/type-check configuration, and the following tools are not installed in the active environment:

```text
python -m ruff check ...        FAIL: No module named ruff
python -m mypy ...              FAIL: No module named mypy
pyright ...                     FAIL: CommandNotFoundException
```

These availability results are recorded rather than reported as clean lint or type-check results. No unavailable tool was treated as a pass.

## 8. Final Conformance and Sign-Off

### Four-row conformance table

| # | Phase 1 requirement | Verdict | Evidence |
|---:|---|---|---|
| 1 | All 15 contracts are Pydantic models with structural validation and real production boundaries, with a compatibility adapter where a native runtime exists. | **PASS** | `contracts.py`; the 15-row matrix in Section 5; 14 production adapters plus the explicit Phase 10 Skill deferral. |
| 2 | Evidence is structurally validated, capability-specific, cannot pass merely from a `verified` provider control flag, and is serialized at the post-execution boundary. | **PASS** | `contracts.py:333-389` and `action_executor.py:821-835`; the pre-fix-path comparison and genuine/malformed captured output in Section 2. |
| 3 | Malformed inputs fail closed at real boundaries, Skill is validated standalone, and the Phase 0 bridge remains consistent. | **PASS** | Section 4 probes; `test_phase1_contracts_maturity.py:334-459`; Section 6 bridge test. |
| 4 | The final regression is complete, the artifact is dated and internally consistent, and no out-of-scope dependency or mass conversion was introduced. | **PASS** | `2067 tests collected`; `2067 passed, 57 warnings`; Sections 1 and 7. |

**Conformance result: 4/4 PASS. No remaining gap within the Phase 1 specification.**

## Phase 1 — Final Sign-Off

Date: 2026-09-25  
Roadmap gate: "All 15 Phase 1 contracts are validated Pydantic models at their real runtime boundaries, malformed inputs fail closed, and capability-specific evidence is required for verified results."

Conformance table: 4/4; no remaining Phase 1 gap.  
Evidence gate: **RESOLVED** — the direct adapter no longer synthesizes `passed=True`, the control flag is ignored, the old production prefilter behavior is documented by replay, and the executor serializes a real `Evidence` object.  
Skill: **DEFERRED TO PHASE 10** — standalone model validation is complete; no Skill runtime is claimed.  
Malformed probes: **COMPLETE** — invalid ActionPlan, missing Task field, and malformed Evidence captured with dispatch counts.  
Phase 0 bridge: **CONFIRMED** — the mixed-objective bridge continues through the Workflow, Task, Execution, and Evidence boundaries.  
Full regression: **2067 passed, 57 warnings in 1032.26s (0:17:12)** on the final tree.  
Tooling: `compileall` passed; `ruff`, `mypy`, and `pyright` are unavailable in the environment.

**VERDICT: CLOSED**

If CLOSED: this verdict applies to the roadmap's Phase 1 specification only. It does not certify Phase 2 onward. The Skill runtime is explicitly owned by Phase 10, durable checkpoint resume is owned by Phase 16, and no capability-level verification fix is claimed as part of this closure.
