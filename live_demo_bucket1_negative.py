"""
Live negative test: simulate shutil "succeeding" while the destination
has been corrupted / removed post-write. The post-state verification
in FileManager.copy/move must report success=False with verified=False.
"""

import shutil
from pathlib import Path

from genesis_os.filesystem.file_manager import FileManager


def main():
    fm = FileManager()
    here = Path(__file__).parent
    src = here / "live_neg_source.txt"
    dest = here / "live_neg_target.txt"
    if not src.exists():
        src.write_text("negative-test payload\n", encoding="utf-8")
    if dest.exists():
        dest.unlink()

    print("=== NEGATIVE LIVE: file.copy ===")
    real_copy2 = shutil.copy2

    def copy_then_delete(src_arg, dst_arg, *a, **kw):
        result = real_copy2(src_arg, dst_arg, *a, **kw)
        if Path(result).exists():
            Path(result).unlink()
            print(
                "  [simulated] shutil returned without error, "
                "but destination was wiped before verification."
            )
        return result

    shutil.copy2 = copy_then_delete
    try:
        result = fm.copy(src, dest)
    finally:
        shutil.copy2 = real_copy2

    print("RESULT:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print(f"  destination on disk now? {dest.exists()}")


if __name__ == "__main__":
    main()