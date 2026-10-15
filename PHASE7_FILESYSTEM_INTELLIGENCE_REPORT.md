# Phase 7 — Filesystem Intelligence Report

## Part 1: Audit of Existing Filesystem Infrastructure

### 1. Known Folders/Aliases — Can Genesis Resolve "my downloads", "desktop", "documents"?

**STATUS: EXISTS — Functional.**

- `FolderTargetProvider` (`folder_target_provider.py:37-51`) maps natural-language folder names to real OS paths via `standard_folders` dict: `"downloads" → ~/Downloads`, `"documents" → ~/Documents`, `"desktop" → ~/Desktop`, plus Pictures, Music, Videos, Workspace.
- `SemanticQueryParser` (`semantic_query_parser.py:86-100`) defines `_LOCATION_ALIASES` mapping 12 natural-language location words to canonical names.
- `FileTargetProvider` (`file_target_provider.py:210-250`) uses location hints to narrow search roots via `_get_effective_roots()`.
- **Evidence**: `test_resolve_my_downloads_folder`, `test_resolve_documents_folder`, `test_resolve_desktop_folder` — all pass with `confidence=0.98`.
- **Disambiguation**: "documents" appears in both `_KNOWN_EXTENSIONS` (file type → `.docx`) and `_LOCATION_ALIASES` (location → Documents folder). When "documents" follows a preposition ("in documents"), the extension is discarded and it's treated as a location. When used as the head noun ("newest documents"), it's treated as a file type. This prevents the "essay in documents" bug where "documents" forced `.docx` extension on all results.

### 2. Newest/Latest/Recency/Content Discovery

**STATUS: EXISTS — Functional.**

- `FileTargetProvider.discover()` (`file_target_provider.py:180-206`) implements recency-first sorting: when `effective_recency` is "newest"/"latest"/"most_recent", candidates are sorted by `mtime` descending with a +0.15 confidence boost for the top candidate.
- `SemanticQueryParser` (`semantic_query_parser.py:172-186`) defines 12 recency patterns: newest, latest, most_recent, yesterday, today, last_week, last_month, etc.
- `_score_file()` (`file_target_provider.py:299-337`) applies time-based scoring: files <1 day old get +0.20, <1 week +0.15, <1 month +0.10.
- **Evidence**: `test_resolve_newest_photo` (mountain_hike.jpg at 12h beats beach_vacation.jpg at 3d), `test_resolve_newest_pdf` (2024 beats 2023), `test_resolve_oldest_photo` (beach at 3d beats mountain at 12h) — all pass.

### 3. Candidate Ranking and Confidence

**STATUS: EXISTS — Functional.**

- `TargetResolver` (`target_resolution.py:55-57`) defines confidence thresholds: `>=0.85` auto-resolves, `0.60-0.849` requires clarification, `<0.60` unresolved.
- `AMBIGUITY_MARGIN = 0.10` detects when top-2 candidates are too close.
- `FileTargetProvider._score_file()` returns `0.0-0.95` range with exact match = 0.96, substring = 0.55+, term overlap = proportional.
- **Evidence**: `test_ambiguous_multiple_pdfs_ranks_by_recency` (2024 ranked above 2023), `test_target_resolver_ambiguity_detection` (clarification required when confidence insufficient), `test_high_confidence_exact_match_resolves` (0.98 auto-resolves) — all pass.

### 4. Existence Validation

**STATUS: EXISTS — Good.**

- `PathSecurity.validate()` (`path_security.py`) checks path existence via `os.path.exists()`.
- `SafeFileManager` validates paths through `PathSecurity` before every read/write/delete operation.
- `FileManager.copy()` (`file_manager.py:821-827`) performs real post-state verification: checks `Path(result).is_file()` AND size matches.
- `FileManager.move()` (`file_manager.py:884-893`) verifies destination exists AND source removed AND size matches.
- **Evidence**: `test_copy_reports_failure_when_destination_missing`, `test_move_reports_failure_when_source_still_present` — both pass.

### 5. Original vs Copy Semantics

**STATUS: EXISTS — Fully functional.**

- `SemanticQueryParser` (`semantic_query_parser.py:200-209`) has concept patterns: "the original" → `concept="original"`, "the copy" → `concept="copy"`, "the backup" → `concept="backup"`.
- `ParsedSemanticQuery.concept` field carries the parsed concept.
- `FileTargetProvider._score_file()` (`file_target_provider.py:285-310`) applies concept-based scoring:
  - **"copy" concept**: penalizes files without copy indicators (`*0.75`) and boosts files with copy indicators (`+0.25`). Files matching `_COPY_PATTERNS` (report_1.docx, report copy.docx) get `*0.55` penalty.
  - **"original" concept**: penalizes files with copy indicators (`*0.55`) and boosts files without them (`+0.10`). Files matching `_COPY_PATTERNS` get `*0.75` penalty.
  - Copy indicators: `_COPY_PATTERNS` regex (e.g., `(?:copy|backup|draft|old|original|v\d+)`, number suffixes) + `_is_copy()` method.
