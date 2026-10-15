"""
Live demonstration of the Bucket 1 fixes.

Runs an actual FileManager against a real on-disk file copy and move
(same production code path used by genesis.py via safe_file_manager ->
manager.copy/move) and prints the verified/success flags so the user
can see the post-state check in action.
"""

import sys
from pathlib import Path

from genesis_os.filesystem.file_manager import FileManager


def hr(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def main():
    fm = FileManager()
    here = Path(__file__).parent

    src = here / "live_demo_source.txt"
    backup = here / "live_demo_backup.txt"
    moved = here / "live_demo_moved.txt"

    if backup.exists():
        backup.unlink()
    if moved.exists():
        moved.unlink()
    if not src.exists():
        src.write_text(
            "Live demo payload for the Bucket 1 verification fix.\n",
            encoding="utf-8",
        )

    hr("LIVE: file.copy")
    print(f"source      = {src}")
    print(f"destination = {backup}")
    print("Calling FileManager.copy(source, destination) ...")
    result = fm.copy(src, backup)
    print("RESULT:")
    for k, v in result.items():
        print(f"  {k}: {v}")

    hr("LIVE: file.move")
    src2 = here / "live_demo_to_move.txt"
    if src2.exists():
        src2.unlink()
    src2.write_text(
        "This is the file that will be moved in the live demo.\n",
        encoding="utf-8",
    )
    print(f"source      = {src2}")
    print(f"destination = {moved}")
    print("Calling FileManager.move(source, destination) ...")
    result = fm.move(src2, moved)
    print("RESULT:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print(f"source still on disk? {src2.exists()}")
    print(f"destination on disk?  {moved.exists()}")


if __name__ == "__main__":
    main()