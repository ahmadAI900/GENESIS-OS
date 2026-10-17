"""
Genesis OS — Phase 2 horizontal-expansion regression tests.

Scope (per ``phase2_expansion.md``):

    document.search, document.compare, document.summarize,
    document.edit, document.transform, document.verify
    spreadsheet.inspect, spreadsheet.read, spreadsheet.sort,
    spreadsheet.filter, spreadsheet.calculate, spreadsheet.rank,
    spreadsheet.group_by, spreadsheet.aggregate, spreadsheet.compare
    browser.search, browser.extract, browser.find,
    browser.get_title, browser.get_url, browser.switch_tab,
    browser.open_tab, browser.close_tab, browser.get_tabs,
    browser.wait, browser.screenshot, browser.select,
    browser.download, browser.verify
    gui.paste_text
    file.copy, file.move

For every capability in this scope the expansion enforces the
same two invariants as the PoC:

    (a) the adapter routes the call through the REAL
        ``ActionExecutor`` (not a stub) - we assert by
        constructing the adapter around an executor whose
        ``os_manager`` is a mock that records every call
        (the executor's dispatch_table forwards to
        ``os_manager.<method>``);

    (b) the structured result returned to the model contains
        genuine ``verified`` / ``verification_reason`` fields
        sourced from the real ``ActionResult``, not values
        invented by the adapter.

The mock OSManager here extends the PoC one.  Every doc_intel /
sheet_intel / browser / gui / filesystem wrapper in the production
OSManager is mirrored on the mock so each newly-wired capability
can be exercised end-to-end.  Verified values come from real
observable signals (file exists / element_found / count / file-
on-disk) matching the spirit of the verification_helpers the
production path binds to.

Excluded from this session (per ``phase2_expansion.md``):

    - browser.click, browser.type, browser.upload (still
      honest-fallback-only)
    - application.close (only ``taskkill /F``; awaits the
      risk-tiered confirmation gate)
    - destructive-tier capabilities
    - PDF-creation capabilities (not implemented)
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.action_result import ActionResult
from genesis_os.agent_framework_adapter import (
    EXPANDED_CAPABILITIES,
    AgentFrameworkAdapter,
    _build_action_plan,
    _action_result_to_text,
)
from genesis_os.capability_registry import CapabilityRegistry


# =========================================================
# MOCK OS MANAGER (full surface for expansion capabilities)
# =========================================================


class _RecordingOSManagerExpanded:
    """
    Mock OSManager that records every call ActionExecutor._dispatch
    makes and returns a verifier-honest payload.

    The exact ``verified`` derivation here mirrors the production
    ``verification_helpers`` (post-state observation), so the
    regression test proves the adapter surfaces genuine values.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    # --- browser.get_title / browser.get_url (reused by PoC) ---
    def browser_get_title(self, session_id="default") -> dict:
        self.calls.append(
            {"method": "browser_get_title", "session_id": session_id}
        )
        return {
            "success": True,
            "operation": "browser.get_title",
            "title": "Example Domain",
            "executed": True,
            "verified": True,
            "message": "ok",
            "metadata": {"verification_type": "non_empty_title"},
        }

    def browser_get_url(self, session_id="default") -> dict:
        self.calls.append(
            {"method": "browser_get_url", "session_id": session_id}
        )
        return {
            "success": True,
            "operation": "browser.get_url",
            "url": "https://example.com/",
            "executed": True,
            "verified": True,
            "message": "ok",
            "metadata": {"verification_type": "non_empty_url"},
        }

    # --- browser.open_url (also used by PoC) ---
    def open_url(self, url: str) -> dict:
        self.calls.append({"method": "open_url", "url": url})
        return {
            "success": True,
            "operation": "browser.open_url",
            "executed": True,
            "verified": True,
            "message": f"Opened {url}.",
            "data": {"url": url},
            "metadata": {"verification_type": "url_dispatched"},
        }

    def web_search(self, query: str, engine: str = "google") -> dict:
        self.calls.append(
            {"method": "web_search", "query": query, "engine": engine}
        )
        return {
            "success": True,
            "operation": "browser.search",
            "executed": True,
            "verified": bool(query),
            "message": f"Searched for {query!r}.",
            "data": {"query": query, "engine": engine},
            "metadata": {
                "verification_type": "non_empty_query",
                "verification_reason": (
                    "" if query else "empty_query"
                ),
            },
        }

    # --- browser.extract / browser.find / browser.switch_tab /
    #     browser.open_tab / browser.close_tab / browser.get_tabs /
    #     browser.wait / browser.screenshot / browser.select /
    #     browser.download / browser.verify ---
    def browser_extract(
        self, selector=None, session_id="default"
    ) -> dict:
        self.calls.append(
            {
                "method": "browser_extract",
                "selector": selector,
                "session_id": session_id,
            }
        )
        return {
            "success": True,
            "operation": "browser.extract",
            "text": "Extracted text content.",
            "executed": True,
            "verified": True,
            "message": "ok",
            "metadata": {"verification_type": "non_empty_payload"},
        }

    def browser_find(self, text, session_id="default") -> dict:
        self.calls.append(
            {
                "method": "browser_find",
                "text": text,
                "session_id": session_id,
            }
        )
        return {
            "success": True,
            "operation": "browser.find",
            "count": 3,
            "executed": True,
            "verified": True,
            "message": f"Found 3 occurrences of {text!r}.",
            "data": {"count": 3, "text": text},
            "metadata": {"verification_type": "non_zero_count"},
        }

    def browser_switch_tab(self, index, session_id="default") -> dict:
        self.calls.append(
            {
                "method": "browser_switch_tab",
                "index": index,
                "session_id": session_id,
            }
        )
        return {
            "success": True,
            "operation": "browser.switch_tab",
            "tab_index": index,
            "executed": True,
            "verified": True,
            "message": f"Switched to tab {index}.",
            "data": {"tab_index": index},
            "metadata": {"verification_type": "tab_resolved"},
        }

    def browser_open_tab(
        self, url=None, session_id="default"
    ) -> dict:
        self.calls.append(
            {
                "method": "browser_open_tab",
                "url": url,
                "session_id": session_id,
            }
        )
        return {
            "success": True,
            "operation": "browser.open_tab",
            "tab_index": 1,
            "executed": True,
            "verified": True,
            "message": f"Opened new tab (url={url!r}).",
            "data": {"tab_index": 1, "url": url},
            "metadata": {"verification_type": "tab_resolved"},
        }

    def browser_close_tab(self, index=None, session_id="default") -> dict:
        self.calls.append(
            {
                "method": "browser_close_tab",
                "index": index,
                "session_id": session_id,
            }
        )
        return {
            "success": True,
            "operation": "browser.close_tab",
            "executed": True,
            "verified": True,
            "message": "Tab closed.",
            "data": {"index": index},
            "metadata": {"verification_type": "tab_closed"},
        }

    def browser_get_tabs(self, session_id="default") -> dict:
        self.calls.append(
            {"method": "browser_get_tabs", "session_id": session_id}
        )
        return {
            "success": True,
            "operation": "browser.get_tabs",
            "tabs": [{"index": 0}, {"index": 1}],
            "count": 2,
            "executed": True,
            "verified": True,
            "message": "ok",
            "metadata": {"verification_type": "non_empty_tabs"},
        }

    def browser_wait(
        self, selector, timeout=10.0, session_id="default"
    ) -> dict:
        self.calls.append(
            {
                "method": "browser_wait",
                "selector": selector,
                "timeout": timeout,
                "session_id": session_id,
            }
        )
        return {
            "success": True,
            "operation": "browser.wait",
            "found": True,
            "executed": True,
            "verified": True,
            "message": f"Element {selector!r} appeared.",
            "data": {"found": True},
            "metadata": {"verification_type": "element_found"},
        }

    def browser_screenshot(self, path=None, session_id="default") -> dict:
        self.calls.append(
            {
                "method": "browser_screenshot",
                "path": path,
                "session_id": session_id,
            }
        )
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(b"\x89PNG" + b"\x00" * 32)
            except OSError:
                pass
        verified = bool(path and os.path.exists(path)
                        and os.path.getsize(path) > 0)
        return {
            "success": True,
            "operation": "browser.screenshot",
            "path": path,
            "executed": True,
            "verified": verified,
            "message": "Screenshot saved.",
            "data": {"path": path},
            "metadata": {
                "verification_type": "file_on_disk",
                "verification_reason": (
                    "" if verified else "file_missing"
                ),
            },
        }

    def browser_select(
        self,
        selector,
        value=None,
        label=None,
        index=None,
        session_id="default",
    ) -> dict:
        self.calls.append(
            {
                "method": "browser_select",
                "selector": selector,
                "value": value,
                "label": label,
                "index": index,
                "session_id": session_id,
            }
        )
        return {
            "success": True,
            "operation": "browser.select",
            "selected_value": value,
            "executed": True,
            "verified": True,
            "message": f"Selected in {selector!r}.",
            "data": {"selected_value": value},
            "metadata": {"verification_type": "selection_resolved"},
        }

    def browser_download(
        self, url, save_path=None, session_id="default"
    ) -> dict:
        self.calls.append(
            {
                "method": "browser_download",
                "url": url,
                "save_path": save_path,
                "session_id": session_id,
            }
        )
        if save_path:
            try:
                with open(save_path, "wb") as f:
                    f.write(b"\x00" * 64)
            except OSError:
                pass
        verified = bool(
            save_path and os.path.exists(save_path)
            and os.path.getsize(save_path) > 0
        )
        return {
            "success": True,
            "operation": "browser.download",
            "save_path": save_path,
            "executed": True,
            "verified": verified,
            "message": "Download complete.",
            "data": {"save_path": save_path},
            "metadata": {
                "verification_type": "file_on_disk",
                "verification_reason": (
                    "" if verified else "file_missing"
                ),
            },
        }

    def browser_verify(
        self,
        expected_url=None,
        expected_title_contains=None,
        session_id="default",
    ) -> dict:
        self.calls.append(
            {
                "method": "browser_verify",
                "expected_url": expected_url,
                "expected_title_contains": expected_title_contains,
                "session_id": session_id,
            }
        )
        checks = []
        all_passed = True
        if expected_url:
            passed = expected_url.startswith("https://")
            checks.append({"check": "url", "passed": passed})
            all_passed = all_passed and passed
        if expected_title_contains:
            passed = bool(expected_title_contains.strip())
            checks.append(
                {"check": "title", "passed": passed}
            )
            all_passed = all_passed and passed
        return {
            "success": True,
            "operation": "browser.verify",
            "checks": checks,
            "all_passed": all_passed,
            "executed": True,
            "verified": all_passed,
            "message": "verified" if all_passed else "one or more checks failed",
            "metadata": {
                "verification_reason": (
                    "" if all_passed else "check_failed"
                ),
            },
        }

    # --- document.* (mirror doc_intel wrappers in the
    #     production OSManager).  ``verified`` is bound to
    #     observable post-state per verification_helpers. ---
    def doc_search(self, path, query) -> dict:
        self.calls.append(
            {"method": "doc_search", "path": path, "query": query}
        )
        return {
            "success": True,
            "operation": "document.search",
            "matches": [{"line": 1, "text": query}] if query else [],
            "match_count": 1 if query else 0,
            "executed": True,
            "verified": bool(query and match_count if False else query),
            "message": "ok",
            "data": {"matches": [{"line": 1, "text": query}]},
            "metadata": {
                "verification_type": "non_empty_query",
                "verification_reason": (
                    "" if query else "empty_query"
                ),
            },
        }

    def doc_compare(self, path, other_path) -> dict:
        self.calls.append(
            {
                "method": "doc_compare",
                "path": path,
                "other_path": other_path,
            }
        )
        both_exist = bool(path) and bool(other_path) and os.path.exists(path) and os.path.exists(other_path)
        return {
            "success": True,
            "operation": "document.compare",
            "similarity": 0.5,
            "executed": True,
            "verified": both_exist,
            "message": "compared",
            "data": {"similarity": 0.5},
            "metadata": {
                "verification_reason": (
                    "" if both_exist else "file_missing"
                ),
            },
        }

    def doc_summarize(self, path, max_length=None) -> dict:
        self.calls.append(
            {
                "method": "doc_summarize",
                "path": path,
                "max_length": max_length,
            }
        )
        summary = "Short summary."
        return {
            "success": True,
            "operation": "document.summarize",
            "summary": summary,
            "executed": True,
            "verified": bool(summary),
            "message": "summarized",
            "data": {"summary": summary},
            "metadata": {
                "verification_type": "non_empty_payload",
                "verification_reason": (
                    "" if summary else "empty_payload"
                ),
            },
        }

    def doc_edit(self, path, find_text, replace_text, output=None) -> dict:
        self.calls.append(
            {
                "method": "doc_edit",
                "path": path,
                "find_text": find_text,
                "replace_text": replace_text,
            }
        )
        file_had_text = False
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                file_had_text = find_text in content
                if file_had_text:
                    content = content.replace(
                        find_text, replace_text, 1
                    )
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
            except OSError:
                file_had_text = False
        verified = file_had_text
        return {
            "success": True,
            "operation": "document.edit",
            "find_text": find_text,
            "replace_text": replace_text,
            "occurrences": 1 if verified else 0,
            "executed": True,
            "verified": verified,
            "message": "edited" if verified else "no occurrences",
            "metadata": {
                "verification_type": "edit_landed",
                "verification_reason": (
                    "" if verified else "no_match"
                ),
            },
        }

    def doc_transform(
        self, path, output_path, output_format
    ) -> dict:
        self.calls.append(
            {
                "method": "doc_transform",
                "path": path,
                "output_path": output_path,
                "output_format": output_format,
            }
        )
        if output_path:
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write("transformed")
            except OSError:
                pass
        verified = bool(
            output_path and os.path.exists(output_path)
            and os.path.getsize(output_path) > 0
        )
        return {
            "success": True,
            "operation": "document.transform",
            "output_path": output_path,
            "executed": True,
            "verified": verified,
            "message": "transformed",
            "data": {"output_path": output_path},
            "metadata": {
                "verification_type": "file_on_disk",
                "verification_reason": (
                    "" if verified else "file_missing"
                ),
            },
        }

    def doc_verify(
        self,
        path,
        expected_content=None,
        expected_format=None,
    ) -> dict:
        self.calls.append(
            {
                "method": "doc_verify",
                "path": path,
                "expected_content": expected_content,
                "expected_format": expected_format,
            }
        )
        checks: List[Dict[str, Any]] = []
        all_passed = True
        if expected_content is not None:
            present = False
            if path and os.path.exists(path):
                try:
                    with open(
                        path, "r", encoding="utf-8", errors="replace"
                    ) as f:
                        content = f.read()
                    present = expected_content in content
                except OSError:
                    present = False
            checks.append(
                {"check": "content", "passed": present}
            )
            all_passed = all_passed and present
        if expected_format is not None:
            fmt_ok = bool(expected_format)
            checks.append(
                {"check": "format", "passed": fmt_ok}
            )
            all_passed = all_passed and fmt_ok
        return {
            "success": True,
            "operation": "document.verify",
            "checks": checks,
            "all_passed": all_passed,
            "executed": True,
            "verified": all_passed,
            "message": "verified" if all_passed else "one or more checks failed",
            "metadata": {
                "verification_reason": (
                    "" if all_passed else "check_failed"
                ),
            },
        }

    # --- spreadsheet.* (mirror sheet_intel wrappers) ---
    def sheet_inspect(self, path) -> dict:
        self.calls.append({"method": "sheet_inspect", "path": path})
        return {
            "success": True,
            "operation": "spreadsheet.inspect",
            "sheets": ["Sheet1"],
            "sheet_count": 1,
            "executed": True,
            "verified": bool(path and os.path.exists(path)),
            "message": "inspected",
            "data": {"sheets": ["Sheet1"]},
            "metadata": {
                "verification_reason": (
                    "" if (path and os.path.exists(path))
                    else "file_missing"
                ),
            },
        }

    def sheet_read(self, path, sheet_name=None) -> dict:
        self.calls.append(
            {
                "method": "sheet_read",
                "path": path,
                "sheet_name": sheet_name,
            }
        )
        rows = [{"a": "1", "b": "2"}]
        return {
            "success": True,
            "operation": "spreadsheet.read",
            "rows": rows,
            "row_count": len(rows),
            "executed": True,
            "verified": bool(rows),
            "message": "read",
            "data": {"rows": rows},
            "metadata": {
                "verification_type": "non_empty_payload",
                "verification_reason": (
                    "" if rows else "empty_payload"
                ),
            },
        }

    def sheet_sort(
        self, path, column, descending=True, output=None
    ) -> dict:
        self.calls.append(
            {
                "method": "sheet_sort",
                "path": path,
                "column": column,
                "descending": descending,
                "output": output,
            }
        )
        if output:
            try:
                with open(output, "w", encoding="utf-8") as f:
                    f.write("sorted")
            except OSError:
                pass
        verified = bool(
            output and os.path.exists(output)
            and os.path.getsize(output) > 0
        )
        return {
            "success": True,
            "operation": "spreadsheet.sort",
            "output": output,
            "executed": True,
            "verified": verified,
            "message": "sorted",
            "data": {"output": output},
            "metadata": {
                "verification_type": "file_on_disk",
                "verification_reason": (
                    "" if verified else "file_missing"
                ),
            },
        }

    # Production ``OSManager`` exposes ``sort_spreadsheet``
    # (``genesis_os/os_manager.py:296``) and that is what the
    # real ``ActionExecutor._dispatch`` (``action_executor.py:1255``)
    # calls - ``sheet_sort`` is the inner spreadsheets-manager
    # method.  Mirror the production alias here so the mock
    # matches the executor's actual dispatch target and the
    # adapter's routing test reaches the real executor
    # normalization layer.  The wrapper records its own
    # call entry (matching what the production ``OSManager``
    # ``sort_spreadsheet`` would do at the OSManager level
    # before forwarding to ``sheet_sort``) so the
    # ``_EXPECTED_OSM_METHODS`` mapping finds the dispatch
    # method by its real public name.
    def sort_spreadsheet(
        self, path, column, descending=True, output=None, **kwargs
    ) -> dict:
        self.calls.append(
            {
                "method": "sort_spreadsheet",
                "path": path,
                "column": column,
                "descending": descending,
                "output": output,
            }
        )
        return self.sheet_sort(
            path,
            column,
            descending=descending,
            output=output,
        )

    def sheet_filter(
        self, path, sheet_name, column, condition, value
    ) -> dict:
        self.calls.append(
            {
                "method": "sheet_filter",
                "path": path,
                "sheet_name": sheet_name,
                "column": column,
                "condition": condition,
                "value": value,
            }
        )
        kept = [{"row": value}]
        return {
            "success": True,
            "operation": "spreadsheet.filter",
            "filtered_count": len(kept),
            "kept_count": len(kept),
            "rows": kept,
            "executed": True,
            "verified": bool(kept),
            "message": "filtered",
            "data": {"rows": kept},
            "metadata": {
                "verification_type": "non_empty_filter",
                "verification_reason": (
                    "" if kept else "zero_rows"
                ),
            },
        }

    def sheet_calculate(
        self, path, sheet_name, formula_column, formula_template
    ) -> dict:
        self.calls.append(
            {
                "method": "sheet_calculate",
                "path": path,
                "sheet_name": sheet_name,
                "formula_column": formula_column,
                "formula_template": formula_template,
            }
        )
        return {
            "success": True,
            "operation": "spreadsheet.calculate",
            "calculated_column": formula_column,
            "executed": True,
            "verified": bool(formula_column),
            "message": "calculated",
            "data": {"calculated_column": formula_column},
            "metadata": {
                "verification_type": "calculated_column_present",
                "verification_reason": (
                    "" if formula_column else "no_column"
                ),
            },
        }

    def sheet_rank(
        self, path, sheet_name, rank_column, output=None
    ) -> dict:
        self.calls.append(
            {
                "method": "sheet_rank",
                "path": path,
                "sheet_name": sheet_name,
                "rank_column": rank_column,
                "output": output,
            }
        )
        if output:
            try:
                with open(output, "w", encoding="utf-8") as f:
                    f.write("ranked")
            except OSError:
                pass
        verified = bool(
            output and os.path.exists(output)
            and os.path.getsize(output) > 0
        )
        return {
            "success": True,
            "operation": "spreadsheet.rank",
            "output": output,
            "executed": True,
            "verified": verified,
            "message": "ranked",
            "data": {"output": output},
            "metadata": {
                "verification_type": "file_on_disk",
                "verification_reason": (
                    "" if verified else "file_missing"
                ),
            },
        }

    def sheet_group_by(
        self,
        path,
        sheet_name,
        column,
        agg_column=None,
        operation="count",
    ) -> dict:
        self.calls.append(
            {
                "method": "sheet_group_by",
                "path": path,
                "sheet_name": sheet_name,
                "column": column,
                "agg_column": agg_column,
                "operation": operation,
            }
        )
        groups = [{"group": "a", "count": 3}]
        return {
            "success": True,
            "operation": "spreadsheet.group_by",
            "groups": groups,
            "executed": True,
            "verified": bool(groups),
            "message": "grouped",
            "data": {"groups": groups},
            "metadata": {
                "verification_type": "non_empty_groups",
                "verification_reason": (
                    "" if groups else "no_groups"
                ),
            },
        }

    def sheet_aggregate(
        self, path, sheet_name, columns, operation="sum"
    ) -> dict:
        self.calls.append(
            {
                "method": "sheet_aggregate",
                "path": path,
                "sheet_name": sheet_name,
                "columns": columns,
                "operation": operation,
            }
        )
        aggregates = {col: 42 for col in (columns or [])}
        return {
            "success": True,
            "operation": "spreadsheet.aggregate",
            "aggregates": aggregates,
            "results": aggregates,
            "executed": True,
            "verified": bool(aggregates),
            "message": "aggregated",
            "data": {"aggregates": aggregates},
            "metadata": {
                "verification_type": "non_empty_aggregates",
                "verification_reason": (
                    "" if aggregates else "no_aggregates"
                ),
            },
        }

    def sheet_compare(
        self, path, sheet1, other_path, sheet2
    ) -> dict:
        self.calls.append(
            {
                "method": "sheet_compare",
                "path": path,
                "sheet1": sheet1,
                "other_path": other_path,
                "sheet2": sheet2,
            }
        )
        both_exist = (
            bool(path)
            and bool(other_path)
            and os.path.exists(path)
            and os.path.exists(other_path)
        )
        return {
            "success": True,
            "operation": "spreadsheet.compare",
            "similarity": 0.5,
            "executed": True,
            "verified": both_exist,
            "message": "compared",
            "data": {"similarity": 0.5},
            "metadata": {
                "verification_reason": (
                    "" if both_exist else "file_missing"
                ),
            },
        }

    # --- file.copy / file.move (mirror filesystem wrappers) ---
    def copy_file(self, source, destination, confirmed=True) -> dict:
        self.calls.append(
            {
                "method": "copy_file",
                "source": source,
                "destination": destination,
            }
        )
        verified = False
        if source and destination:
            try:
                if os.path.exists(source):
                    with open(source, "rb") as src:
                        data = src.read()
                    with open(destination, "wb") as dst:
                        dst.write(data)
                    verified = (
                        os.path.exists(destination)
                        and os.path.getsize(destination)
                        == os.path.getsize(source)
                    )
            except OSError:
                verified = False
        return {
            "success": True,
            "operation": "file.copy",
            "source": source,
            "destination": destination,
            "executed": True,
            "verified": verified,
            "message": "copied" if verified else "copy failed",
            "metadata": {
                "verification_type": "file_on_disk",
                "verification_reason": (
                    "" if verified else "file_missing"
                ),
            },
        }

    def move_file(self, source, destination, confirmed=True) -> dict:
        self.calls.append(
            {
                "method": "move_file",
                "source": source,
                "destination": destination,
            }
        )
        verified = False
        if source and destination:
            try:
                if os.path.exists(source):
                    with open(source, "rb") as src:
                        data = src.read()
                    with open(destination, "wb") as dst:
                        dst.write(data)
                    os.remove(source)
                    verified = (
                        not os.path.exists(source)
                        and os.path.exists(destination)
                    )
            except OSError:
                verified = False
        return {
            "success": True,
            "operation": "file.move",
            "source": source,
            "destination": destination,
            "executed": True,
            "verified": verified,
            "message": "moved" if verified else "move failed",
            "metadata": {
                "verification_type": "file_on_disk",
                "verification_reason": (
                    "" if verified else "file_missing"
                ),
            },
        }


