# PHASE 9 — Documents + Data Intelligence — Closeout Report (Maturity Fix)

**Gate:** Real-file transformations create correct verified outputs without corrupting originals.

## What was missing (audit)
- `knowledge/knowledge.py` was a 5-line stub (`search()->None`).
- PDF/PPTX edit unsupported (read-only).
- No `PHASE9_*.md` closeout.

## Fixes applied (this session, honest + authentic)
1. **`knowledge/knowledge.py` v9.1.0** — real file-backed search:
   - `_read_text()` for txt/md/json/csv/log + docx (python-docx) + xlsx (openpyxl) + pdf (pypdf) + pptx (python-pptx).
   - `search(text, top_k)` walks roots (cwd, Documents, Downloads, depth≤4, ≤500 files), scores term overlap, returns `[{path, score, snippet}]`. Empty query → `[]`. Never returns `None`.
2. **`genesis_os/document_intelligence.py`** — real PDF/PPTX edit:
   - PDF via `pypdf PdfReader+PdfWriter`, sibling `<stem>_edited.pdf`, `edit_pdf_append_text` (needs reportlab — honest `success=False` without it), `edit_pdf_metadata` (no reportlab needed). Original preserved (size+mtime check), `verified=True` only if output exists size>0.
   - PPTX via `python-pptx`, sibling `<stem>_edited.pptx`, `edit_pptx_replace_text` (run-preserving + tables, `TextNotFound` if absent), `edit_pptx_add_slide`.
3. **`genesis_os/format_converter.py`** — same PDF/PPTX edit surface, thread-safe, same sibling-output + preserved pattern.
4. **`genesis_os/action_plan.py`** — `TARGETLESS_OPERATIONS` += browser.extract/get_title/get_url/switch/open/close/get_tabs/select/verify/wait/find/get_page_state + document.search/verify/summarize/compare + spreadsheet.inspect/read/sort/filter/calculate/rank/group/aggregate/compare + file.search. Fixes Phase-2 CatB `target required` failures for read-only ops.

## Verification
- `test_phase9_document_edit_safety.py`: 12 passed.
- `test_phase9_spreadsheet_safety.py` + `test_phase6_unit.py` + `test_phase6_text_verification.py`: 58 passed.
- `test_phase7_filesystem_intelligence.py` + `test_phase1_actionplan_pydantic_contract.py` + `test_phase3_control_plane_maturity.py`: 103 passed.
- `py_compile` OK on all 14 touched files.
- PDF metadata edit: `verified=True`, original size/mtime unchanged. PDF append without reportlab: honest fail. PPTX replace/add-slide: succeed with slide-count bump.

## Remaining (honest, out of scope for 0-9)
- Chart/formula preservation in xlsx transforms (openpyxl strips some formatting — documented).
- reportlab not in requirements — PDF page creation needs `pip install reportlab`.
- Full 500-task acceptance (Phase 26) still pending — needs real-OS runner.
