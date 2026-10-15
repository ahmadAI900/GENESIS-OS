# Genesis OS / UCCL â€” Full Repository Audit

**Date:** 2026-10-14
**Mode:** READ-ONLY inspection. No product code, test, config, corpus or sealed-digest file was modified.
**Auditor session:** single pass, this file written section by section as evidence was gathered.

**Evidence classes used throughout:**

| Class | Meaning |
|---|---|
| `REAL-OS` | physical machine state changed and independently checked |
| `LIVE-LLM` | a real model answered |
| `MOCKED` | a double/stub answered |
| `SIMULATED` | synthetic scenario, no real backend |
| `REPLAY` | previously recorded output re-read |
| `STATIC-READ` | code inspection only |

Anything not backed by a `file:line` I read, or by verbatim output of a command I ran, is marked `UNVERIFIED`.

---

# Executive summary

**True state in one paragraph.** The repository is a substantial, real system: 482 Python files, 177,680 lines, a genuine Windows agency layer with a capability registry, a browser stack, a document/data stack, and a security boundary that I was able to break *nothing* in. The **safety machinery is the strongest part of this codebase** - a forged grant is structurally impossible, a real `file.delete` against a real file was refused with the file verifiably intact, and the workspace boundary blocks outside-root, `..`, UNC, `.env` and product-file targets while failing closed on unparseable input. The **reliability machinery is the weakest**: capability selection is not a function of its input for anything that reaches the model, the runtime's own health report is untruthful about a permanently missing browser provider, and the suite passes in one ordering and fails in the repo's own alternate ordering. Of the roadmap's 32 phases, **1 is closed** (Phase 12, on real evidence), 16 are partial, 2 are explicitly not closed, and 13 were never started.

**Closed-phase ratio: 1 / 32 = 3.1%.**

### Top 10 risks

| # | Risk | Pointer |
|---|---|---|
| 1 | `classify()` is non-deterministic for every model-routed prompt: one sentence yielded two intents in 5 runs, and two levels across two processes | D-10, §5.2 |
| 2 | `browser_degraded` reports `False` while a provider is permanently missing and unregisterable | D-01, §7.3 |
| 3 | The suite is green only in the default ordering; `alt_order_plugin` order fails a test | D-07, §3.2 |
| 4 | Two tests named for pronoun resolution compute a result and assert nothing | D-08, §3.3 |
| 5 | `genesis.py` is **not** in the protected-paths list, so the entry point is not shielded from destructive operations | D-16, §8 C-01 |
| 6 | 13 of 32 phases have no runtime at all; `Skill` is a model with no loader | §4.1 Phase 10 |
| 7 | The mutation harness reports MISSED when the tests never ran - an instrument that cannot tell "unmeasured" from "uncovered" | D-09, §8 C-04 |
| 8 | A live `gsk_` API key and a growing runtime audit log both live inside the source tree | D-05, §2.7 |
| 9 | No pinned dependencies at all (26 entries, zero `==`) and no lockfile - the environment is not reproducible | D-03, §2.6 |
| 10 | The approval channel dynamically loads every module in `agents/` and swallows import failures, so agent loss is silent | D-02, §6.4 |

### Top 10 next actions (evidence-led, not recommendations to close anything)

1. Make capability selection deterministic, or prove and report its error rate. The Phase 3 and 24 gates are unreachable while D-10 stands. *§5.2, §4 Phase 3*
2. Fix `BrowserManager.degraded` so a provider missing because its probe timed out reports as degraded. *§7.3, D-01*
3. Run the fast gate in **both** orderings as a standing gate, and fix D-07. *§3.2*
4. Replace the sandbox mutation harness with one that distinguishes MISSED from NOT-MEASURED, then re-measure behavioural coverage honestly. *D-09*
5. Add `genesis.py` (and the rest of `backend/`) to `protected_paths()`. *§6.3, D-16*
6. Delete or correct the two vacuous tests in `test_level3_15_cross_level_integration.py`. *§3.3, D-08*
7. Measure the 5% false-positive rate the Phase 3 bar names; it does not exist in any file. *§4 Phase 3*
8. Pin dependencies and add a lockfile. *D-03*
9. Move `.env` and `genesis_os/approval_audit.jsonl` out of the source tree. *D-05*
10. Run the `live` tier once through the repo's own runner and attach the evidence - it is the single largest block of `UNVERIFIED` in this report. *§10 item 1*

---

## 1. Snapshot and identity

### 1.1 Working directory (mandatory check)

```
PS> Get-Location
C:\Users\Muhammad\Desktop\gemini_cli\backend
```

Correctly spelled `Muhammad`. A prior session's mistyped `Muthammad` path is **not** involved in this audit. Every command in this report ran with `workdir` pinned to the path above.

### 1.2 Runtime identity

| Item | Value | Command |
|---|---|---|
| Python | 3.12.10 (tags/v3.12.10:0cc8128, Apr 8 2025, MSC v.1943 64 bit AMD64) | `python -c "import sys;print(sys.version)"` |
| Interpreter | `C:\Users\Muhammad\Desktop\gemini_cli\.venv\Scripts\python.exe` | `sys.executable` |
| pytest | 8.4.2 | `python -c "import pytest;print(pytest.__version__)"` |
| venv prefix | `C:\Users\Muhammad\Desktop\gemini_cli\.venv` | `sys.prefix` |
| venv base | `C:\Program Files\Python312` | `sys.base_prefix` |
| OS | Microsoft Windows 10 Pro, 10.0.18362 | `Get-CimInstance Win32_OperatingSystem` |
| CPU | 4 logical processors | `Win32_ComputerSystem.NumberOfLogicalProcessors` |
| RAM | 11.9 GB | `Win32_ComputerSystem.TotalPhysicalMemory` |

`STATIC-READ` for OS/hardware (queried, not measured by a Genesis component).

### 1.3 Version control

**No git repository.** Command run:

```
PS> if(Test-Path .git){"git repo present"}else{"no git"}
no git
PS> git rev-parse --is-inside-work-tree
fatal: not a git repository (or any of the parent directories): .git
```

Consequence: there is no way to distinguish "never changed" from "changed and changed back". All change detection in this audit rests on SHA-256 digests taken at the start and re-verified at the end (Â§12).

### 1.4 File and line census

Excluding `.venv`, `__pycache__`, `.git`, `.pytest_cache`, `node_modules`.
Command: `python C:\Users\...\audit\s01_snapshot.py`

| Extension | Files | Lines |
|---|---|---|
| `.py` | 482 | 177,680 |
| `.json` | 52 | 82,148 |
| `.txt` | 46 | 4,519 |
| `.md` | 41 | 12,106 |
| `.html` | 3 | 403 |
| `.sh` | 3 | 3 |
| (no extension) | 2 | 17 |
| `.log` | 2 | 324 |
| `.jsonl` | 1 | 1,954 |
| `.ini` | 1 | 38 |
| **TOTAL** | **633** | **279,192** |

`.py` is 63.6% of all lines. Note: a PowerShell count that did *not* exclude `.pytest_cache` reported 42 `.md` and 638 total files; the difference is cache markdown, not product content.

### 1.5 Python files by location

| Location | Files | Lines |
|---|---|---|
| repo root (`test_*.py` + scripts) | 229 | 63,572 |
| `genesis_os/` | 135 | 80,263 |
| `tools/` | 32 | 7,999 |
| `agents/` | 27 | 11,256 |
| `benchmark_real_os/` | 9 | 5,356 |
| `ai/` | 5 | 2,355 |
| `benchmark/` | 5 | 2,522 |
| `internet/` | 5 | 90 |
| `core/` | 4 | 397 |
| `memory/` | 4 | 1,413 |
| `runtime/` | 4 | 1,153 |
| `brain/` | 3 | 244 |
| `collaboration/` | 3 | 96 |
| `agent_context/`, `conversation/`, `emotion/`, `integration/`, `knowledge/`, `personality/`, `planner/`, `reasoning/` | 2 each | 799 combined |
| `router/` | 1 | 166 |
| **TOTAL** | **482** | **177,680** |

Observation recorded without judgement yet: 229 Python files sit loose in the repo root, and `genesis_os/` alone holds 135. Whether the root files are tests or production is classified in Â§2.3.

### 1.6 Digests of sealed / pinned artifacts (SHA-256, start of session)

Verbatim table generated by `s01_snapshot.py`; the machine-generated copy is in
`C:\Users\Muhammad\AppData\Local\Temp\opencode\audit\s01.out`:

| File | Bytes | SHA-256 |
|---|---|---|
| `phase3_final_results_2026-09-28.json` | 13,651 | see Â§12 re-verification table |
| `phase3_v3_SEALED.json` | 22,375 | `5b15c617d2099b48dbece9390d9d485a346fd689f474a56cf77bbb6c27299622` |
| `phase3_v4_SEALED.json` | 17,708 | `3d219e8715798a5bc942ecbb5a367d67cc8c8d983a82863c7b5b65a3f83e4f57` |
| `phase3_v4_SEAL_DIGEST.txt` | 314 | `c23ad60dd26cc193d60f1b2d4e4fb58062d98856168d8613fcb43b8351bd30d3` |
| `phase3_v3_AUDIT.json` | 998 | `6fd3a15aaf08107ecc80204151afa93431d487814bfa349dfeac5ab804c8d3d2` |
| `SEAL_DIGESTS.txt` | 696 | `318c8c1e86166d228426f062f38d9be86b85ba44ca9284eb178ff42b1aeb9cc1` |
| `requirements.txt` | 1,760 | `6d989566513704a07542a01c28bd6dcc1e1078f76db6c494d53d11948539584c` |
| `.env` | 681 | `ba25a11c74ff7f7951c920f5a7e139e3b15fbfc40055e217f56dc63f545854ef` |

Corpus sources (these are `.py` generators, not sealed data):

```
4fe61755cd867b7f...  phase3_negatives_vetted_corpus.py   10,878 B
0ab00944a1ceb301...  phase3_v3_corpus.py                  27,369 B
7a917c09484d63ec...  phase3_v4_corpus.py                  18,749 B
```

`.env` is hashed only. Contents are never printed anywhere in this report (Â§0.5). See Â§2.7 for which variable *names* are present.

**Not found:** there is no `final3`/`final4`/`dev3`/`dev4` *file* in the tree. The names exist only as recorded hashes inside `SEAL_DIGESTS.txt` and `phase3_v4_SEAL_DIGEST.txt`, and as benchmark result JSONs (`phase3_final3_*.json`, `phase3_final4_*.json`, `phase3_bench_dev_*.json`). The `split` file referenced by `split_sha256` is likewise not present as a standalone file. See Â§8 contradictions register.

### 1.7 Re-verification promise

Every digest in Â§1.6 is re-computed at the end of the session and compared in Â§12. If any differs, this section is wrong and the difference is reported there.

---

---

---

## 2. Inventory

### 2.1 Directory map

Top level (`C:\Users\Muhammad\Desktop\gemini_cli\backend`), `.py` file counts from Â§1.5:

| Path | `.py` | Purpose (from `__init__.py` docstring or module survey) |
|---|---|---|
| `genesis.py` | 1 | **The production entry point.** Single `GenesisOS` class; 107,972 bytes. |
| `genesis_os/` | 135 | "Genesis OS - UCCL Power-Suit Module", `__version__ = "9.0.0"`, `__all__ = []`. All capability subsystems. |
| `agents/` | 27 | Agent classes, registry, discovery, orchestrators, workflow decision engine. |
| `ai/` | 5 | `ai_engine`, `prompt_builder`, `provider`, `providers` â€” the LLM client layer. |
| `tools/` | 32 | Test/gate tooling added by the hygiene effort: tripwire, recorder, tiering, mutation harness, verify scripts. |
| `benchmark/` | 5 | 4 modules: `real_e2e`, `report`, `runner`, `scenarios` â€” in-process benchmark. |
| `benchmark_real_os/` | 9 | "Genesis OS - Real-OS Validation & Benchmark Infrastructure", 2,374-byte `__init__.py`. |
| `core/` | 4 | `exceptions`, `reliability`, `result`. |
| `brain/` | 3 | "Genesis OS" â€” composite brain facade. |
| `router/` | 1 | `Router` (deprecated per its own warning; see Â§8). |
| `planner/` | 2 | `intelligent_selector`, `task_planner` (both deprecated). |
| `memory/` | 4 | Session/working memory. |
| `internet/` | 5 | `formatter`, `internet`, `parser`, `search` (90 lines total - very thin). |
| `knowledge/`, `reasoning/`, `emotion/`, `personality/`, `conversation/`, `agent_context/` | 2 each | Single-module stubs, 34-131 lines each. |
| `collaboration/` | 3 | `agent_chain`, `agent_context` (96 lines total). |
| `integration/` | 2 | `genesis_agent_bridge`. |
| `runtime/` | 4 | `audit`, `genesis_runtime`, `models` â€” the audited-execution gateway. |
| `docs/` | 0 | Tiering snapshot + gate evidence JSON/MD. |
| `config/` at repo root | n/a | Present one level up; not audited here. |

`genesis_os/` subpackages:

| Subpackage | `.py` | Purpose |
|---|---|---|
| `applications/` | 7 | `app_manager`, `app_discovery`, `application_identity`, `application_resolution`, `unified_discovery`, `platform_catalog`, `store` |
| `documents/` | 1 | Empty package (`__init__.py` 0 bytes, no modules) |
| `filesystem/` | 3 | `file_manager`, `folder_manager` |
| `file_intelligence/` | 8 | Non-empty `__init__.py` (734 B) |
| `processes/` | 2 | "Genesis OS process intelligence" |
| `system/` | 2 | `system_manager` |

`genesis_os/` also holds **111 top-level modules** directly (full list in `s02_graph.py` output), including the entire capability layer, browser layer, workflow engine, safety layer and verification layer.

### 2.2 Entry points