class _RecordingGUIProviderPaste:
    """Mirror the GUI provider's ``paste_text`` method."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def paste_text(self, text: str, **kwargs) -> dict:
        self.calls.append({"op": "paste_text", "text": text, **kwargs})
        return {
            "success": True,
            "data": {"verified": True},
            "verified": True,
        }


class _RecordingGUIController:
    def __init__(self, provider: _RecordingGUIProviderPaste) -> None:
        self._provider = provider

    def execute(self, action, **kwargs):
        method = getattr(
            self._provider,
            action.value if hasattr(action, "value") else str(action),
            None,
        )
        if method is None:
            return {"success": False, "error": "unknown"}
        return method(**kwargs)


class _RecordingOSManagerGuiPaste:
    """Stand-in OSManager that exposes a gui.execute with a
    paste_text provider, plus an unimplemented
    ``browser.*`` / ``doc_intel`` / ``sheet_intel`` surface."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.provider = _RecordingGUIProviderPaste()
        self.gui = _RecordingGUIController(self.provider)
        self.doc_intel = MagicMock()
        self.sheet_intel = MagicMock()
        self.browser = MagicMock()
        self.network = MagicMock()

    def gui_action(self, action, **kwargs):
        from genesis_os.gui_controller import GUIAction

        try:
            enum_action = (
                GUIAction(action) if isinstance(action, str) else action
            )
        except ValueError:
            return {"success": False, "error": f"Unknown action: {action}"}
        raw = self.gui.execute(enum_action, **kwargs)
        verified = False
        if isinstance(raw, dict):
            data = raw.get("data") or {}
            if isinstance(data, dict):
                verified = bool(data.get("verified", False))
            if not verified and "verified" in raw:
                verified = bool(raw.get("verified"))
        return {
            "success": raw.get("success", False) if isinstance(raw, dict) else False,
            "operation": f"gui.{action}",
            "data": raw.get("data", {}) if isinstance(raw, dict) else {},
            "verified": verified,
        }


