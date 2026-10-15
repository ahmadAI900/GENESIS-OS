"""Section 3 exact prompt verifier."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

tmpdir = tempfile.mkdtemp()
real_csv = Path(tmpdir) / "sales.csv"
real_csv.write_text("a,b,c\n1,2,3\n")

from agents.agent_tools import find_csv_path

r = find_csv_path(f"analyze {real_csv} for trends")
assert r == str(real_csv), f"FAIL: got {r!r}"

r2 = find_csv_path("analyze missing_file.csv")
assert r2 is None, f"FAIL: expected None, got {r2!r}"

print("PASS: find_csv_path isolates the real path correctly")