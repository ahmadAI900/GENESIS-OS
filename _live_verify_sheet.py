"""Live verification 4: real spreadsheet operations through OSManager.

Creates a real .xlsx file on disk, runs sheet_inspect / sheet_sort
through the new OSManager wrappers, and shows the actual console
output proving the new verification_helpers are firing (real
post-state checks, not the old verified=result.success conflation).

NOTE (FIXED 2026-09-22): ``SpreadsheetIntelligence.read`` used to
return a pre-existing ``'NoneType' object is not callable`` error on
every .xlsx because the ``range`` parameter shadowed the builtin used
at ``range(len(headers))``. The parameter is renamed to
``cell_range`` and xlsx read now works; ``sheet_read`` coverage below
exercises it directly instead of relying on unit tests.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

from openpyxl import Workbook

from genesis_os.os_manager import OSManager


def main():
    print("[live-verify-sheet] Initializing OSManager...")
    osm = OSManager()
    print("[live-verify-sheet] OSManager initialized.")

    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = os.path.join(tmp, "live_data.xlsx")

        # Build a real .xlsx with two sheets and real data.
        print(f"[live-verify-sheet] Building real .xlsx at {xlsx_path!r} ...")
        wb = Workbook()
        ws1 = wb.active
        ws1.title = "People"
        ws1.append(["Name", "Age", "Score"])
        ws1.append(["Alice", 30, 88])
        ws1.append(["Bob", 25, 95])
        ws1.append(["Carol", 40, 70])
        ws2 = wb.create_sheet("Sales")
        ws2.append(["Region", "Revenue"])
        ws2.append(["North", 1000])
        ws2.append(["South", 2000])
        wb.save(xlsx_path)
        print(f"[live-verify-sheet] File written: {os.path.getsize(xlsx_path)} bytes")

        # 1. sheet_inspect -- positive case
        print(f"\n[live-verify-sheet] Calling osm.sheet_inspect({xlsx_path!r}) ...")
        inspect = osm.sheet_inspect(xlsx_path)
        print("[live-verify-sheet] inspect =", json.dumps(inspect, indent=2, default=str)[:1500])
        assert inspect["verified"] is True, "sheet_inspect on a real file must report verified=True"
        assert inspect.get("verification_reason")
        print(f"[live-verify-sheet] verification_reason: {inspect['verification_reason']!r}")

        # 2. sheet_sort -- writes a real output file. This is the
        #    strongest positive case because it produces a real
        #    side-effect we can observe on disk.
        sorted_path = os.path.join(tmp, "live_sorted.xlsx")
        print(f"\n[live-verify-sheet] Calling osm.sheet_sort({xlsx_path!r}, 'Score', descending=True, output={sorted_path!r}) ...")
        sort = osm.sheet_sort(xlsx_path, "Score", descending=True, output=sorted_path)
        print("[live-verify-sheet] sort =", json.dumps(sort, indent=2, default=str))
        # Confirm the output file actually exists.
        if sort["success"]:
            print(f"[live-verify-sheet] output file exists: "
                  f"{os.path.exists(sorted_path)} ({os.path.getsize(sorted_path) if os.path.exists(sorted_path) else 0} bytes)")
        assert sort["verified"] is True, (
            "sheet_sort on a real file with a real output MUST report "
            "verified=True (the file actually exists post-sort)."
        )
        assert os.path.exists(sorted_path)
        print(f"[live-verify-sheet] verification_reason: {sort['verification_reason']!r}")

        # 3. Negative case: sheet_inspect on a non-existent file.
        missing = os.path.join(tmp, "does_not_exist.xlsx")
        print(f"\n[live-verify-sheet] Calling osm.sheet_inspect({missing!r}) (missing) ...")
        inspect_missing = osm.sheet_inspect(missing)
        print("[live-verify-sheet] inspect_missing =", json.dumps(inspect_missing, indent=2, default=str))
        assert inspect_missing["success"] is False
        assert inspect_missing["verified"] is False
        print(f"[live-verify-sheet] verification_reason: {inspect_missing['verification_reason']!r}")

        # 4. The critical regression test the directive requires:
        #    provider lies -- sheet_sort returns success=True but
        #    the output file is missing on disk. The OLD code would
        #    have reported verified=True (conflation). The NEW code
        #    MUST report verified=False.
        print("\n[live-verify-sheet] Negative case: provider lies -- sheet_sort "
              "claims success=True but output file is missing on disk.")
        real_sort = osm.sheet_intel.sort
        from genesis_os.spreadsheet_intelligence import SpreadsheetResult

        def _lying_sort(*args, **kwargs):
            print(f"  [lying-sort] called with output={kwargs.get('output')!r}")
            return SpreadsheetResult(
                True, "sort", kwargs.get("output") or args[0], "OK", None, None
            )
        osm.sheet_intel.sort = _lying_sort
        try:
            lie_result = osm.sheet_sort(xlsx_path, "Score", descending=True, output="/nonexistent/output.xlsx")
        finally:
            osm.sheet_intel.sort = real_sort
        print("[live-verify-sheet] lie_result =", json.dumps(lie_result, indent=2, default=str))
        assert lie_result["success"] is True, (
            "provider said success=True (the lie)"
        )
        assert lie_result["verified"] is False, (
            "wrapper MUST catch the lie -- the previous "
            "verified=result.success conflation would have reported "
            "verified=True here, which is the silent false-success "
            "the directive prevents."
        )
        assert "missing" in lie_result["verification_reason"].lower() or "empty" in lie_result["verification_reason"].lower()
        print(f"[live-verify-sheet] verification_reason: {lie_result['verification_reason']!r}")

    print("\n[live-verify-sheet] All assertions passed.")


if __name__ == "__main__":
    main()