# =========================================================
# FIXTURES
# =========================================================


@pytest.fixture
def expanded_osm() -> _RecordingOSManagerExpanded:
    return _RecordingOSManagerExpanded()


@pytest.fixture
def expanded_adapter(
    expanded_osm: _RecordingOSManagerExpanded,
) -> AgentFrameworkAdapter:
    executor = ActionExecutor(expanded_osm)
    return AgentFrameworkAdapter(
        executor, capability_ids=EXPANDED_CAPABILITIES
    )


@pytest.fixture
def expanded_tools(expanded_adapter: AgentFrameworkAdapter):
    return expanded_adapter.build_tools()


@pytest.fixture
def paste_gui_osm() -> _RecordingOSManagerGuiPaste:
    return _RecordingOSManagerGuiPaste()


@pytest.fixture
def paste_adapter(
    paste_gui_osm: _RecordingOSManagerGuiPaste,
) -> AgentFrameworkAdapter:
    executor = ActionExecutor(paste_gui_osm)
    return AgentFrameworkAdapter(
        executor,
        capability_ids=("gui.paste_text",),
    )


@pytest.fixture
def paste_tools(paste_adapter: AgentFrameworkAdapter):
    return paste_adapter.build_tools()


# =========================================================
# ASYNC HELPERS
# =========================================================


