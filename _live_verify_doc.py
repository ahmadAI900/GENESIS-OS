"""Live verification: exercise a real document create+inspect through
the new OSManager wrapper to confirm the verification helper runs
and surfaces the genuine post-state check.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

from genesis_os.os_manager import OSManager


def main():
    print("[live-verify-doc] Initializing OSManager...")
    osm = OSManager()
    print("[live-verify-doc] OSManager initialized.")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "live_doc.txt")
        content = "Hello from verification-honesty-sweep."

        # 1. Create
        print(f"[live-verify-doc] Calling osm.doc_create({path!r}, txt, {content!r})...")
        create_result = osm.doc_create(path, doc_type="txt", content=content)
        print("[live-verify-doc] create_result =", json.dumps(create_result, indent=2, default=str))
        assert "verified" in create_result
        assert create_result["verified"] is True, (
            "after creating a real file the wrapper MUST report verified=True"
        )
        assert os.path.exists(path)
        assert create_result["verification_reason"]
        print(f"[live-verify-doc] verification_reason: {create_result['verification_reason']!r}")

        # 2. Read
        print(f"[live-verify-doc] Calling osm.doc_read({path!r})...")
        read_result = osm.doc_read(path)
        print("[live-verify-doc] read_result =", json.dumps(read_result, indent=2, default=str)[:600])
        assert read_result["verified"] is True
        print(f"[live-verify-doc] verification_reason: {read_result['verification_reason']!r}")

        # 3. Edit
        print(f"[live-verify-doc] Calling osm.doc_edit({path!r}, 'Hello', 'Goodbye')...")
        edit_result = osm.doc_edit(path, "Hello", "Goodbye")
        print("[live-verify-doc] edit_result =", json.dumps(edit_result, indent=2, default=str))
        assert edit_result["verified"] is True
        with open(path, encoding="utf-8") as f:
            assert "Goodbye" in f.read()
        print(f"[live-verify-doc] verification_reason: {edit_result['verification_reason']!r}")

        # 4. Inspect missing file -- wrapper must report verified=False honestly
        missing = os.path.join(tmp, "does_not_exist.txt")
        print(f"[live-verify-doc] Calling osm.doc_inspect({missing!r}) (missing)...")
        inspect_missing = osm.doc_inspect(missing)
        print("[live-verify-doc] inspect_missing =", json.dumps(inspect_missing, indent=2, default=str))
        # The provider's inspect returns success=False for a missing
        # file, so verified follows the provider's failure.
        assert inspect_missing["success"] is False
        assert inspect_missing["verified"] is False

    print("[live-verify-doc] All assertions passed.")


if __name__ == "__main__":
    main()