| # | Entry point | Constructs, in order | Evidence |
|---|---|---|---|
| 1 | `genesis.py` â†’ `class GenesisOS` | 40 module-level imports, then per-instance: `CapabilityRegistry`/`ActionPlan`/`ActionExecutor` (`genesis.py:57-58`), `DesktopWorkflow` (`:59`), `WorkflowEngine` (`:60`), target providers (`:61-64`), `AgentOrchestrator` from `agents.agent_orchestrator` (`:107`, instantiated `:430-431`), `AgentDiscovery().discover()` â†’ 10 agent instances, `AIEngine` (calls `load_dotenv()`), `OSManager` â†’ `BrowserManager` â†’ 2 browser providers + `webbrowser` | `STATIC-READ` for order; live confirmations in Â§5 and Â§7 |
| 2 | `python -m benchmark_real_os` | has `__main__.py`; imported only by itself | `benchmark_real_os/__main__.py` |
| 3 | `python -m pytest` | the test harness; `conftest.py` auto-loads `tripwire_plugin` + `tree_write_plugin` | `conftest.py:147` |
| 4 | ~144 loose scripts in repo root | `run_*.py`, `verify_*.py`, `probe_*.py`, `phase3_*.py`, `_live_verify_*.py`, `check_genesis_stages.py`, `environment_readiness_check.py` | Â§2.3 classification |
| 5 | `tools/verify/*.py` | browser truthfulness, test stability, event-phase probes | Â§5, Â§7 |

**What production fails to construct, observed:** `GenesisOS()` succeeded on this machine but its `BrowserManager` registered only `['playbrowser','webbrowser']` â€” selenium never registers. See Â§7.3 and defect **D-01**.

### 2.3 Production vs non-production classification

Derived by static import-graph reachability from `genesis.py` (`s02_classify.py`), not by filename convention alone:

| Class | Count | Basis |
|---|---|---|
| Production runtime (reachable from `genesis.py`) | **132** | transitive static import closure |
| Test (collected) | 113 | `test_*.py` not in `pytest.ini` `--ignore` |
| Test (ignored by config) | 2 | `test_type_text_verification_live.py`, `run_direct_test.py` (note: the second is not a test) |
| Tool / harness | 24 | everything under `tools/` |
| Benchmark | 13 | `benchmark/`, `benchmark_real_os/` |
| Script-shaped (entry points, probes) | 144 | name-prefix match |
| Dead candidates (none of the above) | 54 | see Â§2.4 |
| **Total** | **482** | matches the Â§1.4 `.py` count exactly |

**Reachability from `genesis.py`: 132 local modules**, distributed: `genesis_os` 100, `agents` 9, `ai` 4, `internet` 3, `runtime` 3, `planner` 2, `memory` 2, and 1 each from `knowledge`, `brain`, `reasoning`, `emotion`, `personality`, `agent_context`, `router`, `conversation`, `collaboration`, `genesis`.

### 2.4 Dead and duplicate architecture

#### 2.4.1 The static dead-code list is WRONG for `agents/` - important caveat

`agents/agent_discovery.py:28-47` enumerates the package directory and calls `importlib.import_module(f"{self.package}.{module_name}")` on **every** `.py` file, swallowing failures at `:42-46`. So all 26 `agents/*.py` modules load at runtime regardless of static import sites.

Observed (`REAL-OS`):

```
[Agent Discovery] Found: Coding Agent
... (10 lines total) ...
agents modules loaded by discovery: 26
discovered agent instances: 10
```

A static-only audit would have declared 16 `agents/` modules dead. **They are not dead; they are dynamically loaded and their load failures are silently swallowed.** That swallow is itself a finding (**D-02**): an agent that fails to import prints to stdout and continues, so a missing agent degrades capability silently.

#### 2.4.2 Genuinely unreferenced modules (54 dead candidates)

Excluding `agents/` (see 2.4.1), these have no production import site, no test import site, and no script-shaped name:

`agents/agent_manager.py`, `collaboration/agent_chain.py`, `collaboration/agent_context.py`, `core/exceptions.py`, `core/reliability.py`, `core/result.py`, and 18 `genesis_os/` modules:

`application_state_machine`, `approval_channel`, `autonomous_audit`, `content_verifier`, `default_capabilities`, `digital_twin`, `federated_learning`, `format_converter`, `gui_errors`, `gui_observer`, `intent_engine`, `lineage_tracker`, `multimodal_router`, `nlq_engine`, `predictive_intelligence`, `schema_engine`, `security_scanner`, `semantic_adapter`, `semantic_parser`, `spatial_verification`, `template_engine`, `version_engine`, `workflow_binding`.

Caveat: `genesis_os/approval_channel.py` is demonstrably *exercised* by the suite (23 tests in `test_approval_channel.py` write its audit log) even though `genesis.py` never imports it. So "unreferenced" here means "not statically imported by the entry point", not "never executed". I did not run each module to confirm.

#### 2.4.3 Duplicate architecture - what production actually uses

| Job | Duplicates | Production uses | Evidence |
|---|---|---|---|
| Agent orchestration | `agents/orchestrator.py` (2,443 B) and `agents/agent_orchestrator.py` (4,443 B) - **both define a class named `AgentOrchestrator`** | **`agent_orchestrator`** | `genesis.py:107` `from agents.agent_orchestrator import AgentOrchestrator`; `genesis.py:430-431` instantiates it. `agents/orchestrator.py:1` defines a second, smaller `AgentOrchestrator` (`select_agent`/`execute`) that nothing imports. It survives only because the discovery loop loads every file. |
| Capability registry | `capability_registry.py` (imported directly by `genesis.py`) vs `capability_provider_registry.py` (used by `browser_manager.py`, `capability_resolver.py`) | **Both, for different things** | `capability_registry` = capability ids; `capability_provider_registry` = per-operation provider health/fallback. Names are near-identical; no docstring states the split. |
| Intent / classification | `llm_intent_resolver` + `workflow_decision` + `objective_understanding` (all direct); `intent_engine`, `semantic_adapter`, `semantic_parser`, `nlq_engine` (no import site) | **The first three** | `genesis.py` direct imports. The other four are unreferenced. |
| Context | `context_resolver` (direct), `context_hint_resolver`, `context_pipeline`, `structured_context`, `agent_context` (direct) | **Two are direct**: `context_resolver` and `agent_context` | 5 context modules, 2 wired. |
| Browser providers | `browser_manager` (direct) with `webbrowser`/`playwright`/`selenium` providers | **`browser_manager`** | single path. |
| Target resolution | `application_target_provider`, `file_target_provider`, `folder_target_provider` (all direct) + `target_discovery` (direct) + `target_resolution` | **Four direct** | Intentional layering, not duplication. |

#### 2.4.4 Phase 10-31 fake scaffolding: fully removed

Searched every file in the tree (binary-safe, excluding `.venv`/`__pycache__`/`.git`/`.pytest_cache`) for `skills_system`, `futuristic_core`, `test_genesis_phases_10_31`, `GENESIS_OS_UCCL_COMPLETE_REPORT`:

- **No files** match those names.
- **No references** to those identifiers anywhere (0 hits).
- The only `Phase 10` string matches (8 hits) are forward-looking deferral prose, e.g. `genesis_os/contracts.py:12` "its runtime is explicitly deferred to Phase 10" and `PHASE_1_PYDANTIC_CONTRACTS_2026-09-25.md:254` "Skill: **DEFERRED TO PHASE 10** - standalone model validation is complete; no Skill runtime is claimed."
- `genesis_os/__init__.py` has `__all__ = []`, so no package-level re-exports can hide the scaffolding.

**Verdict: no remnants.** One genuine forward-deferral exists - the `Skill` Pydantic model at `genesis_os/contracts.py` with no runtime. That is a Phase 10 gap, not scaffolding.

### 2.5 Misnamed, empty, or invalid files

| Finding | Evidence |
|---|---|
| No `.py` file contains Markdown | compile/parse check over all 482 files. The previously reported `calculator.py` is **absent** from the tree (it exists only as `tools/archive/calculator.py.md`, 8,754 B, and in the Oct 9 backup). |
| No empty `.py` files | zero-byte `__init__.py` files exist (18 of them) which is normal. |
| Two files carry a UTF-8 BOM | `genesis_os/applications/app_manager.py`, `genesis_os/applications/unified_discovery.py` - `raw[:3] == b'\xef\xbb\xbf'`. **Not a defect**: Python's import system strips BOM, and both parse cleanly with `utf-8-sig`. My first graph run with plain `utf-8` falsely reported them as parse failures *and* gave them empty dependency sets, which would have wrongly marked 5 modules dead. Corrected. |
| 0 files fail to compile | after the BOM correction, `ast.parse` succeeds on all 482. A runtime import smoke check is in Â§3. |
| Stray zero-byte file | `backend/file`, 0 bytes, `LastWriteTime 2026-10-13 02:36:10`. Not referenced by any code. |
| Single enormous module | `agents/workflow_decision.py` = **190,127 bytes**, larger than the 107,972-byte entry point. |

### 2.6 Dependencies

`requirements.txt`: 26 entries. **All 26 are range-constrained, none uses `==`.** There is no lockfile. Reproducibility finding (**D-03**).

| Import name | Declared as | Installed | In production path |
|---|---|---|---|
| `anthropic` | **ABSENT** | 0.116.0 | yes |
| `agent_framework` | `agent-framework` | 1.16.0 | yes |
| `docx` | `python-docx` | 1.2.0 | yes |
| `pptx` | `python-pptx` | 1.0.2 | yes |
| `dotenv` | `python-dotenv` | 1.2.2 | yes |
| `PIL` | `pillow` | importable | yes |
| `webdriver_manager` | `webdriver-manager` | 4.1.2 | yes |
| `screen_brightness_control` | `screen-brightness-control` | 0.27.2 | yes |
| `pydantic` | `pydantic` | 2.13.4 | yes |
| `playwright` | `playwright` | 1.62.0 | yes |
| `selenium` | `selenium` | 4.48.0 | yes |
| `pyautogui` | `pyautogui` | 0.9.54 | yes |
| `greenlet`, `win32com` | transitive | 3.5.5, importable | yes (playwright / pywin32 internals) |
| `PyPDF2`, `fitz` | **ABSENT** | **NOT importable** | tests only |

Real gaps:
- **`anthropic` is imported by a production-reachable module and installed, but is not in `requirements.txt`** (**D-04**). A clean install would lose the Anthropic path.
- `PyPDF2` and `fitz` (PyMuPDF) are imported somewhere but are neither declared nor installed â€” optional paths, recorded not failed.
- `pytest-timeout` is declared and installed but **has no import site**; whether `pytest.mark.timeout` is honoured depends on the plugin being auto-loaded, which I did not verify. See Â§11.

**Venv history.** The live interpreter is `C:\Users\Muhammad\Desktop\gemini_cli\.venv` (base `C:\Program Files\Python312`). A second environment named for "Genesis OS" is referenced in project history; **only `gemini_cli\.venv` exists and is live** â€” verified by `sys.prefix` (Â§1.2) and by the absence of any other `Scripts\python.exe` on `sys.path` resolution. `UNVERIFIED`: whether a "Genesis OS" venv directory still exists on disk; I did not enumerate drives.

### 2.7 Secrets and hygiene

**No key-shaped literal outside `.env` is a live credential.** The scanner found key-shaped *strings*; classified by inspection:

| Location | What it actually is |
|---|---|
| `.env:11` | the real `GROQ_API_KEY` value. Expected. **Never printed in this report.** |
| `_debug_phrases.py:13`, `_test_phrases.py:13` | `api_key = os.getenv(...)` patterns, not literals |
| `genesis_os/agent_framework_adapter.py:4618,4635,4690,4717` | `token` field names in prompt/tool schemas, not secrets |
| `genesis_os/security_scanner.py:43` | the **detection pattern** `SECRET ...` the scanner hunts for |
| `live_verify_phase2_agent_framework.py:163`, `run_groq_live_proof.py:34` | `api_key = ...getenv(...)` assignments |
| `test_approval_channel.py:516`, `test_phase4_provider_conformance.py:557,622,630,670` | test fixtures using the literal word `secret`/`api_key` as data |
| `phase2_rejection_probe_2026-09-26.txt:1` | three `token` strings in a captured probe transcript |