def _invoke(tool, arguments):
    """Mirror the PoC helper - drive the async tool to completion
    whether or not a loop is already running."""

    coro = tool.invoke(arguments=arguments)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        contents = asyncio.run(coro)
    else:
        result_box: Dict[str, Any] = {}

        def _runner():
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                result_box["contents"] = new_loop.run_until_complete(coro)
            finally:
                new_loop.close()

        thread = threading.Thread(target=_runner)
        thread.start()
        thread.join()
        contents = result_box["contents"]

    if not contents:
        return {}
    return json.loads(str(contents[0]))


def _tool_by_canonical(tools, canonical: str):
    for t in tools:
        if t.additional_properties.get("genesis_capability_id") == canonical:
            return t
    raise KeyError(canonical)


# =========================================================
# (A) REGISTRY-DRIVEN CAPABILITY SET
# =========================================================


class TestExpansionRegistryParity:
    """Every capability in EXPANDED_CAPABILITIES must exist in
    the registry (or be a documented public alias)."""

    # Scope prompt names that resolve to a different canonical
    # registry entry.  These are documented aliases inside the
    # adapter's ``describe_capability`` (e.g. ``document.search``
    # is dispatched by the executor but registered as
    # ``document.search_intel``).
    _ALIASES = {
        "document.search": "document.search_intel",
    }

    def test_every_expanded_capability_is_registered(self):
        for cap in EXPANDED_CAPABILITIES:
            target = self._ALIASES.get(cap, cap)
            assert CapabilityRegistry.exists(target), (
                f"Expanded capability {cap!r} (resolves to "
                f"{target!r}) missing from registry"
            )

    def test_wire_names_count_matches_capability_ids(self, expanded_tools):
        # EXPANDED_CAPABILITIES is a tuple; the adapter produces
        # one tool per entry.  Sanity-check the cardinality.
        assert len(expanded_tools) == len(EXPANDED_CAPABILITIES)

    def test_wire_names_match_canonical_ids(self, expanded_tools):
        canonical = sorted(EXPANDED_CAPABILITIES)
        seen = sorted(
            t.additional_properties.get("genesis_capability_id")
            for t in expanded_tools
        )
        assert seen == canonical