- **Evidence**: `test_resolve_original_file_ranks_above_copy` (report.docx ranked above report_1.docx), `test_resolve_copy_file_ranks_above_original` (report_1.docx ranked above report.docx), `test_resolve_original_concept_parsed`, `test_resolve_copy_concept_parsed` — all pass.

---

## Part 2: Verification-Honesty for Filesystem Capabilities

### Changes Made

**File: `verification_helpers.py`** — Added 7 new verification helpers:

| Helper | Operation | Post-State Signal |
|--------|-----------|-------------------|
| `verify_file_copy()` | file.copy | Destination file exists on disk AND non-empty |
| `verify_file_move()` | file.move | Destination exists AND source removed |
| `verify_file_rename()` | file.rename | New path exists AND old path removed |
| `verify_file_delete()` | file.delete | File no longer exists on disk |
| `verify_folder_create()` | folder.create | Directory exists on disk (`os.path.isdir`) |
| `verify_folder_list()` | folder.inspect | Directory exists AND items payload returned |
| `verify_file_resolve()` | NL resolution | Resolved path actually exists on disk |

**File: `os_manager.py`** — Wired verification helpers into 8 OSManager wrappers:

- `copy_file()` → `_verify_file_copy` (lines 282-288)
- `move_file()` → `_verify_file_move` (lines 290-296)
- `rename_file()` → `_verify_file_rename` (lines 298-304)
- `delete_file()` → `_verify_file_delete` (lines 306-312)
- `create_folder()` → `_verify_folder_create` (lines 318-323)
- `list_folder()` → `_verify_folder_list` (lines 325-330)
- Added new `list_folder()` method (line 325) that wraps `folders.inspect()` with verification

Each wrapper now follows the proven pattern:
```python
result = self.files.X(...)
if _VERIFICATION_HELPERS_AVAILABLE and isinstance(result, dict):
    v = _verify_X(bool(result.get("success")), result.get("path"), result)
    result["verified"] = v["verified"]
    result["verification_reason"] = v["reason"]
return result
```

### Positive/Negative Test Proof

| Capability | Positive Test | Negative Test (Provider Lies) |
|------------|--------------|-------------------------------|
| file.copy | `test_osm_copy_file_positive` ✓ | `test_osm_copy_file_negative_provider_lies` ✓ |
| file.move | `test_osm_move_file_positive` ✓ | `test_osm_move_file_negative_provider_lies` ✓ |
| file.rename | `test_osm_rename_file_positive` ✓ | `test_osm_rename_file_negative_provider_lies` ✓ |
| file.delete | `test_osm_delete_file_positive` ✓ | `test_osm_delete_file_negative_provider_lies` ✓ |
| folder.create | `test_osm_create_folder_positive` ✓ | `test_osm_create_folder_negative_provider_lies` ✓ |
| folder.list | `test_osm_list_folder_positive` ✓ | (tested via verify_folder_list negative) ✓ |
| file.resolve | `test_verify_file_resolve_positive` ✓ | `test_verify_file_resolve_negative_invented_path` ✓ |

**Key negative test pattern**: A monkeypatched provider returns `success=True` but the file doesn't actually exist on disk. The wrapper catches the lie and reports `verified=False` with `verification_reason`.

---

## Part 3: Natural-Language Resolution — Real Pass/Fail Table

15+ genuinely natural filesystem references tested against real disposable files:

| # | Natural Reference | Category | Expected | Result |
|---|-------------------|----------|----------|--------|
| 1 | "my downloads" (folder) | Known alias | Downloads dir | ✓ PASS |
| 2 | "documents" (folder) | Known alias | Documents dir | ✓ PASS |
| 3 | "desktop" (folder) | Known alias | Desktop dir | ✓ PASS |
| 4 | "my most recent photo" | Recency | mountain_hike.jpg (12h) | ✓ PASS |
| 5 | "my latest txt file" | Recency+type | Newest .txt file | ✓ PASS |
| 6 | "the newest PDF" | Recency+type | tax_return_2024.pdf | ✓ PASS |
| 7 | "recent xlsx files" | Recency+type | Spreadsheet files | ✓ PASS |
| 8 | "my oldest photo" | Recency | beach_vacation.jpg (3d) | ✓ PASS |
| 9 | "PDF in downloads" (multiple) | Ranking | 2024 ranked above 2023 | ✓ PASS |
| 10 | "PDF in downloads" (ambiguous) | Ambiguity | Requires clarification | ✓ PASS |
| 11 | "monthly_budget.xlsx" (exact) | Exact match | Budget file | ✓ PASS |
| 12 | "definitely_missing_xyz_file_12345" | Invention guard | 0 candidates | ✓ PASS |
| 13 | "the original project report" | Original concept | concept=original parsed | ✓ PASS |
| 14 | "the copy of the project report" | Copy concept | concept=copy parsed | ✓ PASS |
| 15 | "spreadsheet I was working on" | Compound | Budget xlsx found | ✓ PASS |
| 16 | "PDF about taxes" | Content | Tax PDFs found | ✓ PASS |
| 17 | "my essay in documents" | Location+name | ielts_essay_draft.docx | ✓ PASS |
| 18 | "open my most recent spreadsheet" | Full NL | Budget xlsx found | ✓ PASS |
| 19 | "find that photo I took" | NL with verb | JPG files found | ✓ PASS |
| 20 | "my meeting notes" | Direct name | meeting_notes.txt | ✓ PASS |
| 21 | "the script about analysis" | NL compound | analysis_script.py | ✓ PASS |
| 22 | "PDF" in downloads only | Location hint | Downloads-only results | ✓ PASS |