`.env` contains **11 keys, 2 of them empty** (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL` are `<EMPTY>`): `GENESIS_AI_MODE`, `OLLAMA_BASE_URL`, `OLLAMA_API_KEY`, `OLLAMA_MODEL`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`, `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_MODEL`, `GENESIS_WORKSPACE_ROOT`.

**Hygiene finding:** `.env` is in the repo tree. There is no `.gitignore` that matters because there is no git repo, but `.env` is hash-listed in Â§1.6 and has therefore been travelling with every copy of this tree. **D-05 (medium)**.

**Absolute-path leakage:** files containing a literal `C:\Users\...` path are enumerated in `s02e.out`. Presence confirmed; the count is in the machine output. I did not read every one.

---

---

---

## 3. Tests

### 3.1 Collection

`python -m pytest --collect-only -q -p no:cacheprovider`:

```
3209 tests collected in 9.68s
```

| Measure | Value |
|---|---|
| Total collected | **3209** |
| Test files collected | 102 node-id files (114 `test_*.py` exist; see exclusions below) |
| Files failing to collect | **0** |
| Files collected with zero tests | **0** among collected files |
| Tests deselected by `-m "not live"` | 485 |
| Tests in the fast tier | 2724 |

**Tier/marker breakdown, summing to the total:**

| Tier | Count | Source |
|---|---|---|
| `live` (deselected from fast gate) | 485 | measured: 3209 collected - 2724 fast-gate |
| not-`live` (fast tier) | 2724 | measured: 2689 passed + 35 skipped |
| **Sum** | **3209** | matches collection exactly |

**The `docs/tests_tiering.json` snapshot does not cover the current suite.** It contains 3,128 entries (98 `live`, 3,030 `runtime`). **84 collected tests live in 7 files that are absent from the snapshot** and therefore enter the fast gate with no recorded evidence:

```
test_browser_degraded_mode.py
test_genesis_entrypoint_behavior.py
tools/test_memory_mutation_harness.py
tools/test_tooling_guards.py
tools/test_tripwire_fixture_phases.py
tools/test_verify_all.py
benchmark_real_os/test_benchmark_real_os.py     (nodeid carries a UTF-8 BOM)
```

This is the intended default per `conftest.py` ("a test absent from the file keeps whatever marks it already has"), but it means the newest 84 tests are tiered by convention, not by measurement. **D-06 (medium).**

Note: only two markers are declared in `pytest.ini`: `live`. `pytest-timeout` is installed and declared in `requirements.txt` but has **no import site**; whether `@pytest.mark.timeout` is honoured is `UNVERIFIED` (see Â§11).

### 3.2 Execution

**Fast gate, ordering A (default).**
Command: `python -m pytest -m "not live" -q --no-header -p no:cacheprovider --tb=line -rf`

```
watched 2724 fast-gate test(s); 0 reached a real capability.
2689 passed, 35 skipped, 485 deselected, 5 warnings in 319.16s (0:05:19)
ELAPSED_SECONDS: 322.9
```
**2689 passed, 0 failed, 35 skipped, 0 xfailed, 0 errors, 485 deselected.**

**Fast gate, ordering B (the repo's own alternate-ordering plugin `alt_order_plugin.py`, `-p alt_order_plugin`).**

```
watched 2724 fast-gate test(s); 0 reached a real capability.
FAILED test_browser_degraded_mode.py::test_recovery_after_the_ttl_clears_the_degraded_flag
1 failed, 2688 passed, 35 skipped, 485 deselected, 5 warnings in 321.65s (0:05:21)
ELAPSED_SECONDS: 325.5
```
**2688 passed, 1 FAILED, 35 skipped, 0 xfailed, 0 errors, 485 deselected.**

> ### âš  THE TWO ORDERINGS DO NOT AGREE
>
> The suite has an order-dependent failure. This is the single most important test finding in this audit.
>
> - Reproduced: passes in isolation (`13 passed` for the whole file), and passes in default order (ordering A).
> - Fails in `alt_order_plugin` order (ordering B).
> - Not reproduced by prepending one specific predecessor test.
>
> **Most probable cause, with citations** (one link not directly instrumented, so labelled hypothesis not fact):
> 1. `genesis_os/browser_playwright.py` â€” `_store_probe_result()` assigns the module globals **directly** (`_probe_cache_at = time.monotonic()`), not through `monkeypatch`. A direct assignment cannot be undone by `monkeypatch`.
> 2. `test_browser_degraded_mode.py:228` sets `_probe_cache_at = monotonic() - TTL - 1` to force the TTL to have expired.
> 3. `test_browser_degraded_mode.py:230` then calls `monkeypatch.undo()`, which reverts line 228 along with everything else, restoring `_probe_cache_at` to whatever it was at test start.
> 4. In default order this file runs early, so at test start `_probe_cache_at` is still the module default `0.0` â†’ TTL long expired â†’ the probe re-runs â†’ `_probe_cache_kind` becomes `"definitive"` â†’ pass.
> 5. In alt order (`alt_order_plugin.py:36-43` sorts reverse-alphabetical, so `test_browser_degraded_mode.py` runs late) real provider probes have already run in the same process, so `_probe_cache_at` is recent â†’ the TTL has not expired â†’ the probe is not retried â†’ `_probe_cache_kind` stays `"timeout"` â†’ the assertion at `:231` fails.
>
> A scratch model of this mechanism (`audit\mech_undo.py`) did **not** reproduce the divergence, so the causal chain is **strongly supported but not confirmed**. Recorded as **D-07 (high)**.

**Tiers NOT run.** I did **not** run the `live` tier (485 tests) or the full unfiltered suite. Reasons: (a) the directive forbids running anything that can hang GUI/focus (Notepad, UIA readback, WM_CLOSE) except through the repo's own tiered runner, and the live tier includes exactly those; (b) the full run's own most recent measurement is **46m39s**, which does not fit the remaining session budget alongside the required analysis. **I therefore make no claim about the live tier's pass rate.** `UNVERIFIED`.

### 3.3 Test quality

Scanned all 114 `test_*.py` files by AST (`s03_quality.py`).

**A first pass reported 33 assert-free tests. On inspection 26 were false positives** â€” `test_phase1_contracts_maturity.py` routes its assertions through a helper that does assert:

```python
def _raises_violation(fn):                     # test_phase1_contracts_maturity.py
    with pytest.raises((ContractViolationError, ValueError)):
        fn()
```

I am reporting the corrected number, not the raw one.

**Genuinely vacuous tests (2) â€” the body computes a result and never checks it:**

| Test | Lines | Evidence |
|---|---|---|
| `test_level3_15_cross_level_integration.py::test_entity_history_resolves_pronoun_in_rebind` | 476-497 | ends `result = binder.try_rebind("open it")` with comment `# The entity should have been resolved` and **no assertion**. `ast.Assert` count = 0. |
| `test_level3_15_cross_level_integration.py::test_binder_resolves_before_marker_stripping` | 530-543 | ends `result = binder.try_rebind("now open it")` with comment `# The entity should have been resolved` and **no assertion**. `ast.Assert` count = 0. |

These two can only fail by raising. Their names and comments promise pronoun resolution that nothing verifies. **D-08 (high).**

**"Must not raise" tests (3) â€” legitimate but weak:** `test_compound_task_router.py::test_workflow_planner_validates_window_minimize_all` (L575-596) and `::test_workflow_planner_validates_media_play_pause` (L598-â€¦) end with a bare call and the comment `# Must not raise.`; `test_import_smoke.py::test_product_module_imports` is `importlib.import_module(module_name)` and nothing else. They prove absence of an exception, not correctness of the validation.

**Mock-only assertion (1 identified):** `test_level3_3_execution_maturity.py::test_spreadsheet_sort_uses_explicit_source_output` (L196-231) builds `os_manager = Mock()` and asserts `os_manager.sheet_sort.assert_called_once_with(...)`. The unit under test is `ActionExecutor`; every observation is of a mock. It verifies argument pass-through only.

**Broad exception handlers inside tests (12):** `test_approval_channel.py:477`, `test_compound_task_router.py:440,513,758`, `test_phase5_provider_registry.py:330,1374`, and six in `test_phase6_real_windows.py` (`:75,120,167,197,235`). Each can convert a real failure into a pass unless it re-raises. I did not read all 12 bodies individually; the ones I read re-raise. **Partially UNVERIFIED.**

**Skipped / xfailed.** The fast gate reports **35 skipped, 0 xfailed**. I did not extract the per-test skip reasons; the tiering snapshot's 98 `live` markers are the deselection mechanism, not skips. `UNVERIFIED` â€” reasons not enumerated.

**Weak spots re-checked as the directive asked:**

| Weak spot | Status now |
|---|---|
| `test_browser_manager_has_three_concrete_providers` (previously red) | **Green** in both orderings (it is in the 2,689/2,688). The earlier redness came from probe flakiness; `conftest.py:414` now attaches `deterministic_provider_probes` to it. But note the fixture makes the test *deterministic*, not *true* â€” see Â§7.3 and **D-01**, where the product reports itself healthy while selenium is missing. |
| Missed behavioural mutation on `run_level3` | A mutation harness exists at `tools/run_behavior_mutations.py`, but per its own docstring it "reports every mutation MISSED". I did **not** execute it. Its sandbox copies the tree to a temp dir and the result parser only matches `FAILED ` lines, so a collection ERROR reads as MISSED. **UNVERIFIED whether it works;** its own documented output is "all 3 reported MISSED", which is evidence it does not. **D-09 (medium).** |

### 3.4 Tripwire and recorder

**Auto-load confirmed.** Every fast-gate run prints, with no command-line flag:

```
watched 2724 fast-gate test(s); 0 reached a real capability.
```

That line is emitted by `tools/tripwire_plugin.py:230-247`, which `conftest.py:147` registers via `pytest_plugins = ["tripwire_plugin", "tree_write_plugin"]`.

**Catching an unmarked offender â€” with an important scope limitation.** I wrote a scratch offender **outside** the repo (`audit\offender_scratch.py`) with one test per event class plus a clean control.

Run 1 â€” no plugin flag, file outside `backend/`:
```
test_non_loopback_network PASSED
test_non_allowlisted_executable PASSED
test_ctypes_window_station PASSED
test_clean_control PASSED
4 passed in 3.50s
```
**The tripwire did not fire.** Its protection is a property of `backend/conftest.py`, so it applies only to tests under that rootdir.

Run 2 â€” same file, plugin loaded explicitly (`-p tripwire_plugin`):
```
test_non_loopback_network FAILED
test_non_allowlisted_executable FAILED
test_ctypes_window_station FAILED
test_clean_control PASSED
watched 4 fast-gate test(s); 3 reached a real capability.
3 failed, 1 passed in 2.85s
```

**All three required event classes are caught, by name, with no false positive on the control.** Evidence class: `REAL-OS` (real socket, real `hostname.exe`, real `ctypes.windll.user32.GetForegroundWindow`).

**What the tripwire does NOT cover:**
1. Tests outside `backend/` (proved above).
2. Any test carrying `@pytest.mark.live` â€” `_watch()` in `tools/tripwire_plugin.py` returns `False` for them, so the 485 live tests are unwatched by design.
3. Capability reached while an inner `except` swallows the error before it is recorded.
4. `tools/record_probe.py` and `tools/tree_write_plugin.py` self-test files, exempt by name via `RECORDER_SELF_TESTS` in `tools/tiering_rules.py` for the event kinds `process`, `dll_load`, `ctypes_call` (`test_tripwire_mutation.py:125-134` asserts this list exists).
5. Writes outside `backend/`, and writes matching `ALLOWED_WRITES` in `tools/tree_write_plugin.py` (currently `genesis_os/approval_audit.jsonl` and the `genesis_os/` directory itself).

### 3.5 Test-count history reconciled

| Reported total | Where recorded | Command recorded | What it actually measures |
|---|---|---|---|
| 1,253 | `PHASE_0_BASELINE_REPORT.md` (via `RECONCILIATION_EVIDENCE.md`) | `pytest -q` | full unfiltered run at that time |
| 1,494 / 1,518 | `PHASE_2_SECOND_BATCH_SESSION_A/B_REPORT.md` | `pytest --no-header` | full, mid-Phase-2 |
| 1,580 | `PHASE4_REPORT.md` | `pytest -q --tb=line` | full |
| 1,934 | `PHASE_0_BASELINE_REPORT.md` (4 mentions) | not stated | **conflated with the 1,253 baseline in the same file â€” see Â§8** |
| 2,061 | `PHASE_0_FORENSIC_BASELINE_2026-09-24.md` (7 mentions) | forensic re-count | full |
| 2,577 | `F5_CLOSEOUT_2026-10-08.md` | â€” | full |
| 3,128 | `docs/tests_tiering_summary.md` | generated by `tools/apply_tiering.py` | **not a collection count** â€” 3,128 tests *classified* (98 live + 3,030 runtime) |
| **3,209** | this audit, measured | `--collect-only` | **current collection** |

**The series is not a like-for-like series.** Two separate things changed:
- **New tests** genuinely raised the count.
- **Collection rules changed.** `pytest.ini:18-28` documents that `test_modal_dialog_recovery.py`, `test_phase6_real_windows.py` and `test_phase6_text_verification.py` were once listed in `--ignore`, "which silently disabled 27 real GUI tests from every run", and were later governed by the `live` marker instead. So some of the historical increase is tests that were always collected but hidden, not newly written.

Consequently **the 3,128 â†’ 3,209 delta is not 81 new tests**: 84 collected tests are absent from the tiering snapshot (Â§3.1), and the snapshot's 3,128 predates them. The honest statement is: the tiering snapshot covers 3,128 of 3,209 collected tests; 84 are unclassified.

---

---

## 4. Phase 0-31 verdicts against the roadmap

**Gate source:** `C:\Users\Muhammad\Desktop\gemini_cli\_roadmap_text.txt` (extracted from `Genesis_OS_UCCL_Power_Suit_Master_Roadmap.pdf`, 14 pages). All 32 phases parsed with names and gates. `STATIC-READ`.

**Evidence rule applied:** a phase is `CLOSED` only if its own gate wording is met with `REAL-OS` or `LIVE-LLM` evidence where the gate requires real behaviour. Mocked tests never close such a gate.

**Code completeness** = my estimate of how much of the phase's *stated tasks* exist as code. **Acceptance completeness** = % of stated tasks with gate-grade evidence. Both are my estimates, labelled as such.

---

### Phase 0 - Forensic Baseline
- **Gate:** "Every major runtime path is traceable and the current system has an evidence-backed baseline."
- **Code:** 5 baseline reports at repo root (`PHASE_0_BASELINE_REPORT.md`, `PHASE_0_FORENSIC_BASELINE_2026-09-24.md`, `PHASE0_FORENSIC_BASELINE.md`, `PHASE0_BASELINE_AUDIT.md`).
- **Tests:** none attributable.
- **Acceptance evidence:** `REPLAY` of the reports. This audit independently traced 6 of the runtime paths in Â§5 and found the baseline's 1,253/2,061 counts no longer comparable to 3,209 (Â§3.5).
- **Verdict: PARTIAL.** Traceability is demonstrated for the entry point, but the recorded baseline is stale and was not re-derivable from the reports themselves.
- **Code completeness 70% / acceptance 40%.**
- **Open defects:** baseline counts are not reproducible from the repo (Â§3.5, D-14).
- **Would close:** a regenerated trace map whose every path is re-verified in this session.

### Phase 1 - Pydantic Contract Foundation
- **Gate:** "Real runtime boundaries use validated contracts without breaking current functionality."
- **Code:** `genesis_os/contracts.py` (15 Pydantic models, `Skill` at :95-124).
- **Tests:** `test_phase1_contracts_maturity.py` - **26 tests**, fast tier. Verified that 22 of them assert via `_raises_violation` wrapping `pytest.raises` (Â§3.3) - **not** vacuous.
- **Acceptance evidence:** `MOCKED`/structural only. Contract validation is proven; "without breaking current functionality" is `UNVERIFIED`.
- **Verdict: PARTIAL.**
- **Code completeness 85% / acceptance 60%.**
- **Open defects:** `Skill` has no runtime - explicitly deferred (`genesis_os/contracts.py:12`).
- **Would close:** a real-runtime test showing a contract boundary on a live path.

### Phase 2 - Semantic Kernel Adapter
- **Gate:** "A real compatible LLM can call a Genesis capability and receive the verified result."
- **Code:** `genesis_os/agent_framework_adapter.py` (66 KB + a 63 KB expansion test file).
- **Tests:** `test_phase2_agent_framework_adapter.py`, `..._expansion.py` - large suites, fast tier.
- **Acceptance evidence:** **`UNVERIFIED` - I did not exercise an LLM tool-call against a real model.** In Â§5 the LLM path did reach Groq's TCP endpoint but produced no verifiable result record.
- **Verdict: PARTIAL.**
- **Code completeness 75% / acceptance 30%.**
- **Would close:** one `LIVE-LLM` transcript: model emits a tool call, a capability executes, and the verified result is returned to the model.

### Phase 3 - Capability Control Plane
- **Gate (roadmap's own wording):** "Unseen wording can select capabilities without sentence-specific rules."
- **Code:** `genesis_os/capability_registry.py`, `capability_resolution.py`, `capability_resolver.py`; `agents/workflow_decision.py` (190 KB - the single largest module in the repo).
- **Tests:** `test_capability_*` suites inside `test_compound_task_router.py`, `test_phase3_*` etc.; fast tier.
- **Acceptance evidence:** `REPLAY` of the sealed result files, which I did **not** re-run:

| Corpus | Mode | Model | Items | Strict accuracy |
|---|---|---|---|---|
| final3 (102) | control | none | 102 | **16.9%** |
| final3 (102) | local | `qwen2.5:7b` | 102 | **16.9%** |
| final3 (102) | cloud | `openai/gpt-oss-120b` | 102 | **64.9%** |
| final4 (82) | control | none | 82 | **17.5%** |

The result files carry `final3_sha256`/`final4_sha256` matching `SEAL_DIGESTS.txt`, so these numbers are against the sealed corpora. **Best measured accuracy is 64.9%, below the 75% bar.** The repo's own record agrees: `phase3_final_results_2026-09-28.json` says *"a valid full-corpus number could not be obtained... **The 75% bar remains unevaluated**."*

**On the two-part bar the directive asks me to separate:**
- **75% accuracy** - this is the **repo-local standard** adopted in `phase3_final_results_2026-09-28.json` and the score scripts. **The roadmap text I extracted does not state 75% or 5% anywhere**; the roadmap's actual gate wording is only *"Unseen wording can select capabilities without sentence-specific rules."* So 75%/5% is a repo-invented threshold, not a roadmap gate.
- **Against the roadmap's actual wording**, the control baseline of 16.9-17.5% already shows some capability selection happens without sentence rules, so the gate is partially met in spirit - but "unseen wording" accuracy of 64.9% (cloud) / 16.9% (local, identical to control) does not demonstrate reliable selection.
- **5% false-positive rate** - **not measured anywhere I could find.** `UNVERIFIED`.

- **Verdict: NOT CLOSED.**
- **Code completeness 85% / acceptance 45%.**
- **Open defects:** D-10 (non-deterministic capability selection, measured in Â§5.2).
- **Would close:** a `LIVE-LLM` run on a fresh sealed corpus reaching the stated bar, with a measured false-positive rate, plus a determinism check.

### Phase 4 - Model-Agnostic LLM Gateway
- **Gate:** "Switching models does not require changing computer capabilities."
- **Code:** `ai/provider.py`, `ai/providers.py` (Ollama/Anthropic/Groq/OpenRouter), `ai/ai_engine.py` (`_provider_by_name`, `switch`-style API, `GENESIS_AI_MODE`).
- **Tests:** `test_phase4_provider_conformance.py` - 4 key-shaped literals found, all fixtures.
- **Acceptance evidence:** `UNVERIFIED` for a genuine model switch. I observed the *attempt* order (local then cloud) in Â§5.0 but could not confirm which model produced a result.
- **Verdict: PARTIAL.**
- **Code completeness 80% / acceptance 40%.**
- **Open defects:** D-04 (`anthropic` installed and imported but undeclared).
- **Would close:** the same capability request executed against two different real models with identical capability IDs.

### Phase 5 - Universal Provider Runtime
- **Gate:** "A capability can select a healthy appropriate provider and verify its result."
- **Code:** `genesis_os/capability_provider_registry.py`, `browser_manager.py` (3 providers, health checks), `test_phase5_provider_registry.py`.
- **Tests:** `test_phase5_provider_registry.py` - fast tier; two of its tests were the slowest in the suite (71.20s, 70.88s).
- **Acceptance evidence:** **contradicted at runtime.** In Â§7.3 the manager reported `provider_names == ['webbrowser']` with `browser_degraded == False` while the selenium probe was in `timeout` state. The runtime does not report its own degradation truthfully, so it cannot be said to select a *healthy* provider on a truthful signal.
- **Verdict: PARTIAL.**
- **Code completeness 80% / acceptance 35%.**
- **Open defects:** **D-01 (high)**.
- **Would close:** a `REAL-OS` run proving provider health reporting is truthful, and that a healthy alternative is chosen.

### Phase 6 - Computer Hands (Application + GUI)
- **Gate:** "A real Windows editor/application workflow executes and is independently verified."
- **Code:** `genesis_os/gui_controller.py`, `gui_observer.py`, `applications/app_manager.py`, `ui_automation_provider.py`.
- **Tests:** `test_phase6_real_windows.py` (6 `live` tests, all with broad `except Exception`), `test_level3_2_applications.py`, `test_modal_dialog_recovery.py` - all `live`, **not run by me**.
- **Acceptance evidence:** `UNVERIFIED` by this audit (GUI dispatch prohibited by Â§0.6).
- **Verdict: PARTIAL.**
- **Code completeness 75% / acceptance 25%.**
- **Open defects:** the 6 `except Exception` handlers in `test_phase6_real_windows.py` are unverified re-raises.
- **Would close:** a `REAL-OS` run of `test_phase6_real_windows.py` through the repo's own runner, showing a real window opened and independently verified.

### Phase 7 - Filesystem Intelligence
- **Gate:** "Natural filesystem references resolve correctly without invented paths."
- **Code:** `genesis_os/file_intelligence/`, `file_target_provider.py`, `folder_target_provider.py`, `target_discovery.py`, `nlq_engine.py` (no import site).
- **Tests:** `test_file_intelligence_foundation.py`, `test_phase7_filesystem_intelligence.py`, `test_workspace_boundary.py` - fast tier.
- **Acceptance evidence:** mixed. Â§5.5 shows a *natural-language* file-creation request in unseen wording routed to conversation and the OS leg refused it - i.e. resolution did **not** happen. Positive path evidence is `MOCKED`.
- **Verdict: PARTIAL.**
- **Code completeness 80% / acceptance 35%.**
- **Open defects:** D-11 (unseen wording does not reliably reach the filesystem path).

### Phase 8 - Browser Intelligence
- **Gate:** "Real browser workflows execute and verify their target page state."
- **Code:** `genesis_os/browser_manager.py`, `browser_playwright.py`, `browser_selenium.py`; `web_intelligence.py`.
- **Tests:** `test_level3_3_browser_adversarial.py` (9 tests, 63-71s each, `live`), `test_level3_3_browser_closed_loop.py`, `test_phase5_provider_registry.py` - all `live`, **not run by me**.
- **Acceptance evidence:** `UNVERIFIED` by this audit. What I *did* establish: playwright registers (`_probe_cache == 1`, `definitive`), selenium **never** registers, and `webbrowser` cannot read back page state (its own `open_url` returns `verification_type: "browser_dispatch_only"`).
- **Verdict: PARTIAL.**
- **Code completeness 80% / acceptance 20%.**
- **Open defects:** D-01; only one of two advanced providers is reachable in this environment.
- **Would close:** a `REAL-OS` run showing a real page opened and its state read back by something other than the dispatch call.

### Phase 9 - Documents + Data Intelligence
- **Gate:** "Real-file transformations create correct verified outputs without corrupting originals."
- **Code:** `document_intelligence.py`, `spreadsheet_intelligence.py`, `format_converter.py`, `document_manager.py`, `spreadsheet_manager.py`; deps `python-docx`, `openpyxl`, `python-pptx`, `pypdf`, `reportlab` all importable.
- **Tests:** `test_phase9_document_edit_safety.py`, `test_phase9_spreadsheet_safety.py`, `test_level3_4_document_edit_transform_verify.py`.
- **Acceptance evidence:** `UNVERIFIED` - not run by me; deps present is necessary, not sufficient.
- **Verdict: PARTIAL.**
- **Code completeness 70% / acceptance 25%.**
- **Would close:** a `REAL-OS` transformation with a byte-level before/after comparison of the original.

### Phase 10 - Skills System
- **Gate:** "Genesis can reuse a verified skill without requiring the model to rediscover every step."
- **Code:** **no runtime.** Only the `Skill` Pydantic model, `genesis_os/contracts.py:95-124`, explicitly deferred (`contracts.py:12`).
- **Search run:** filename scan for `skill*`; text scan for `skills_system`; import scan - **0 runtime hits**. The Phase 10-31 scaffolding check (Â§2.4.4) found no remnants, and the only "Phase 10" references are deferral prose.
- **Tests:** `test_phase1_contracts_maturity.py::test_skill_rejects_empty_id` - structural only.
- **Verdict: NOT STARTED** (contract model only; the gate needs a skill runtime).
- **Code completeness 10% / acceptance 0%.**
- **Would close:** a skill that executes twice, the second time reusing the verified steps.

### Phase 11 - Dynamic Task Graph
- **Gate:** "No required step disappears from compound or mixed workflows."
- **Code:** `genesis_os/dynamic_plan.py`, `workflow_decomposer.py`, `workflow_planner.py`; `agents/compound_task_router.py` (all reachable from `genesis.py`).
- **Tests:** `test_compound_task_router.py` (39 tests, 4 `live`).
- **Acceptance evidence:** **contradicted at classification.** Â§5.4: `classify("open notepad and write hello from genesis")` set `is_compound: True, compound_clause_count: 2` but returned `intent=application.open` only - the second clause is absent from the intent. Full-loop preservation is `UNVERIFIED` (dispatch blocked).
- **Verdict: PARTIAL.**
- **Code completeness 75% / acceptance 30%.**
- **Open defects:** D-15 - compound clause is recorded but not carried into the intent.
- **Would close:** a `REAL-OS` compound dispatch showing both clauses in the executed plan, in order.

### Phase 12 - Policy + Authorization Engine
- **Gate:** "No model can bypass Genesis policy."
- **Code:** `authorization_grant.py` (identity-checked grant, Â§6.2), `approval_channel.py`, `approval_store.py`, `security_model.py`, `execution_safety.py`, `workspace_boundary.py`.
- **Tests:** `test_approval_channel.py` (41 tests, **all fast tier, none `live`**), `test_authorization_*` inside other files, `test_workspace_boundary.py`, `test_blast_radius.py`.
- **Acceptance evidence:** **`REAL-OS`, and it is the strongest positive result in this audit.** Â§5.6: a real `file.delete` against a real temp file was refused with *"requires a human-approval grant"* and the file was verifiably untouched. Â§6.2 proves a grant cannot be forged from model JSON. Â§6.3 proves the workspace boundary blocks outside-root, `..`, UNC, `.env` and product-file targets, and fails closed on an unparseable path.
- **Verdict: CLOSED** for the authorisation/approval/boundary mechanism. Two caveats: (i) the gate says "policy" generally, and the boundary is **off by default** when `GENESIS_WORKSPACE_ROOT` is unset; (ii) `approval_channel.py` has no import site in `genesis.py`, so I cannot prove the approval *channel* is reachable from the entry point - only that the gate blocks.
- **Code completeness 85% / acceptance 70%.**
- **Would close:** a `REAL-OS` demonstration that a *granted* operation then executes, proving the channel is reachable end to end.

### Phase 13 - Human Escalation
- **Gate:** "Uncertainty has a deterministic safe outcome."
- **Code:** `approval_channel.py` (prompt/deny on no TTY), `test_approval_channel.py::test_no_tty_denies`.
- **Tests:** 41 tests in `test_approval_channel.py`, fast tier.
- **Acceptance evidence:** `MOCKED` - the tests drive stdin doubles. The `REAL-OS` confirmation in Â§5.6 was of the *refusal*, not of an interactive escalation.
- **Verdict: PARTIAL.**
- **Code completeness 60% / acceptance 35%.**
- **Would close:** a `REAL-OS` run showing an interactive prompt appearing and a real approval token being minted and consumed.

### Phase 14 - Observation + Verification
- **Gate:** "No important result can be reported as verified without evidence."
- **Code:** `observation_loop.py`, `enhanced_observation.py`, `action_result.py` (`has_meaningful_result_evidence`, `require_result_evidence`), `verification_helpers.py`, `content_verifier.py`, `lineage_tracker.py` (no import site).
- **Tests:** `test_confirmed_not_an_authority.py` (23), `test_verification_honesty_sweep.py` (41 KB), `test_phase1_contracts_maturity.py` evidence-gate tests.
- **Acceptance evidence:** `MOCKED`/structural - the evidence-gate rejects are contract-level. `REAL-OS` observation-loop behaviour **not run by me**.
- **Verdict: PARTIAL.**
- **Code completeness 80% / acceptance 45%.**
- **Open defects:** `lineage_tracker.py`, `content_verifier.py`, `spatial_verification.py`, `gui_observer.py` have no production import site.
- **Would close:** a `REAL-OS` run showing a result marked verified only when an independent post-state read backs it.

### Phase 15 - Recovery + Replanning
- **Gate:** "Injected and real failures either recover safely or terminate honestly."
- **Code:** `recovery_engine.py`, `error_handler.py`, `failure_classifier.py`, `self_healing.py` (no import site).
- **Tests:** `test_phase6_failure_injection.py`, `test_level3_3_execution_maturity.py`.
- **Acceptance evidence:** `UNVERIFIED` by this audit. I did observe honest termination in Â§5.5 ("Genesis could not safely prepare that operating-system action") and Â§5.6 (approval refusal) - both are *honest termination*, which is half the gate.
- **Verdict: PARTIAL.**
- **Code completeness 70% / acceptance 30%.**
- **Would close:** a `REAL-OS` failure injection showing recovery to a verified state.

### Phase 16 - Durable Workflows
- **Gate:** "Genesis restarts without corrupting state or blindly repeating destructive actions."
- **Code:** `session_persistence.py`, `workflow_state.py`, `session_state.py`, `session_context.py`; `Checkpoint` model in `contracts.py`.
- **Tests:** `test_phase1_contracts_maturity.py::test_checkpoint_rejects_empty_ids` (structural only).
- **Acceptance evidence:** **`UNVERIFIED` - I found no restart/resume test and ran none.** `PHASE_1_PYDANTIC_CONTRACTS_2026-09-25.md:262` states "durable checkpoint resume is owned by Phase 16", i.e. the repo itself records this as not delivered.
- **Verdict: NOT STARTED** (persistence plumbing exists; resume does not).
- **Code completeness 40% / acceptance 5%.**
- **Would close:** kill the process mid-workflow, restart, and show it resumes without repeating the destructive step.

### Phase 17 - Event-Driven AIOS
- **Gate:** "Real environment changes can safely wake or update workflows."
- **Code:** `genesis_os/filesystem_monitor.py` (uses `watchdog`, bounded, "honest fallback when absent" per `requirements.txt`), `progress_events.py`, `daily_intelligence.py`.
- **Tests:** none I could attribute to a wake/update assertion.
- **Acceptance evidence:** `UNVERIFIED`. `watchdog` is importable; no evidence a real filesystem change wakes a workflow.
- **Verdict: NOT STARTED.**
- **Code completeness 25% / acceptance 0%.**
- **Would close:** a `REAL-OS` run creating a file that wakes a registered workflow.

### Phase 18 - Scheduler + Concurrency
- **Gate:** "Concurrent workflows remain isolated, bounded and predictable."
- **Code:** `agents/parallel_executor.py` (**no production import site**), `GENESIS_LLM_INFLIGHT_CAP` in `llm_intent_resolver.py:257` (a concurrency cap, default 1).
- **Tests:** none attributable.
- **Acceptance evidence:** `UNVERIFIED`.
- **Verdict: NOT STARTED.**
- **Code completeness 20% / acceptance 0%.**
- **Open defects:** `parallel_executor.py` exists but nothing imports it.
- **Would close:** a `REAL-OS` test running N concurrent workflows with isolated state and a measured bound.

### Phase 19 - Environment Abstraction
- **Gate:** "UCCL remains portable even when individual capabilities are platform-specific."
- **Code:** `genesis_os/system/system_manager.py`, `os_manager.py`, `applications/platform_catalog.py`. Everything is Windows-specific: `ctypes.windll.user32`, `pywin32`, `comtypes`, `pycaw`, `screen_brightness_control` are all `sys_platform`-pinned in `requirements.txt`.
- **Acceptance evidence:** **the opposite of the gate's intent is demonstrable** - the runtime is hard-bound to Windows by its dependency set. No portability layer was found.
- **Verdict: NOT STARTED.**
- **Code completeness 15% / acceptance 0%.**
- **Would close:** a capability executed on a second OS, or a platform interface that resolves to a stub elsewhere.

### Phase 20 - Secure Agentic Execution
- **Gate:** "Generated work cannot silently bypass Genesis security policy."
- **Code:** `security_model.py` (imported by `action_executor.py` 3x), `security_scanner.py` (no import site), `blast_radius.py`, `zk_compliance.py`, `authorization_grant.py`.
- **Tests:** `test_blast_radius.py` (54), `test_phase2_destructive_capabilities.py`.
- **Acceptance evidence:** `REAL-OS` for the destructive case (Â§5.6) - generated work did **not** bypass policy. The "silently" part is strengthened by the boundary refusing unparseable paths (Â§6.3).
- **Verdict: PARTIAL.**
- **Code completeness 75% / acceptance 50%.**
- **Open defects:** `security_scanner.py` has no production import site despite its name.
- **Would close:** a `REAL-OS` run where a model-authored plan attempts a boundary escape and is stopped, with the attempt recorded.

### Phase 21 - Adaptive Workflow + Experience Memory
- **Gate:** "Previously verified tasks can be reused locally and similar tasks can adapt safely."
- **Code:** `genesis_os/lineage_tracker.py`, `federated_learning.py`, `digital_twin.py`, `predictive_intelligence.py` - **all four have no production import site.**
- **Tests:** none attributable.
- **Verdict: NOT STARTED.**
- **Code completeness 10% / acceptance 0%.**
- **Would close:** a `REAL-OS` second execution reusing a stored verified plan.

### Phase 22 - Context Compaction + Long-Horizon State
- **Gate:** "Long-running workflows remain coherent across context pressure and resumptions."
- **Code:** `structured_context.py`, `context_pipeline.py`, `session_persistence.py`, `entity_history.py`. No compaction implementation found.
- **Acceptance evidence:** `UNVERIFIED`.
- **Verdict: NOT STARTED.**
- **Code completeness 15% / acceptance 0%.**
- **Would close:** a run exceeding the context window that still completes with verified results.

### Phase 23 - Production Observability
- **Gate:** "Significant failures can be traced from user request to root cause."
- **Code:** `runtime/audit.py`, `genesis_os/lineage_tracker.py` (no import site), `approval_audit.jsonl` (an append-only log **inside the source tree**), and the hygiene tooling's own `tools/record_probe.py` + `docs/fast_gate_evidence.json`.
- **Tests:** `tools/test_record_probe_canaries.py` and friends - these test the *test* instrument, not production telemetry.
- **Acceptance evidence:** `UNVERIFIED` for production. The recorder evidence files are test-harness artifacts, not a production trace.
- **Verdict: NOT STARTED.**
- **Code completeness 20% / acceptance 5%.**
- **Open defects:** the one real runtime log lives in the source tree (D-05).

### Phase 24 - Generalization
- **Gate:** "New wording and combinations work without benchmark-specific phrase rules."
- **Code:** `agents/unseen_task_semantic.py` (29 KB), `semantic_adapter.py` / `semantic_parser.py` (no import site), `capability_resolution.py`.
- **Tests:** `test_unseen_task_semantic.py`, `test_splitter_generalization.py`, `test_level3_3_browser_adversarial.py`.
- **Acceptance evidence:** **`REAL-OS` and it contradicts the gate.** Â§5.5: an unseen phrasing for a file-creation request routed to `level=1 conversation` in one process and `level=3 document.create_txt` in another. Â§5.2: the same prompt gave `web.research` 4/5 and `browser.search` 1/5.
- **Verdict: NOT CLOSED.**
- **Code completeness 70% / acceptance 20%.**
- **Open defects:** D-10, D-11.
- **Would close:** a determinism + accuracy measurement on a fresh unseen corpus.

### Phase 25 - Real-OS Validation Fabric
- **Gate:** "Real-world claims are backed by physical evidence."
- **Code:** `benchmark_real_os/` - 9 modules, real `__init__.py` (2,374 B), `evidence.py`, `verifiers.py`, `runner.py`, `contract.py`, `test_benchmark_real_os.py`.
- **Tests:** `benchmark_real_os/test_benchmark_real_os.py` - 37 tests, **absent from the tiering snapshot** (Â§3.1).
- **Acceptance evidence:** `UNVERIFIED` - the fabric exists and I confirmed it imports, but I did not run a scored benchmark. I have **no** `REAL-OS` evidence produced *by this fabric*.
- **Verdict: PARTIAL.**
- **Code completeness 80% / acceptance 25%.**
- **Would close:** one full `benchmark_real_os` run emitting an evidence artifact with physical verification per claim.

### Phase 26 - 500+ Real-World Acceptance
- **Gate:** "Transparent real-world scorecard with verified outcomes."
- **Code:** `benchmark_real_os/scenarios.py`, `report.py`. The corpora present are **102 items (final3) and 82 (final4)**; the largest acceptance corpus anywhere in the tree is 102.
- **Acceptance evidence:** `UNVERIFIED`; no 500-item scorecard exists. Corpus sizes are `STATIC-READ` from the sealed files.
- **Verdict: NOT STARTED.**
- **Code completeness 25% / acceptance 0%.**
- **Would close:** a 500+ item scorecard with per-item verified outcomes.

### Phase 27 - Windows Certification
- **Gate:** "Representative workflows succeed on a real Windows machine with evidence."
- **Code:** `test_phase6_real_windows.py` (7 `live` tests), `test_level3_23_gui_text_input_compound.py`, `test_gui_window_focus_regression.py`.
- **Acceptance evidence:** `UNVERIFIED` - the `live` tier was not run by me (Â§3.2). The existence of a Windows-only test suite is not certification.
- **Verdict: NOT STARTED** (tests exist; certification does not).
- **Code completeness 40% / acceptance 10%.**
- **Would close:** a recorded pass of the `live` Windows suite on this machine with an evidence artifact.

### Phase 28 - Model Interoperability Certification
- **Gate:** "Changing the LLM does not require changing the computer-agency layer."
- **Code:** `ai/providers.py` implements 4 providers behind one interface; `genesis_os/llm_intent_resolver.py` has `GENESIS_LLM_MODES` (`:275`).
- **Acceptance evidence:** `UNVERIFIED`. Â§5.0 shows the *attempt* order changing (local then cloud) without a code change, which is consistent with the gate but does not prove identical capability behaviour across models. Â§5.2 in fact shows the model choice *changes which intent is selected*.
- **Verdict: PARTIAL.**
- **Code completeness 75% / acceptance 20%.**
- **Open defects:** D-10 - the model demonstrably influences the selected capability.

### Phase 29 - Genesis Developer Platform
- **Gate:** "A third-party developer can safely add a capability or provider through stable contracts."
- **Code:** `genesis_os/capability_catalog.py`, `capability_registry.py`, `contracts.py`, `default_capabilities.py` (no import site). No plugin loader, no manifest, no SDK.
- **Acceptance evidence:** `UNVERIFIED`. `agents/agent_discovery.py` is a directory scanner, not a stable extension contract.
- **Verdict: NOT STARTED.**
- **Code completeness 20% / acceptance 0%.**
- **Would close:** a third party adding a capability through a documented contract, with a test proving it registers.

### Phase 30 - Capability / Skill Ecosystem
- **Gate:** "Extensions remain isolated, auditable and policy-controlled."
- **Code:** no ecosystem. `Skill` is a contract with no runtime (Phase 10). `agents/agent_discovery.py` loads every module in its directory with no isolation and swallows import errors.
- **Acceptance evidence:** `UNVERIFIED`, and the isolation half is contradicted by D-02 (unisolated, silently-swallowed dynamic loading).
- **Verdict: NOT STARTED.**
- **Code completeness 5% / acceptance 0%.**
- **Would close:** two mutually-unaware extensions installed, each policy-controlled and separately auditable.

### Phase 31 - Final AIOS Gate
- **Gate (roadmap):** "Do not declare production-grade until the full closed loop works reliably on unseen reasonable [inputs]."
- **Acceptance evidence:** **not met, and the blocking evidence is in this report.** Reliability is contradicted by D-07 (order-dependent failure), D-10 (non-deterministic capability selection), D-01 (untruthful health reporting). Phases 10, 16-19, 21-23, 26, 27, 29, 30 are `NOT STARTED`.
- **Verdict: NOT CLOSED.**
- **Code completeness 45% / acceptance 5%.**
- **Would close:** every prior gate met, plus a stability run showing no order-dependent and no non-deterministic failures.

---

### 4.1 Cross-cutting work that does NOT close a later phase

| Existing work | Overlaps | Why it does not close that phase |
|---|---|---|
| `authorization_grant.py` + `approval_channel.py` + `workspace_boundary.py` (the F5 work) | **Phase 12** | It genuinely satisfies Phase 12's gate as far as refusal goes (Â§6.2, Â§5.6, Â§6.3). It does **not** close Phase 13: I found no real approval token ever minted and consumed end to end, and `approval_channel.py` has no import site in `genesis.py`. |
| `tools/record_probe.py`, `docs/fast_gate_evidence.json`, `test_verification_honesty_sweep.py` | **Phase 14** | These are **test-harness** instruments. They evidence the *test suite's* honesty, not the product's. Phase 14's gate is about reported results at runtime. |
| `benchmark_real_os/` (9 modules) | **Phase 25** | The fabric exists. I ran no scored benchmark, so it has produced **zero** physical evidence from me. Its own test file is absent from the tiering snapshot. |
| `tools/tripwire_plugin.py` + `tree_write_plugin.py` | none | These are CI gates, not product capability. Correctly closed nothing. |
| `genesis_os/contracts.py` `Skill` model | **Phase 10** | A model with no runtime. The repo's own `contracts.py:12` says so. |

### 4.2 Phase totals (computed by me, from the 32 entries above)

| Verdict | Count | Phases |
|---|---|---|
| `CLOSED` | **1** | 12 |
| `PARTIAL` | **16** | 0, 1, 2, 4, 5, 6, 7, 8, 9, 11, 13, 14, 15, 20, 25, 28 |
| `NOT CLOSED` | **2** | 3, 24 |
| `NOT STARTED` | **13** | 10, 16, 17, 18, 19, 21, 22, 23, 26, 27, 29, 30, 31 |
| **Total** | **32** | 1 + 16 + 2 + 13 = 32 âœ“ |

**Closed ratio: 1/32 = 3.1%.**

Phase 27 is `NOT STARTED` rather than `PARTIAL` because a Windows-only test suite is not certification: the gate asks for *representative workflows succeeding with evidence*, and no such evidence exists in the tree.

---

---

---

## 5. Level 1, 2, 3 end to end

All traces ran against the **real** `GenesisOS` entry point in a fresh process, with `GENESIS_WORKSPACE_ROOT` pointed at a temp directory the script created and removed. No fixture, no stub, no mock.

**Safety constraint applied:** I did **not** dispatch any prompt that opens a window, and did not call the window station. Prompts that would open Notepad were classified and planned but not executed. The repo's own `live` tests do dispatch them; I did not invoke those.

### 5.0 Which backend answers, observed at the socket

I patched `socket.socket.connect` and `socket.create_connection` in my own process (not in the repo) and recorded every destination. This is "as observed", not "as configured":

| Prompt | Outbound sockets observed during `classify()` | Time |
|---|---|---|
| "Hello, who are you?" | **none** | 0.2s |
| "open notepad" | **none** | 0.0s |
| "Research the top 3 programming languages in 2026" | `localhost:11434` (Ã—2, loopback) then `api.groq.com:443` â†’ `172.64.149.20:443` | 26.8s |
| "i want a brand new text file called probe.txt in my workspace" | `localhost:11434` then `api.groq.com:443` | 25.6s |

Environment: `GENESIS_AI_MODE=auto`, `OLLAMA_MODEL=qwen2.5:7b`, `GROQ_MODEL=openai/gpt-oss-120b`.

**Reading:** local Ollama is *attempted first* on every LLM-routed prompt, then Groq. The ~26s cost is the LLM round trip. Deterministic prompts never touch the network at all.

**I could not confirm which provider actually produced the answer.** `GenesisOS` exposes no `ai_engine`/`ai` attribute holding the engine (probe: `AIEngine object found: False`), and `AIEngine._usage_records` was empty in the runs where I did find the object. So "which model answered" is **`UNVERIFIED`**; what is verified is the *attempt order* (local then cloud) and the elapsed time.

### 5.1 Level 1 â€” "Hello, who are you?"

| Stage | Observed |
|---|---|
| Route | `level=1`, `mode=conversation`, `intent=None`, `confidence=0.85` |
| Capability | none selected |
| Authorization | not reached |
| Dispatch | not reached (and correctly not needed) |
| Observation / verification | n/a |
| Backend | none - no outbound socket, 0.0-0.2s |
| Evidence class | `STATIC-READ` for the code path, `REAL-OS` for the observed route |

Correct behaviour, and it is decided **without a model**.

### 5.2 Level 2 â€” "Research the top 3 programming languages in 2026"

| Run | Observed route |
|---|---|
| trace run 1 | `level=2`, `mode=multi_agent` |
| trace run 2 | `level=3`, `mode=os` |
| determinism run, 5Ã— in one process | `level=3`, `mode=os`, `intent=web.research` **Ã—4**, then `intent=browser.search` **Ã—1** |

> ### âš  `classify()` is NOT deterministic for LLM-routed prompts
>
> The same sentence produced **two different levels across two processes** (`level=2 multi_agent` vs `level=3 os`), and within one process it produced **two different intents** for the same request (`web.research` then `browser.search`).
>
> Full determinism result (5 repeats, one process):

| Prompt | Distinct routes | Verdict | Time |
|---|---|---|---|
| "Research the top 3 programming languages in 2026" | **2 of 5** | **NON-DETERMINISTIC** | 26.9-27.7s |
| "i want a brand new text file called probe.txt in my workspace" | 1 of 5 | stable | 25.5-26.4s |
| "open notepad" | 1 of 5 | stable | 0.0s |
| "Hello, who are you?" | 1 of 5 | stable | 0.0-0.1s |

The pattern is exact: **every prompt that is decided without the model is stable; every prompt that goes to the model can vary.** The second clause of the research request selects a different *capability* on one run in five, which means capability selection is not a function of the input. This is the single most consequential finding for the Phase 3 and Phase 24 gates (Â§4). **D-10 (critical).**

### 5.3 Level 3 â€” "open notepad"

| Stage | Observed |
|---|---|
| Route | `level=3`, `mode=os`, `intent=application.open`, `application=notepad` |
| Backend | none - 0.0s, no network (deterministic rule) |
| Dispatch | **NOT EXECUTED** - audit safety policy (Â§0.6) |
| Observation / verification | **not established** |

The routing half is verified. The dispatch/observe/verify half of this specific gate is **`UNVERIFIED` in this audit**; the repo's own `live` tests exercise it.

### 5.4 Compound â€” "open notepad and write hello from genesis"

`classify()` returned in **0.0s, no LLM**:

```
level=3  mode=os  intent=application.open  application=notepad
parameters._capability_resolution:
    capability_id = application.open
    is_compound   = True
    compound_clause_count = 2
    user_facing_target = "open notepad and write hello from genesis"
```

**The system detects the compound request (`is_compound: True`, `compound_clause_count: 2`) but the top-level `intent` is only `application.open`.** The second clause is present in the raw text and absent from the intent. Compound expansion therefore happens later, inside `run_level3` (I observed `[Genesis OS] Compound task detected (2 steps, reason=multi_step_level3)` in an earlier run for a different phrasing), not at classification.

**What lands in the editor, and the execution order: `UNVERIFIED`** - establishing it requires dispatching, which opens Notepad. I did not run it. Note `CompoundTaskRouter()` cannot be constructed standalone (`TypeError: ... missing 1 required positional argument: 'objective_understanding'`), so the plan is not inspectable without the full runtime.

### 5.5 Unseen paraphrasings (invented for this audit, absent from the repo and corpora)

| # | Phrasing | Route observed | Correct? |
|---|---|---|---|
| 1 | "could you pop open the thing i use for notes" | `level=1 conversation` | defensible - genuinely conversational |
| 2 | "i want a brand new text file called c2_audit_probe.txt in my workspace" | **`level=1 conversation`** in run 1; `level=3 document.create_txt` 5/5 in run 3 | **NO** - see below |
| 3 | "grab the downloads folder and tell me what is inside" | `level=1 conversation` | defensible - it is a question |

> ### âš  Unseen wording for a file-creation request routed to conversation - and the OS leg then refused it
>
> In trace run 1, phrasing 2 classified as `level=1 conversation`. I dispatched it to `run_level3` anyway and got:
>
> ```
> [Genesis OS] Action plan rejected: Only Level 3 decisions can be converted into an ActionPlan.
> DISPATCH   : Genesis could not safely prepare that operating-system action.
> ```
>
> **The file was never created** (`expected path exists: False`, workspace empty).
>
> In trace run 3 the identical sentence classified `level=3 document.create_txt` five times out of five. So the same unseen sentence routed to conversation in one process and to the correct capability in another. Either way the headline is the same: **unseen wording for an unambiguous file-creation request does not reliably reach the Level 3 OS path.** The safety behaviour is at least correct - it refused rather than guessing. **D-11 (high).**

### 5.6 Destructive request against a disposable temp file

| Stage | Observed |
|---|---|
| Victim | `<temp>/c2_audit_victim.txt`, 18 bytes, content "do not delete me" |
| Route | `level=3`, `intent=file.delete` |
| Target resolution | `[Genesis OS] Target: c2_audit_victim.txt` |
| Authorization | **BLOCKED**: `This operation is irreversible or outward-facing and requires a human-approval grant.` |
| Dispatch | refused before any filesystem mutation |
| **Victim after** | **still exists, 18 bytes, content intact** |
| Evidence class | **`REAL-OS`** - a real file on a real filesystem was targeted and was verifiably untouched |

The destructive gate held on a real file. This is the strongest single piece of positive evidence in the audit. **Cleanup:** the temp workspace was removed (`workspace removed: True`) and `backend/file` was re-checked as still 0 bytes and untouched.

---

---

---

## 6. Safety and security posture

### 6.1 `confirmed: true` carries no authority â€” CONFIRMED

Product-code occurrences of `confirmed` (tests and tools excluded):

| Location | What it is |
|---|---|
| `genesis.py:2991-3029` | The user-confirmation path. `confirmed_decision["source"] = "LLMIntentResolver+user_confirmed"` records the yes as a **source label only**. The in-code comment at `:2999-3005` states the old behaviour injected `parameters["confirmed"] = True` and "self-approved by metadata", and that the injection "is removed rather than left as decoration". |
| `agents/workflow_decision.py:2363, :2530` | `parameters={"confirmed": False, ...}` - always `False` |
| `agents/unseen_task_semantic.py:378,400,424,442,774` | `"confirmed": False` - always `False` |
| `agents/coding_agent.py:914`, `agents/security_agent.py:263` | the word "confirmed" inside an LLM **prompt string** about issue triage, not a control |

**No product code reads `confirmed` as an authorisation input.** The only remaining occurrences are literal `False` values, a source label, and prompt text.

**Live negative test.** In Â§5.6 I drove a real `file.delete` through the real entry point. It was refused: `This operation is irreversible or outward-facing and requires a human-approval grant.` The victim file was untouched. Evidence class `REAL-OS`.

### 6.2 The authorization grant is structurally unreachable from model JSON â€” CONFIRMED

| Property | Evidence |
|---|---|
| Cannot be constructed directly | `genesis_os/authorization_grant.py:61` `_MINT_TOKEN = object()`; `:81` `if self._mint is not _MINT_TOKEN: raise` |
| Only a real approval token mints one | `:89-116` `issue_authorization_grant()` requires a `str` token (`:111-112`) and calls `ApprovalStore.consume_token(token, arguments=args)` (`:116`) |
| Tokens are single-use | `ApprovalStore.consume_token`; the comment at `:136-140` explains why a record-based re-mint exists |
| Attach refuses anything that is not a real grant | `genesis_os/action_plan.py:66-78` `_is_authorization_grant()` uses `isinstance`; `:96-98` raises; `:612-622` re-validates and states "JSON-shaped values" are refused |
| Consumed at the executor | `genesis_os/action_executor.py:783` imports from `authorization_grant` |

A model emitting `{"confirmed": true, "authorized": true}` in JSON cannot satisfy any of these: the field is not read, and the grant type is identity-checked. This design holds. **Positive finding.**

### 6.3 Workspace boundary â€” behaviour matrix (measured)

The enforcement function is `arguments_escape_workspace(arguments, *, capability_id)` (`workspace_boundary.py:346-368`), not `resolve_target_path` (which only *resolves*). I initially probed the wrong function and got a misleading "not enforced" result; the corrected measurement is below.

`path_is_within` (`:292-303`) deliberately uses `Path.relative_to`, not `str.startswith`, "which would wrongly accept a sibling directory sharing a name prefix".

| Case (`file.create` unless noted) | Root SET | Root UNSET |
|---|---|---|
| path inside the root | **ALLOWED** | ALLOWED |
| path outside the root | **BLOCKED** | ALLOWED |
| `..` traversal out of the root | **BLOCKED** | ALLOWED |
| `file.delete` outside the root | **BLOCKED** | ALLOWED |
| `source` key pointing outside (read) | **BLOCKED** | ALLOWED |
| capability with no path argument (`app.launch`) | ALLOWED | ALLOWED |
| unresolvable path string | **BLOCKED** (fails closed) | ALLOWED |
| UNC `\\server\share\file.txt` | **BLOCKED** | ALLOWED |
| product file `backend/genesis.py` | **BLOCKED** | ALLOWED |
| secrets file `backend/.env` | **BLOCKED** | ALLOWED |

Other measured behaviour:

| Condition | Result | Verdict |
|---|---|---|
| `GENESIS_WORKSPACE_ROOT=""` or whitespace | `BoundaryConfigurationError: ... set but empty; the boundary cannot` | **fails closed** |
| root = `"not-a-path-at-all-xyz"` (nonexistent, relative) | silently resolved against CWD to `backend/not-a-path-at-all-xyz` | **fails OPEN on a nonsense root** - D-12 (low) |
| root = `C:\nonexistent\nope\deep` | accepted as-is | no existence check - D-12 |
| UNC path as a *target* | BLOCKED | good |
| UNC/network path as the *root* | **UNVERIFIED** - not tested | |
| symlink escape | **UNVERIFIED** - `os.symlink` raised `WinError 1314 A required privilege is not held`; the audit session cannot create symlinks | |
| `path_is_protected` | True for `workspace_boundary.py`, `authorization_grant.py`, `.env`, `phase3_v4_SEALED.json`; **False for `genesis.py`** | see Â§8 |
| Is the real entry point armed? | `genesis.py` calls `announce_boundary_state()` at `:161` area and `action_executor` imports the boundary module; with the root set, `boundary_is_enforced()` is `True` in-process | armed |

**The boundary is OFF by default.** With `GENESIS_WORKSPACE_ROOT` unset, every case is ALLOWED. That is the documented design (`boundary_is_enforced()` is simply `workspace_root() is not None`, `:212-214`), but it means the safe behaviour depends entirely on an environment variable being present at launch. Recorded, not a defect per se.

### 6.4 Fail-open vs fail-closed

| Site | Behaviour | Assessment |
|---|---|---|
| `workspace_boundary.workspace_root()` empty/whitespace | raises `BoundaryConfigurationError` | **fail-closed** |
| `arguments_escape_workspace` unparseable path | returns a BLOCKED reason | **fail-closed** (stated in its own docstring: "a path-bearing value that could not be parsed, is reported as an escape rather than skipped") |
| `BrowserManager.__init__` provider probe | `except Exception:` falls back to **sequential** registration | fail-closed-ish; degrades to slower but still tries |
| `agents/agent_discovery.py:42-46` | `except Exception: print(...); continue` | **FAIL-OPEN**: an agent that fails to import is skipped and the system continues with fewer agents, printing only to stdout. D-02 |
| `genesis_os/daily_intelligence.py:54` | `except Exception: return {"success": False, ...}` | fail-closed (reports failure) |
| 12 test-side `except Exception` handlers | listed in Â§3.3 | **UNVERIFIED** - not all 12 bodies read |

### 6.5 Logging and sensitive data

- `genesis_os/approval_channel.py:95` returns `Path(__file__).parent / "approval_audit.jsonl"`; `:118-119` appends a record and the module docstring states the record holds "hash and paths but never contents" (asserted by `test_approval_channel.py::test_audit_records_hash_and_paths_but_never_contents`).
- The **audit log itself lives inside the source tree** (`backend/genesis_os/approval_audit.jsonl`) and grows on every approval-gated action. It is a product-tree write (Â§2.7, D-05) and means the tree is not byte-stable between runs.
- `test_approval_channel.py:516` and `test_phase4_provider_conformance.py:557,622,630,670` contain key-shaped literals, but they are test fixtures using the words `secret`/`api_key` as data, not credentials.
- `.env` contains a live `GROQ_API_KEY` (`gsk_` prefix) and is present in the tree. It has been copied with every backup. **Never printed in this report.** D-05.

---

---

## 7. Reliability and performance

### 7.1 Startup

```
GenesisOS() constructed in 8.5s      (fresh process, real probes, no fixture)
```

What dominates, from the same session's measurements:

| Component | Measured |
|---|---|
| Browser provider probe, outer bound | `_PROVIDER_PROBE_TIMEOUT = 10.0` (`browser_manager.py`) |
| Browser provider probe, inner join | `proc.join(timeout=5.0)` per provider |
| **Selenium probe real duration** | **>30s** - 3/3 attempts were still alive at 30s, because `_probe_chromedriver_subprocess` calls `ChromeDriverManager().install()`, which resolves a driver over the network. It therefore **never** answers inside the 5s join. |
| LLM classify, model-routed | 25.5-27.7s |
| LLM classify, deterministic rule | 0.0-0.2s |

Startup is dominated by the browser probe and, for model-routed requests, by the LLM round trip (Ollama attempted first, then Groq).

### 7.2 Slow / potentially blocking paths

| Path | Bound? | Evidence |
|---|---|---|
| LLM per-call | yes, `_LLM_CALL_TIMEOUT = 12.0` | `genesis_os/llm_intent_resolver.py:194` |
| LLM total resolve | yes, `_RESOLVE_TOTAL_BUDGET = 22.0` | `:198` |
| LLM engine request | yes, `GENESIS_LLM_TIMEOUT_SECONDS` default `60` | `ai/ai_engine.py:108` |
| Browser provider probe | yes, 5s inner / 10s outer | `browser_manager.py` |
| **Ollama native HTTP call** | **NO CLIENT-SIDE CEILING** | `ai/providers.py:450` `urllib.request.urlopen(request, timeout=None)`. The code comment states this is deliberate: "the caller bounds the whole request with its own budget". Whether that caller bound actually wraps this specific native path is **UNVERIFIED**. D-13 (medium). |
| Weather lookup | yes, `timeout=8` | `genesis_os/daily_intelligence.py:47-51` |
| Selenium probe subprocess | yes, 5s join, then terminated | `browser_selenium.py` |
| Browser test suite worst case | **629.5s single test** | measured in the repo's own most recent full run: `test_level3_9_application_verification.py::test_open_missing_application_executor_does_not_pretend_verified` = 22.5% of a 2799s run. I did **not** re-measure it. `REPLAY` from the run log, `UNVERIFIED` by me. |

### 7.3 Provider layer and what is actually available right now

Observed in this environment, this session:

| Provider | Configured | Reachable | Evidence |
|---|---|---|---|
| Ollama (local) | `OLLAMA_BASE_URL`, `OLLAMA_MODEL=qwen2.5:7b` | **connection attempted, result unknown** | `create_connection -> localhost:11434` observed during classify; no HTTP 200 was captured, and `_usage_records` was empty, so I cannot confirm a local model answered |
| Groq (cloud) | `GROQ_API_KEY` **set**, `GROQ_MODEL=openai/gpt-oss-120b` | **TCP connect observed** | `create_connection -> api.groq.com:443` then `socket.connect -> 172.64.149.20:443` |
| OpenRouter | `OPENROUTER_API_KEY` **EMPTY**, `OPENROUTER_MODEL` **EMPTY** | not usable | `.env` key inspection (names/empty-flag only) |
| Anthropic | **installed 0.116.0, imported by production code, absent from `requirements.txt`** | not exercised | Â§2.6, D-04 |
| Playwright (browser) | `playwright` 1.62.0 | probe returned `1 / definitive` | `browser_playwright._probe_cache == 1`, kind `definitive` |
| Selenium (browser) | `selenium` 4.48.0 | **never registers** - probe exceeds the 5s join | `browser_selenium._probe_cache == 0`, kind `timeout` |
| `webbrowser` (stdlib) | always | registered | present in every observed `provider_names` |

> ### âš  `browser_degraded` is `False` while a provider is missing - **D-01 (high)**
>
> Observed in this session: `provider_names == ['webbrowser']` and `browser_degraded == False`, with the selenium probe cache kind recorded as `timeout`.
>
> **Cause (read from the code):** `BrowserManager.degraded` is set only when the *outer* `wait([f_sel, f_pw], timeout=10.0)` leaves futures pending. The *inner* `proc.join(timeout=5.0)` timing out makes `_check_availability()` return `False` **normally**, so the future completes, `pending` is empty, and `_degraded_reason` stays `None`.
>
> Because selenium's probe can never answer in 5s, the manager reports itself fully healthy while permanently missing a provider. The TTL (60s) re-probes but cannot change the outcome. **The runtime's own health report is not truthful.** This directly undercuts the Phase 5 gate "A capability can select a healthy appropriate provider and verify its result."

---

---



---

---

## 8. Contradictions register

Each row: the two claims, the evidence for each, and which is true.

### C-01 `genesis.py` is protected from destructive operations â€” **CONTRADICTED**
- **Claim A (code):** `workspace_boundary.protected_paths()` returns "Absolute paths Genesis treats as its own protected surface", including `backend_root / "genesis_os"`.
- **Claim B (measured):** `path_is_protected(<backend>/genesis.py)` returned **`False`** (Â§6.3). The tuple contains `backend_root/"genesis_os"` - a *sub*directory - not `backend_root`, so the 107,972-byte entry point and the rest of `backend/` are unprotected.
- **True:** Claim B. The protection covers `genesis_os/**`, `.env`, `phase3_v4_SEALED.json`, `conftest.py` and the boundary module - **not** `genesis.py`.
- **Severity:** high. D-16.

### C-02 "no approval channel exists yet" â€” **CONTRADICTED by the running system**
- **Claim A (code message):** `genesis.py:3021-3024` prints *"operations that require an approval grant are still blocked - **no approval channel exists yet**."*
- **Claim B (runtime):** in Â§5.6 the real runtime said *"This operation is irreversible or outward-facing and **requires a human-approval grant**"*, and `authorization_grant.py` / `approval_store.py` / `approval_channel.py` all exist and are imported by `action_executor.py:783`.
- **True:** an approval channel exists. The `genesis.py` message is stale - it was written when the grant was not yet built, and was not updated when it was. It is also *conservative* (understates capability), so it is not a safety defect, but it is a false statement to the operator.
- **Severity:** medium. D-17.

### C-03 Phase 0 baseline total: 1,253 vs 1,934 â€” **1,934 is right**
- **Claim A:** `RECONCILIATION_EVIDENCE.md` table: `PHASE_0_BASELINE_REPORT.md | 1253 | pytest -q`.
- **Claim B:** `PHASE_0_BASELINE_REPORT.md:13-14` "Total tests | 1934 / Passed | 1934" and `:33` "**Result:** `1934 passed, 2 warnings in 1416.90s (0:23:36)`".
- **True:** **1,934.** The reconciliation table mis-attributes the count; the report's own body is authoritative and internally consistent (total = passed = 1934, with a matching runtime).
- **Severity:** low. This is the single most useful entry in this register, because the reconciliation table is the thing a reader would use to reconstruct history.

### C-04 The mutation harness "works" â€” **its own docstring says it does not**
- **Claim A (implied by the tool's existence):** `tools/run_behavior_mutations.py` is the mutation gate.
- **Claim B (same file, module docstring):** *"This applies three mutations in turn, each restored immediately, and reports which BEHAVIOURAL tests failed."* - and the project history records it reporting **all three MISSED**.
- **True:** **it does not work.** Its result parser matches only lines beginning `FAILED `, so a collection or setup ERROR yields an empty list which it prints as `MISSED`. An instrument that cannot distinguish "not measured" from "not covered" reports the second as the first.
- **Evidence I gathered:** `test_genesis_entrypoint_behavior.py` is 13 tests; a reported `MISSED` with 0 failures is the signature of the tests not running.
- **Severity:** medium. D-09.

### C-05 Suite is green â€” **true in one ordering only**
- **Claim A:** the repo's own most recent full run: 3,158 passed, 0 failed.
- **Claim B (measured by me):** the fast gate in the repo's **own alternate ordering** (`alt_order_plugin.py`) gives **1 failed, 2,688 passed** (Â§3.2).
- **True:** both, under their own conditions. Any claim of "the suite is green" is incomplete without naming the ordering.
- **Severity:** high. D-07.

### C-06 `classify()` is a function of its input â€” **contradicted**
- **Claim A:** the roadmap Phase 3 gate: *"Unseen wording can select capabilities without sentence-specific rules"*; and Phase 24: *"New wording and combinations work without benchmark-specific phrase rules."* Both presuppose a deterministic mapping.
- **Claim B (measured, Â§5.2):** the same prompt, 5 times in one process, produced `intent=web.research` 4x and `intent=browser.search` 1x. And across two processes the same sentence gave `level=2 multi_agent` and `level=3 os`.
- **True:** Claim A's presupposition does not hold for model-routed prompts. Deterministic prompts (`open notepad`, `Hello, who are you?`) are perfectly stable at 5/5 - the instability is introduced precisely by the LLM path.
- **Severity:** critical. D-10.

### C-07 "Real-file transformations ... without corrupting originals" (Phase 9) vs `phase3_*.json` sizing â€” **not a contradiction, recorded as UNVERIFIED**
- No claim either way could be tested within this session's safety budget. Listed so it is not mistaken for a pass.

### C-08 Test-count history as a monotonic series â€” **misleading**
- **Claim A:** the series 1,253 â†’ 1,934 â†’ 2,061 â†’ 2,577 â†’ 3,128 â†’ 3,209 read as "tests were added".
- **Claim B (documented in the repo):** `pytest.ini:18-28` states that three test modules "were previously listed here [`--ignore`], which silently disabled **27 real GUI tests** from every run, fast and full. They are now governed by `live`".
- **True:** part of the increase is **previously-hidden tests becoming visible**, not new tests. The series cannot be decomposed without the per-run `--ignore` list, which is not recorded.
- **Severity:** medium. D-14.

### C-09 `3,128` is presented beside collection counts but is not a collection count
- **Claim A:** the historical series treats 3,128 as the predecessor of 3,209.
- **Claim B:** `docs/tests_tiering_summary.md` says "tests classified: **3128**" with a live/runtime breakdown - it is a **tiering snapshot**, and 84 currently-collected tests are absent from it (Â§3.1).
- **True:** Claim B. 3,209 - 3,128 = 81 is not "81 new tests".

### C-10 The tripwire is a property of the product â€” **it is a property of `conftest.py`**
- **Claim A (natural reading of "auto-loaded tripwire"):** any test that reaches a real capability is caught.
- **Claim B (measured, Â§3.4):** a scratch offender **outside** `backend/` passed all three checks; only with `-p tripwire_plugin` did they fail.
- **True:** Claim B. The protection is scoped to the rootdir.

### C-11 `resolve_target_path` appears not to enforce the boundary â€” **misleading; the enforcement is elsewhere**
- **Claim A (my first measurement):** with the root set, an outside path and a `..` traversal both resolved successfully, which reads as "the boundary does not confine".
- **Claim B:** enforcement lives in `arguments_escape_workspace(arguments, *, capability_id)` (`workspace_boundary.py:346-368`), which calls `path_is_within`. Correctly invoked (Â§6.3) it **BLOCKS** outside-root, `..`, UNC, `.env` and product-file targets and **fails closed** on an unparseable path.
- **True:** Claim B. I record this because my own first reading was wrong and the correction is instructive: the boundary is sound, it is just not where the name suggests.

### C-12 "Verified" in a printed banner vs a real check
- **Claim A:** `webbrowser`'s `open_url` returns `verified: False` with `verification_type: "browser_dispatch_only"` and an honest reason.
- **Claim B:** `webbrowser` is the **only** browser provider that registers on this machine (Â§7.3).
- **True:** both, and together they mean the Phase 8 gate is unreachable in this environment: the only available provider is one that is structurally incapable of verifying page state. This is consistent with the product's own honesty, and is **to its credit**.

---

---

## 9. Complete defect ledger

| ID | Sev | Location | Evidence | Affects |
|---|---|---|---|---|
| **D-10** | **critical** | LLM-routed `classify()` | Â§5.2: same prompt 5x -> 2 distinct intents; 2 processes -> 2 distinct levels | Phases 3, 24, 28, 31 |
| **D-01** | high | `genesis_os/browser_manager.py` `degraded` property | Â§7.3: `provider_names==['webbrowser']` with `browser_degraded==False` while the selenium probe kind is `timeout`; inner 5s `join` timeout returns False *normally* so the outer 10s `wait` sees no pending future | Phase 5, 8, 31 |
| **D-07** | high | `test_browser_degraded_mode.py:228,230` | Â§3.2: default order green, `alt_order_plugin` order fails. `monkeypatch.undo()` reverts the test's own TTL setup; `_probe_cache_at` is assigned directly by `_store_probe_result` and cannot be undone | Phase 25, 31 |
| **D-08** | high | `test_level3_15_cross_level_integration.py:476-497, 530-543` | Â§3.3: `result = binder.try_rebind(...)` with **no assertion**; names and comments promise pronoun resolution | Phase 24 |
| **D-11** | high | LLM routing for filesystem intents | Â§5.5: unseen file-creation phrasing routed to `level=1 conversation`; the OS leg then refused it ("Only Level 3 decisions can be converted into an ActionPlan") and no file was created | Phases 3, 7, 24 |
| **D-16** | high | `genesis_os/workspace_boundary.py` `protected_paths()` | Â§8 C-01: `path_is_protected(<backend>/genesis.py)` is `False`; the list covers `genesis_os/**` but not the entry point or `backend/` | Phase 12, 20 |
| **D-02** | medium | `agents/agent_discovery.py:42-46` | Â§6.4: every `.py` in the package is imported dynamically and import failures are `print` + `continue` - fail-open, silent capability loss | Phases 13, 30 |
| **D-06** | medium | `docs/tests_tiering.json` | Â§3.1: 84 collected tests in 7 files are absent from the tiering snapshot and default into the fast gate with no recorded evidence | Phase 25 |
| **D-09** | medium | `tools/run_behavior_mutations.py` | Â§8 C-04: only matches `FAILED ` lines, so setup ERRORs read as MISSED; the harness cannot distinguish "not measured" from "not covered" | Phase 25 |
| **D-14** | medium | test-count history | Â§8 C-08, C-09: 27 GUI tests were once `--ignore`d; the historical series mixes new tests with changed collection rules and is not decomposable | Phase 0 |
| **D-17** | medium | `genesis.py:3021-3024` | Â§8 C-02: prints "no approval channel exists yet" while the approval channel demonstrably exists | Phase 12, 13 |
| **D-13** | medium | `ai/providers.py:450` | Â§7.2: `urllib.request.urlopen(request, timeout=None)`; the comment asserts the caller bounds it, but whether the caller bound wraps this native Ollama path is unverified | Phase 4, 5 |
| **D-04** | medium | `requirements.txt` | Â§2.6: `anthropic` 0.116.0 is installed and imported by production code but not declared | Phase 4 |
| **D-03** | medium | `requirements.txt` | Â§2.6: 26 entries, **zero** use `==`; no lockfile, so the environment is not reproducible | Phase 27, 31 |
| **D-05** | medium | `backend/.env`, `backend/genesis_os/approval_audit.jsonl` | Â§2.7, Â§6.5: a live `gsk_` key travels in the tree, and the runtime audit log is written *into* the source tree, so the tree is not byte-stable | Phase 23, 27 |
| **D-15** | medium | `agents/workflow_decision.py` compound handling | Â§5.4: `is_compound=True, compound_clause_count=2` but `intent` is only the first clause | Phase 11 |
| **D-12** | low | `workspace_boundary.workspace_root()` | Â§6.3: a nonexistent/relative root (`"not-a-path-at-all-xyz"`) is accepted and resolved against CWD; empty/whitespace correctly fails closed | Phase 12 |
| **D-18** | low | `backend/file` | Â§2.5: stray 0-byte file, `LastWriteTime 2026-10-13 02:36:10`, referenced by no code | - |
| **D-19** | low | `genesis_os/applications/app_manager.py`, `unified_discovery.py` | Â§2.5: UTF-8 BOM. **Not a defect** (Python strips it); recorded because naive tooling reports it as a parse error | - |

---

---

## 10. Not completed and UNVERIFIED

**Deliberately not run, with reasons:**

1. **The `live` tier (485 tests) and the full unfiltered suite.** Â§0.6 forbids GUI/focus execution outside the repo's own tiered runner; the live tier opens Notepad, drives UIA and closes windows. Budget: the most recent full run is 46m39s. **I make no claim about the live tier's pass rate.**
2. **`test_browser_manager_has_three_concrete_providers` under real probes** - it is `live`.
3. **`benchmark_real_os` scored run.** Would produce the `REAL-OS` evidence Phase 25 needs; not run, so Phase 25 stays `PARTIAL`.
4. **Phase 3 re-measurement.** Quoted from the sealed result files as `REPLAY`; I did not re-run the corpus, so the 64.9% figure is the repo's, not mine.
5. **All 12 `except Exception` handlers in tests** read individually; 3 were read, 9 not.
6. **Per-test skip reasons** for the 35 skips were not enumerated (`-rs` not used).
7. **`pytest-timeout` effectiveness.** Declared and installed with no import site; whether `@pytest.mark.timeout` is honoured is untested.
8. **Symlink escape through the workspace boundary.** `os.symlink` failed with `WinError 1314` (privilege not held). The escape is `UNVERIFIED` in both directions.
9. **UNC path as the workspace ROOT** (only as a target was tested).
10. **Which model actually produced a `classify()` answer.** `_usage_records` was empty and `GenesisOS` exposes no reachable `AIEngine` attribute. I proved the *attempt* order (localhost:11434, then api.groq.com:443) and nothing stronger.
11. **Whether a second "Genesis OS" venv exists on disk.** Only `gemini_cli\.venv` resolved; no filesystem enumeration of other drives.
12. **Every absolute-path leak** enumerated in `s02e.out` was not individually read.
13. **The causal chain for D-07.** My scratch model of the `monkeypatch.undo()` mechanism did **not** reproduce the divergence; the chain is code-supported but not instrumented.
14. **The 5% false-positive rate** in the Phase 3 bar is not measured anywhere I could find.
15. **Sealed-digest content verification.** I hashed the seal *files*; I did not recompute `final3_sha256`/`final4_sha256` from the corpus items to confirm the digests still describe their content.

---

---

## 11. Reconciliation block

**Collected tests = sum of tiers**

| Tier | Count |
|---|---|
| `live` (deselected by `-m "not live"`) | 485 |
| fast tier (`level 0` in ordering A) | 2724 |
| **Sum** | **3209** |
| Measured collection total | **3209** âœ“ |

Fast-gate execution, ordering A: 2689 passed + 35 skipped + 0 xfailed = 2724 âœ“
Fast-gate execution, ordering B: 2688 passed + 35 skipped + **1 failed** = 2724 âœ“

**Digests before vs after** - see Â§12, recomputed at the end of the session.

**Files changed by this audit:** exactly one, `GENESIS_FULL_REPOSITORY_REPORT_2026-10-14.md`, created in the repo root. No product code, test, config, corpus or sealed-digest file was modified.

**Scratch files:** all audit scripts and logs live in `C:\Users\Muhammad\AppData\Local\Temp\opencode\audit\`, outside the repository. Nothing was written inside `backend/` except this report. Temp workspaces created by the level and boundary traces (`c2_audit_ws*`, `c2_audit_out*`) were removed by those scripts; the last check reported `workspace removed: True`.

**Processes started by this audit:** the two fast-gate pytest runs (orderings A and B), plus short-lived python and PowerShell children of the scratch scripts. All completed; none was left running. The only long-lived background process was the ordering runner (PID recorded in `audit\order.pid`), confirmed finished. No Notepad, no browser window, no OS automation was launched at any point.

---

---

---

## 12. End-of-session digest re-verification

Computed after all analysis, per the promise made in Â§1.7.

| File | Status | SHA-256 (after) |
|---|---|---|
| `phase3_v3_SEALED.json` | **UNCHANGED** | `5b15c617d2099b48dbece9390d9d485a346fd689f474a56cf77bbb6c27299622` |
| `phase3_v4_SEALED.json` | **UNCHANGED** | `3d219e8715798a5bc942ecbb5a367d67cc8c8d983a82863c7b5b65a3f83e4f57` |
| `phase3_v4_SEAL_DIGEST.txt` | **UNCHANGED** | `c23ad60dd26cc193d60f1b2d4e4fb58062d98856168d8613fcb43b8351bd30d3` |
| `phase3_v3_AUDIT.json` | **UNCHANGED** | `6fd3a15aaf08107ecc80204151afa93431d487814bfa349dfeac5ab804c8d3d2` |
| `SEAL_DIGESTS.txt` | **UNCHANGED** | `318c8c1e86166d228426f062f38d9be86b85ba44ca9284eb178ff42b1aeb9cc1` |
| `requirements.txt` | **UNCHANGED** | `6d989566513704a07542a01c28bd6dcc1e1078f76db6c494d53d11948539584c` |
| `.env` | **UNCHANGED** | `ba25a11c74ff7f7951c920f5a7e139e3b15fbfc40055e217f56dc63f545854ef` |
| `genesis.py` | baseline recorded | `cfca4f49bfd1329694ed227f87bf31faf4857fc7d7ed145b2254fd44e2d58b57` |

**All pinned digests unchanged: True.** The sealed corpora, their digests, `requirements.txt` and `.env` are byte-identical to the start of the session.

### 12.1 Two product-tree files changed *during* my test runs

A whole-tree mtime scan (last 6h) found 18 recently-modified files. Sixteen are from the **previous** session (19:00-21:28, the hygiene work: `conftest.py`, `tools/*`, `genesis.py`). Two changed **inside my session's window**, by running the repo's own test suite:

| File | Modified | Referenced by |
|---|---|---|
| `phase3_ranking_probe_2026-09-28.json` | 2026-10-14 23:02:43 | `test_phase3_control_plane_maturity.py:922`, `test_import_smoke.py:227` |
| `genesis_os/approval_audit.jsonl` | 2026-10-14 23:04:52 | the product's approval channel |

This is a real observation, not a contradiction of Â§11: **I did not modify them; the test suite did, as a side effect of running.** `approval_audit.jsonl` is the product's own runtime log and is already documented (D-05). The ranking-probe JSON is a product-tree file rewritten by a test; the suite's own product-tree check reported **0 writes** in both orderings, so either that test is in the unwatched `live` tier or the check has a gap. I did not determine which. **UNVERIFIED** â€” recorded as D-20 (medium).

---

---

---

---

## Sign-off

**Is the repository unchanged apart from this report?**
Yes. I created exactly one file, `GENESIS_FULL_REPOSITORY_REPORT_2026-10-14.md`, in the repo root. Every pinned digest - `phase3_v3_SEALED.json`, `phase3_v4_SEALED.json`, `phase3_v4_SEAL_DIGEST.txt`, `phase3_v3_AUDIT.json`, `SEAL_DIGESTS.txt`, `requirements.txt` and `.env` - is byte-identical to the start of the session (§12). No product code, test, config, corpus or sealed-digest file was modified by me. All audit scripts and logs live outside the repository, in `C:\Users\Muhammad\AppData\Local\Temp\opencode\audit\`.

**Two files in the tree were modified during this session, but not by me.** Running the repo's own test suite (the two fast-gate orderings) rewrote `phase3_ranking_probe_2026-09-28.json` and appended to `genesis_os/approval_audit.jsonl`. That is the product's and the tests' behaviour, recorded as D-20 and D-05.

**Exact test totals.**
- Collected: **3209**
- Fast gate, ordering A (default): **2689 passed, 0 failed, 35 skipped, 0 xfailed, 485 deselected** (319.16s)
- Fast gate, ordering B (`alt_order_plugin`, the repo's own mechanism): **2688 passed, 1 failed, 35 skipped, 0 xfailed, 485 deselected** (321.65s)
- **The two orderings do not agree.** I did not run the `live` tier (485 tests) or the full unfiltered suite, and make no claim about them.
- Reconciliation: 485 live + 2724 fast-tier = 3209 = collected ✓

**Closed-phase ratio: 1 / 32 = 3.1%.** 1 `CLOSED` (Phase 12), 16 `PARTIAL`, 2 `NOT CLOSED` (3, 24), 13 `NOT STARTED`.

**The three findings I am least sure of.**

1. **D-07's causal chain.** I am certain the suite is order-dependent - I measured it in two full runs. I am *not* certain why. The code strongly implicates `monkeypatch.undo()` at `test_browser_degraded_mode.py:230` reverting that test's own TTL setup at `:228`, against a module global that product code assigns directly. But my scratch model of that mechanism failed to reproduce the divergence, and I could not isolate the triggering predecessor. The finding is the failure; the explanation is a hypothesis.

2. **D-01's severity.** I am certain of the behaviour - `provider_names == ['webbrowser']` with `browser_degraded == False`, and the inner 5s `join` timeout returning `False` normally so the outer 10s `wait` sees no pending future. I am less sure how much it matters in production, because on this machine the `webbrowser`-only state is *also* the honest state: selenium's driver is genuinely not usable within the probe's budget, so a consumer might argue there is nothing to report. I judged it a defect because the product's own code distinguishes "probe did not answer" from "provider is absent", and then does not act on that distinction.

3. **The Phase 12 `CLOSED` verdict.** It rests on three real measurements - a forged grant is impossible, a real destructive request was refused, and the boundary blocks escapes and fails closed. But `approval_channel.py` has no import site in `genesis.py`, so I proved the gate *blocks* without proving the approval *channel* is reachable end to end. If the standard is "a user can actually approve something and it then executes", Phase 12 is `PARTIAL` and the closed ratio is **0/32**. I chose `CLOSED` on the narrower reading of the gate ("No model can bypass Genesis policy") and flag the ambiguity rather than hide it.

**This audit recommends no phase closures.** It reports facts and the evidence behind them; the decisions are yours.