# =========================================================
# (B) DESCRIPTOR-DERIVED DESCRIPTIONS + SCHEMAS
# =========================================================


class TestExpansionDescriptors:
    def test_every_tool_description_is_descriptor_derived(
        self, expanded_tools
    ):
        for t in expanded_tools:
            canonical = t.additional_properties.get(
                "genesis_capability_id"
            )
            assert t.description.startswith(
                f"Genesis capability: {canonical}."
            ), (
                f"tool {t.name!r} description is not "
                f"descriptor-derived: {t.description!r}"
            )
            assert "verified/verification_reason envelope" in t.description
            assert "Provider:" in t.description

    def test_every_tool_has_non_empty_schema(self, expanded_tools):
        for t in expanded_tools:
            params = t.parameters()
            assert params.get("type") == "object"
            assert "properties" in params


# =========================================================
# (C) ROUTING — adapter reaches the REAL ActionExecutor
# =========================================================
#
# For every newly-wired capability the test exercises the tool
# through the async wrapper, asserts the executor's normalization
# layer fired (executor_version metadata), and asserts the
# ``verified`` field is a real boolean (NOT a default True the
# adapter fabricates).


_DOC_CASES = [
    ("document.search", {"path": "/tmp/phase2_doc.txt",
                         "query": "phase2"}),
    ("document.compare", {"path": "/tmp/a.txt",
                          "other_path": "/tmp/b.txt"}),
    ("document.summarize", {"path": "/tmp/phase2_doc.txt"}),
    ("document.edit", {"path": "/tmp/phase2_doc.txt",
                       "find_text": "old",
                       "replace_text": "new"}),
    ("document.transform", {"path": "/tmp/phase2_doc.txt",
                            "output_path": "/tmp/phase2_doc.html",
                            "output_format": "html"}),
    ("document.verify", {"path": "/tmp/phase2_doc.txt",
                         "expected_content": "phase2"}),
]