**Score: 22/22 PASS (100%)**

---

## Part 4: Safety Confirmation Gating

All destructive operations via the natural-language resolution → SafeFileManager path require confirmation:

| Operation | Requires Confirmation | Evidence |
|-----------|----------------------|----------|
| file.delete | YES | `test_resolved_delete_requires_confirmation` ✓ |
| file.move | YES | `test_resolved_move_requires_confirmation` ✓ |
| file.rename | YES | `test_resolved_rename_requires_confirmation` ✓ |
| file.copy | NO (non-destructive) | `test_resolved_copy_does_not_require_confirmation` ✓ |
| folder.create | NO (non-destructive) | `test_resolved_create_folder_no_confirmation` ✓ |

**Confirmed**: A resolved-by-inference target does NOT bypass confirmation. The confirmation gate operates at the SafeFileManager level, independent of whether the path was provided literally or resolved from natural language.

---

## Verification: Suite Count Reconciliation

| Test File | Tests | Status |
|-----------|-------|--------|
| test_phase7_filesystem_intelligence.py (NEW) | 75 | 75 pass |
| test_verification_honesty_sweep.py | 71 | 71 pass |
| test_bucket1_verification_regression.py | 11 | 11 pass |
| test_level3_8_5_semantic_resolution.py | 45 | 45 pass |
| test_file_intelligence_foundation.py | 14 | 14 pass |
| test_level3_7_file_intelligence.py | 15 | 15 pass |
| test_level3_8_4_target_resolution.py | 6 | 6 pass |
| test_context_resolver.py | 10 | 10 pass |
| test_phase2_destructive_capabilities.py | 24 | 24 pass |
| test_level3_4_execution_safety.py | 12 | 12 pass |
| test_level3_5_safety_integration.py | 3 | 3 pass |
| **TOTAL (filesystem-related)** | **286** | **286 pass** |

**Previous baseline**: 1859 tests (V2 report)
**New tests added**: 75 (test_phase7_filesystem_intelligence.py)
**Verified new total**: 1859 + 75 = **1934** (full suite: 1934 passed, 0 failures, 2 pre-existing warnings)

Note: The 75 new tests are additive — no existing tests were modified or removed.

---

## Acceptance Gate Verdict

### "Natural references resolve correctly without invented paths"

**VERDICT: GENUINELY HOLDS — with documented gaps.**

**What works:**
- Known folders/aliases (downloads, documents, desktop) resolve correctly with confidence=0.98
- Recency queries (newest, latest, oldest) resolve to the correct files using real mtime
- Extension-based filtering (PDF, spreadsheet, xlsx) narrows correctly
- Candidate ranking is deterministic and transparent (confidence scores 0.0-0.95)
- **Essay-in-documents ranking** (bug fix): "my essay in documents" now correctly picks `ielts_essay_draft.docx` over `cover_letter.docx` — "documents" is treated as a location, not a file-type keyword
- Original vs copy resolution: "the original project report" ranks the base file above copies; "the copy of the project report" ranks copies above originals
- **Contextual references** (pronouns / anaphora): "that file", "this file", "open it" resolve to the most recently mentioned file via `ConversationContext`; "same folder", "that folder" resolve to the most recently mentioned folder and search within it. The parser detects contextual references via `_CONTEXTUAL_PATTERNS` (9 regex patterns) and `_AMBIGUOUS_PRONOUN_RE`. File pronouns return the resolved file directly (confidence=0.92); folder pronouns search the resolved folder.
- **Plural file-type queries**: "newest documents", "find my recent documents" correctly resolve to `.docx` files. Extension-only queries (no name terms) use recency scoring to pass the 0.40 confidence threshold.
- Ambiguity detection works (clarification required when confidence < 0.85)
- Invented paths return 0 candidates — no hallucinated filesystem objects
- `verify_file_resolve()` catches invented paths at the verification layer

**Remaining gaps (honest assessment):**
1. **Recency-only queries without name terms**: Queries like "my latest download" (where "download" is stripped as a stop word) produce 0 name terms. Extension-only queries now work via the 0.35 base score, but the 0.40 threshold still requires recency boost for some queries.
2. **Non-recursive search**: `FileTargetProvider.discover()` only searches top-level directory entries, not subdirectories. Deeply nested files are not found.

**Accuracy**: 44/44 natural-language references resolved correctly (100% on tested set: 22 self-contained + 2 original-vs-copy + 10 contextual references + 1 essay-ranking regression + 4 plural/type queries + 5 extension-only queries).
**No invented paths**: Confirmed — the system returns empty candidates rather than guessing.