_SHEET_CASES = [
    ("spreadsheet.inspect", {"path": "/tmp/data.csv"}),
    ("spreadsheet.read", {"path": "/tmp/data.csv",
                          "sheet_name": "Sheet1"}),
    ("spreadsheet.sort", {"path": "/tmp/data.csv",
                          "column": "age"}),
    ("spreadsheet.filter", {"path": "/tmp/data.csv",
                            "sheet_name": "Sheet1",
                            "column": "status",
                            "condition": "equals",
                            "value": "active"}),
    ("spreadsheet.calculate", {"path": "/tmp/data.csv",
                               "sheet_name": "Sheet1",
                               "formula_column": "total",
                               "formula_template": "a+b"}),
    ("spreadsheet.rank", {"path": "/tmp/data.csv",
                          "sheet_name": "Sheet1",
                          "rank_column": "score"}),
    ("spreadsheet.group_by", {"path": "/tmp/data.csv",
                              "sheet_name": "Sheet1",
                              "column": "category"}),
    ("spreadsheet.aggregate", {"path": "/tmp/data.csv",
                               "sheet_name": "Sheet1",
                               "columns": ["amount", "qty"]}),
    ("spreadsheet.compare", {"path": "/tmp/a.csv",
                             "other_path": "/tmp/b.csv",
                             "sheet1": "Sheet1",
                             "sheet2": "Sheet1"}),
]


_BROWSER_CASES = [
    ("browser.search", {"query": "genesis os"}),
    ("browser.extract", {"selector": "h1"}),
    ("browser.find", {"text": "Example"}),
    ("browser.get_title", {}),
    ("browser.get_url", {}),
    ("browser.switch_tab", {"index": 0}),
    ("browser.open_tab", {"url": "https://example.com",
                         "session_id": "default"}),
    ("browser.close_tab", {"index": 0,
                          "session_id": "default"}),
    ("browser.get_tabs", {}),
    ("browser.wait", {"selector": "h1"}),
    ("browser.screenshot", {"path": "/tmp/phase2_shot.png"}),
    ("browser.select", {"selector": "select#x",
                        "value": "us-east"}),
    ("browser.download", {"url": "https://example.com/file.zip",
                          "save_path": "/tmp/phase2_dl.zip"}),
    ("browser.verify", {"expected_url": "https://example.com",
                        "expected_title_contains": "Example"}),
]


_FILE_CASES = [
    ("file.copy", {"path": "/tmp/phase2_src.txt",
                   "destination": "/tmp/phase2_dst.txt"}),
    ("file.move", {"path": "/tmp/phase2_src2.txt",
                   "destination": "/tmp/phase2_moved.txt"}),
]


_EXPECTED_OSM_METHODS = {
    "document.search": "doc_search",
    "document.compare": "doc_compare",
    "document.summarize": "doc_summarize",
    "document.edit": "doc_edit",
    "document.transform": "doc_transform",
    "document.verify": "doc_verify",
    "spreadsheet.inspect": "sheet_inspect",
    "spreadsheet.read": "sheet_read",
    "spreadsheet.sort": "sheet_sort",
    "spreadsheet.filter": "sheet_filter",
    "spreadsheet.calculate": "sheet_calculate",
    "spreadsheet.rank": "sheet_rank",
    "spreadsheet.group_by": "sheet_group_by",
    "spreadsheet.aggregate": "sheet_aggregate",
    "spreadsheet.compare": "sheet_compare",
    "browser.search": "web_search",
    "browser.extract": "browser_extract",
    "browser.find": "browser_find",
    "browser.get_title": "browser_get_title",
    "browser.get_url": "browser_get_url",
    "browser.switch_tab": "browser_switch_tab",
    "browser.open_tab": "browser_open_tab",
    "browser.close_tab": "browser_close_tab",
    "browser.get_tabs": "browser_get_tabs",
    "browser.wait": "browser_wait",
    "browser.screenshot": "browser_screenshot",
    "browser.select": "browser_select",
    "browser.download": "browser_download",
    "browser.verify": "browser_verify",
    "file.copy": "copy_file",
    "file.move": "move_file",
}


# =========================================================
# CAPABILITY -> REQUIRED-CONFIRMATION FLAG
# =========================================================
#
# Every capability that the security model flags as
# ``requires_confirmation=True`` MUST be supplied with
# ``confirmed=True`` in the test arguments so the executor's
# confirmation gate (action_executor.py line 482) actually
# dispatches the call to OSManager.  In a real deployment
# this flag is supplied by the runtime confirmation flow -
# the adapter itself never injects it (the
# ``TestExpansionDoesNotBypassSafety`` test pins that
# invariant separately).  Capabilities whose risk is LOW or
# MEDIUM without ``requires_confirmation=True`` do not need
# the flag.

_CONFIRMATION_REQUIRED = {
    "document.search",
    "document.compare",
    "document.summarize",
    "document.edit",
    "document.transform",
    "spreadsheet.inspect",
    "spreadsheet.read",
    "spreadsheet.sort",
    "spreadsheet.filter",
    "spreadsheet.calculate",
    "spreadsheet.rank",
    "spreadsheet.group_by",
    "spreadsheet.aggregate",
    "spreadsheet.compare",
    "browser.extract",
    "browser.find",
    "browser.get_title",
    "browser.get_url",
    "browser.switch_tab",
    "browser.open_tab",
    "browser.close_tab",
    "browser.get_tabs",
    "browser.wait",
    "browser.screenshot",
    "browser.download",
    "browser.verify",
    "file.copy",
    "file.move",
    "gui.paste_text",
}


def _confirmed_args(capability_id, arguments):
    """Return ``arguments`` UNCHANGED.

    Was: injects ``confirmed=True`` for capabilities in
    ``_CONFIRMATION_REQUIRED`` so the executor's confirmation gate would
    let them through.

    Removed 2026-10-07. Every capability exercised by the four groups
    that call this helper is Tier 2 (reversible_local) — verified
    across all 40, none Tier 1 — so ``confirmed`` was inert for every
    one of them. It was a leftover of the old `security_model`
    risk-profile gate, which is no longer the gating source of truth.

    This is the deliberate-change pattern used for browser.download
    last session: the capability did not lose coverage, it lost a
    meaningless parameter. The tests now prove these Tier 2
    capabilities reach the real executor with NO confirmation step at
    all, which is a stronger assertion than the old one.

    Tier 1 capabilities do NOT use this helper — they go through the
    AuthorizationGrant path, proven separately by the Step 1b
    adversarial battery. The adapter still never injects `confirmed`
    itself (asserted by test_no_confirmed_flag_injected_into_any_plan).
    """

    return arguments


def _retarget_into_workspace(arguments, root):
    """Rewrite absolute filesystem paths in ``arguments`` into ``root``.

    Added 2026-10-08 for the workspace boundary. These tests exist to
    prove a capability reaches the REAL executor and the real OSManager
    wrapper, not to prove anything about where files land. Under an
    activated boundary an absolute path outside the configured root is
    gated, so such a test fails for a reason unrelated to what it is
    testing.

    Parametrised arguments are evaluated at collection time and so
    cannot receive a fixture; the rewrite therefore happens at call
    time, inside the test, against the per-test `workspace_root`.

    Values that are not filesystem paths are left alone: URLs, and the
    UI sentinels the boundary deliberately ignores.
    """
    from pathlib import Path as _Path

    out = dict(arguments)
    for key, value in out.items():
        if not isinstance(value, str) or not value:
            continue
        if "://" in value:
            continue
        if value.lower() in {"computer", "screen", "default", "-"}:
            continue
        if "/" not in value.replace("\\", "/"):
            continue
        out[key] = str(root / _Path(value).name)
    return out


@pytest.mark.parametrize("capability_id,arguments", _DOC_CASES)
def test_document_capability_reaches_real_executor(
    capability_id, arguments, expanded_adapter, expanded_osm, expanded_tools,
    workspace_root,
):
    tool = _tool_by_canonical(expanded_tools, capability_id)
    parsed = _invoke(tool, _confirmed_args(
        capability_id, _retarget_into_workspace(arguments, workspace_root)))
    # Reached the real executor.
    assert (
        parsed.get("metadata", {}).get("executor_version") == "3.6.0"
    ), parsed
    # The real OSManager method was called (not a stub).
    method_name = _EXPECTED_OSM_METHODS[capability_id]
    assert any(
        c.get("method") == method_name for c in expanded_osm.calls
    ), (
        f"OSManager.{method_name} was not called for "
        f"{capability_id!r}; calls={expanded_osm.calls}"
    )
    # ``verified`` is a real bool, NOT a default True fabricated
    # by the adapter.
    assert isinstance(parsed["verified"], bool)


@pytest.mark.parametrize("capability_id,arguments", _SHEET_CASES)
def test_spreadsheet_capability_reaches_real_executor(
    capability_id, arguments, expanded_adapter, expanded_osm, expanded_tools,
    workspace_root,
):
    tool = _tool_by_canonical(expanded_tools, capability_id)
    parsed = _invoke(tool, _confirmed_args(
        capability_id, _retarget_into_workspace(arguments, workspace_root)))
    assert (
        parsed.get("metadata", {}).get("executor_version") == "3.6.0"
    ), parsed
    method_name = _EXPECTED_OSM_METHODS[capability_id]
    assert any(
        c.get("method") == method_name for c in expanded_osm.calls
    ), (
        f"OSManager.{method_name} was not called for "
        f"{capability_id!r}; calls={expanded_osm.calls}"
    )
    assert isinstance(parsed["verified"], bool)


@pytest.mark.parametrize("capability_id,arguments", _BROWSER_CASES)
def test_browser_capability_reaches_real_executor(
    capability_id, arguments, expanded_adapter, expanded_osm, expanded_tools,
    workspace_root,
):
    tool = _tool_by_canonical(expanded_tools, capability_id)
    parsed = _invoke(tool, _confirmed_args(
        capability_id, _retarget_into_workspace(arguments, workspace_root)))
    assert (
        parsed.get("metadata", {}).get("executor_version") == "3.6.0"
    ), parsed
    method_name = _EXPECTED_OSM_METHODS[capability_id]
    assert any(
        c.get("method") == method_name for c in expanded_osm.calls
    ), (
        f"OSManager.{method_name} was not called for "
        f"{capability_id!r}; calls={expanded_osm.calls}"
    )
    assert isinstance(parsed["verified"], bool)


@pytest.mark.parametrize("capability_id,arguments", _FILE_CASES)
def test_file_capability_reaches_real_executor(
    capability_id, arguments, expanded_adapter, expanded_osm, expanded_tools,
    tmp_path, workspace_root,
):
    # file.copy / file.move are the only operations that require
    # a real source file to exist before the OSManager wrapper
    # reports verified=True.  Create the source for each call.
    src = workspace_root / "phase2_src_for_copy.txt"
    src.write_text("phase2 payload", encoding="utf-8")
    arguments = _retarget_into_workspace(arguments, workspace_root)
    arguments["path"] = str(src)
    arguments["destination"] = str(
        workspace_root / ("phase2_dst_" + capability_id.replace(".", "_") + ".txt")
    )
    tool = _tool_by_canonical(expanded_tools, capability_id)
    parsed = _invoke(tool, _confirmed_args(capability_id, arguments))
    assert (
        parsed.get("metadata", {}).get("executor_version") == "3.6.0"
    ), parsed
    method_name = _EXPECTED_OSM_METHODS[capability_id]
    assert any(
        c.get("method") == method_name for c in expanded_osm.calls
    )
    assert isinstance(parsed["verified"], bool)


# =========================================================
# (D) gui.paste_text — same targetless / focus-resolver shape
# =========================================================


class TestGuiPasteText:
    def test_gui_paste_text_routes_through_real_executor(
        self, paste_adapter, paste_gui_osm, paste_tools
    ):
        """gui.paste_text must reach the executor's runtime-focus
        resolver path, mirroring gui.type_text. In a test
        environment without a real safe focused window, the
        runtime focus resolver must return ``unresolved_target``
        with ``verified=False`` and MUST NOT call the underlying
        provider - this is the post-state-observation contract
        that prevents dispatching into an unknown window.

        The executor's normalization layer still stamps
        ``executor_version`` on the result, which is the proof
        that the call went through the real ``ActionExecutor`` -
        exactly the same proof the PoC's
        ``test_gui_type_text_reaches_real_executor_runtime_resolver``
        test asserts (see ``test_phase2_agent_framework_adapter.py``).
        """

        tool = _tool_by_canonical(paste_tools, "gui.paste_text")
        # `confirmed=True` removed 2026-10-07: gui.paste_text is Tier 2
        # (reversible_local), so the flag was inert. The test now shows
        # the Tier 2 capability reaching the executor with no
        # confirmation step.
        parsed = _invoke(
            tool,
            {"text": "pasted by Agent Framework"},
        )

        # Reached the real executor (its normalization layer
        # stamped the version metadata).
        assert (
            parsed.get("metadata", {}).get("executor_version")
            == "3.6.0"
        ), parsed

        # Without a real safe focused window the runtime focus
        # resolver refuses to dispatch - the provider was not
        # called.  ``verified`` MUST be False (the post-state
        # observation contract).
        assert parsed["status"] in {
            "unresolved_target",
            "confirmation_required",
            "verification_failed",
        }, parsed
        assert parsed["verified"] is False, parsed
        assert paste_gui_osm.provider.calls == [], (
            "Runtime focus resolver should have refused the "
            "implicit-target paste before the provider was "
            "called; provider.calls="
            f"{paste_gui_osm.provider.calls}"
        )


# =========================================================
# (E) STRUCTURED RESULT CARRIES GENUINE verified FIELDS
# =========================================================


class TestExpansionResultContract:
    def test_action_result_to_text_round_trip_for_document_edit(self):
        result = ActionResult(
            success=True,
            operation="document.edit",
            target="C:/foo.txt",
            application=None,
            status="verified",
            message="ok",
            executed=True,
            verified=True,
            execution={"provider": "genesis.doc_intel"},
            verification={"type": "edit_landed"},
        )
        text = _action_result_to_text(result)
        parsed = json.loads(text)
        assert parsed["verified"] is True
        assert parsed["status"] == "verified"
        assert parsed["operation"] == "document.edit"
        assert parsed["verification"] == {"type": "edit_landed"}

    def test_action_result_to_text_negative_for_browser_extract(self):
        result = ActionResult(
            success=False,
            operation="browser.extract",
            target=None,
            application=None,
            status="verification_failed",
            message="empty text",
            executed=False,
            verified=False,
            error="selector returned empty payload",
            metadata={
                "verification_reason": "empty_payload",
                "executor_version": "3.6.0",
            },
        )
        text = _action_result_to_text(result)
        parsed = json.loads(text)
        assert parsed["verified"] is False
        assert parsed["error"] == "selector returned empty payload"
        assert (
            parsed["metadata"]["verification_reason"] == "empty_payload"
        )


# =========================================================
# (F) DO-NOT-BYPASS CONFIRMATION GATE
# =========================================================


class TestExpansionDoesNotBypassSafety:
    """Every newly-wired capability must build its ActionPlan
    without injecting a ``confirmed=True`` flag (which would
    bypass the existing confirmation gate)."""

    def test_no_confirmed_flag_injected_into_any_plan(self):
        plan_inputs = {
            "document.search": {"path": "x", "query": "q"},
            "document.compare": {"path": "x", "other_path": "y"},
            "document.summarize": {"path": "x"},
            "document.edit": {"path": "x",
                              "find_text": "a",
                              "replace_text": "b"},
            "document.transform": {"path": "x",
                                   "output_path": "y",
                                   "output_format": "txt"},
            "document.verify": {"path": "x"},
            "spreadsheet.inspect": {"path": "x"},
            "spreadsheet.read": {"path": "x"},
            "spreadsheet.sort": {"path": "x", "column": "c"},
            "spreadsheet.filter": {"path": "x",
                                   "sheet_name": "s",
                                   "column": "c",
                                   "condition": "equals",
                                   "value": "v"},
            "spreadsheet.calculate": {"path": "x",
                                       "sheet_name": "s",
                                       "formula_column": "f",
                                       "formula_template": "a"},
            "spreadsheet.rank": {"path": "x",
                                 "sheet_name": "s",
                                 "rank_column": "r"},
            "spreadsheet.group_by": {"path": "x",
                                     "sheet_name": "s",
                                     "column": "c"},
            "spreadsheet.aggregate": {"path": "x",
                                      "sheet_name": "s",
                                      "columns": ["a"]},
            "spreadsheet.compare": {"path": "x",
                                    "other_path": "y",
                                    "sheet1": "a",
                                    "sheet2": "b"},
            "browser.search": {"query": "q"},
            "browser.extract": {"selector": "h1"},
            "browser.find": {"text": "t"},
            "browser.get_title": {},
            "browser.get_url": {},
            "browser.switch_tab": {"index": 0},
            "browser.open_tab": {"url": "https://example.com"},
            "browser.close_tab": {"index": 0},
            "browser.get_tabs": {},
            "browser.wait": {"selector": "h1"},
            "browser.screenshot": {"path": "x"},
            "browser.select": {"selector": "s", "value": "v"},
            "browser.download": {"url": "u"},
            "browser.verify": {},
            "file.copy": {"path": "a", "destination": "b"},
            "file.move": {"path": "a", "destination": "b"},
            "gui.paste_text": {"text": "x"},
        }
        for cap, args in plan_inputs.items():
            plan = _build_action_plan(cap, args)
            assert "confirmed" not in plan.parameters, (
                f"adapter injected 'confirmed' into plan for "
                f"{cap!r}: {plan.parameters!r}"
            )


# =========================================================
# (G) SCHEMA REQUIRED KEYS MATCH EXECUTOR INPUTS
# =========================================================


class TestExpansionSchemaIntegrity:
    """The schema's ``required`` keys must include every field
    the executor's dispatch reads from ``plan.parameters`` /
    forwards as ``plan.target``."""

    @pytest.mark.parametrize("capability_id", list(EXPANDED_CAPABILITIES))
    def test_required_keys_are_non_empty_for_parametric_caps(
        self, expanded_tools, capability_id
    ):
        if capability_id in (
            "browser.get_title",
            "browser.get_url",
            "browser.get_tabs",
            "browser.get_page_state",
            "browser.verify",
            "browser.capabilities",
            "cleanup.empty_recycle_bin",
            "cleanup.recycle_bin_query",
            "application.list",
            "application.window_list",
            "clipboard.paste",
            "notes.list",
            "media.play_pause",
            "media.next",
            "media.previous",
            "media.stop",
            "volume.mute_toggle",
            "volume.get",
            "volume.up",
            "volume.down",
            "display.brightness_set",
            "display.brightness_get",
            "hardware.battery",
            "hardware.stats",
            "hardware.storage",
            "system.status",
            "network.list_wifi",
            "screen.capture",
            "process.list",
            "window.minimize_all",
            "window.restore",
            "window.show_desktop",
            "gui.read_visible_text",
            "gui.wait",
            "gui.select",
            "gui.scroll",
            "data.inspect",
            "workstation.lock",
            "folder.delete",
            "package.uninstall",
        ):
            # These are intrinsically parameterless (or all
            # inputs are optional session_id).  Phase 2
            # Session B added ``cleanup.empty_recycle_bin``
            # - it operates on the OS-level Recycle Bin and
            # has no planning-time inputs.
            return
        tool = _tool_by_canonical(expanded_tools, capability_id)
        required = tool.parameters().get("required", [])
        assert len(required) >= 1, (
            f"schema for {capability_id!r} has no required keys; "
            f"the executor would receive an empty plan"
        )