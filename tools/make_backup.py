"""Safe, reproducible backups for a zip-snapshot workflow.

This repository has no version control. The owner's only recovery
mechanism is a zip of `backend/` taken after each significant change. That
makes three properties load-bearing, and this tool exists to guarantee
them:

1. A backup never contains `.env` or any other credential.
2. A backup is verifiable after the fact: every file's SHA-256 is
   written to a manifest beside the zip, and the sealed-corpus digests
   are recomputed into `SEAL_DIGESTS.txt`.
3. A backup is self-describing: the zip name records the gate result it
   was taken under, and the first 8 hex of its own SHA-256, so a file
   can be traced to the state that produced it.

Usage:
    python tools/make_backup.py [--outdir DIR] [--gate-result RESULT]

`--gate-result` should be the verdict of the last `tools/verify_all.py`
run. Without it the tool reads `tools/.last_gate_result` if present, and
otherwise records `unverified` -- deliberately, so an unverified backup
is visible in its filename rather than silently trusted.

Exit codes: 0 success, 1 refused (secret in tree, or post-zip assertion
failed).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

BACKEND = Path(__file__).resolve().parent.parent

EXCLUDED_DIR_NAMES = {
    ".venv", "venv", "__pycache__", ".pytest_cache", ".git", "node_modules",
    ".mypy_cache", ".ruff_cache", ".idea", "dist", "build",
}
EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".zip", ".tmp", ".bak", ".orig",
}
# Never included, at any depth.
NEVER_INCLUDE_NAMES = {".env", ".env.local", "secrets.json", "credentials.json"}
LOG_SUFFIXES = {".log"}
SCRATCH_DIR_NAMES = {"scratch", "scratchpad", "tmp", "temp", "out", "output"}

# Credential patterns. Reused verbatim by the post-zip assertion, so a
# file that slipped past the walk is caught in the archive itself.
SECRET_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("provider_key", re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{16,}\b")),
    ("gh_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token"
        r"|client[_-]?secret)\s*[:=]\s*[\"']?([A-Za-z0-9_\-\.]{12,})\b")),
)

# Values that look like matches but are not credentials.
BENIGN_VALUE = re.compile(
    r"(?i)^(?:|none|null|true|false|changeme|placeholder|your[_-]?\w+|"
    r"xxx+|todo|\.\.\.|test|dummy|example|redacted|secret|password|"
    r"[A-Z_]{3,}|\{\{.*\}\}|%[A-Z_]+%|<[^>]+>|"
    r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*)$"
)
SHA256_HEX = re.compile(r"[0-9a-f]{64}")

# Text we must not scan for secrets: this file names the patterns, and
# corpus/audit JSON is generated data.
SKIP_CONTENT_SCAN = {"make_backup.py"}


def is_excluded(path: Path, root: Path) -> Tuple[bool, str]:
    """Return (excluded, reason). Conservative: errs toward excluding."""
    rel = path.relative_to(root)
    parts = rel.parts
    if path.name in NEVER_INCLUDE_NAMES:
        return True, "credential file"
    for part in parts[:-1]:
        if part in EXCLUDED_DIR_NAMES:
            return True, f"excluded dir {part}"
        if part in SCRATCH_DIR_NAMES:
            return True, f"scratch dir {part}"
    suffix = path.suffix.lower()
    if suffix in EXCLUDED_SUFFIXES:
        return True, f"excluded suffix {suffix}"
    if suffix in LOG_SUFFIXES:
        return True, "log file"
    if path.name.startswith(".env"):
        return True, "dotenv"
    return False, ""


def walk_includable(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        excluded, _ = is_excluded(path, root)
        if excluded:
            continue
        try:
            if path.stat().st_size > 8_000_000:
                continue
        except OSError:
            continue
        yield path


def scan_text_for_secrets(path: Path) -> List[Tuple[str, int]]:
    """Return [(pattern_name, line_no)]. Never returns the value."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:
            line = line[:4000]
        for name, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(1) if match.groups() else match.group(0)
                value = value.strip().strip("\"'")
                if not value or BENIGN_VALUE.match(value):
                    continue
                if SHA256_HEX.fullmatch(value):
                    continue
                found.append((name, lineno))
    return found


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_seal_digests() -> Dict[str, object]:
    """Recompute the sealed-corpus digests from content.

    Recomputes rather than trusting any recorded value, then compares, so
    the output states whether the seal still holds.
    """
    result: Dict[str, object] = {}
    sys.path.insert(0, str(BACKEND))
    digest_path = BACKEND / "phase3_v4_SEAL_DIGEST.txt"
    recorded: Dict[str, str] = {}
    if digest_path.is_file():
        for line in digest_path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(" ")
            recorded[key] = value.strip()

    def digest_of(ordered) -> str:
        payload = json.dumps(ordered, indent=2, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    sealed = BACKEND / "phase3_v4_SEALED.json"
    if sealed.is_file():
        seal = json.loads(sealed.read_text(encoding="utf-8"))
        final4 = seal.get("final4", [])
        dev4 = seal.get("dev4", [])
        result["final4_sha256"] = digest_of(final4)
        result["final4_item_count"] = len(final4)
        result["dev4_sha256"] = digest_of(dev4)
        result["dev4_item_count"] = len(dev4)
        result["final4_matches_recorded"] = (
            result["final4_sha256"] == recorded.get("final4_sha256"))
        result["dev4_matches_recorded"] = (
            result["dev4_sha256"] == recorded.get("dev4_sha256"))

    v3 = BACKEND / "phase3_v3_SEALED.json"
    if v3.is_file():
        blob = json.loads(v3.read_text(encoding="utf-8"))
        items = blob.get("final3", [])
        result["final3_sha256"] = digest_of(items)
        result["final3_item_count"] = len(items)
        result["final3_self_consistent"] = (
            result["final3_sha256"] == blob.get("final3_sha256"))

    try:
        import phase3_v4_corpus as CORPUS

        positives = CORPUS.all_positives()
        negatives = CORPUS.NEGATIVES
        by_category: Dict[str, list] = {}
        for item in positives:
            by_category.setdefault(str(item.get("category", "")), []).append(item)
        dev_keys = set()
        dev_items = []
        for category in sorted(by_category):
            group = sorted(by_category[category],
                           key=lambda i: json.dumps(i, sort_keys=True))
            take = max(1, int(len(group) * 0.25))
            for item in group[:take]:
                key = json.dumps(item, sort_keys=True)
                dev_items.append(item)
                dev_keys.add(key)
        rebuilt = [i for i in positives
                   if json.dumps(i, sort_keys=True) not in dev_keys] + negatives
        ordered = sorted(rebuilt, key=lambda i: json.dumps(i, sort_keys=True))
        result["final4_rebuilt_sha256"] = digest_of(ordered)
        result["final4_rebuilt_item_count"] = len(ordered)
        result["corpus_source_matches_seal"] = (
            result["final4_rebuilt_sha256"] == recorded.get("final4_sha256"))
    except Exception as exc:  # corpus module absent or unreadable
        result["corpus_source_matches_seal"] = f"not checked: {exc}"
    return result


def write_seal_digests(path: Path) -> Dict[str, object]:
    digests = compute_seal_digests()
    lines = ["# Recomputed from CONTENT at backup time.",
             "# Compare with the copy the owner keeps OFF this computer.",
             f"# generated_utc={_dt.datetime.now(_dt.timezone.utc).isoformat()}",
             ""]
    for key in sorted(digests):
        lines.append(f"{key} {digests[key]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return digests


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe backend backup.")
    parser.add_argument("--outdir", default=str(BACKEND.parent / "backups"))
    parser.add_argument("--gate-result", default=None)
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    gate = args.gate_result
    if gate is None:
        marker = BACKEND / "tools" / ".last_gate_result"
        gate = marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
    gate = gate or "unverified"

    # ---- pre-flight secret scan -------------------------------------
    print("scanning for credentials outside .env ...")
    findings: List[Tuple[str, str, int]] = []
    for path in walk_includable(BACKEND):
        if path.name in SKIP_CONTENT_SCAN:
            continue
        if path.suffix.lower() not in {".py", ".md", ".txt", ".json", ".cfg",
                                       ".ini", ".toml", ".yaml", ".yml"}:
            continue
        for name, lineno in scan_text_for_secrets(path):
            findings.append((path.relative_to(BACKEND).as_posix(), name, lineno))
    if findings:
        print(f"REFUSED: {len(findings)} credential-like string(s) in the "
              f"tree. No zip produced.")
        for rel, name, lineno in findings:
            print(f"  {rel}:{lineno}  {name}")
        print("Remove them, or rotate the key if one is live.")
        return 1
    print("  clean")

    # ---- gather files -----------------------------------------------
    files = list(walk_includable(BACKEND))
    manifest: Dict[str, Dict[str, object]] = {}
    for path in files:
        rel = path.relative_to(BACKEND).as_posix()
        manifest[rel] = {"sha256": sha256_file(path),
                         "bytes": path.stat().st_size}

    seal = write_seal_digests(BACKEND / "SEAL_DIGESTS.txt")

    stamp = _dt.date.today().isoformat()
    partial = outdir / f"genesis_backend_{stamp}_{gate}_PENDING.zip"
    zip_path = outdir / f"genesis_backend_{stamp}_{gate}.zip"
    if zip_path.exists():
        zip_path.unlink()

    # Deterministic member order and fixed timestamps so two backups of
    # the same tree are byte-identical.
    fixed_time = (2020, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted(manifest):
            info = zipfile.ZipInfo(rel, date_time=fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (BACKEND / rel).read_bytes())

    # ---- post-zip assertions ----------------------------------------
    with zipfile.ZipFile(partial) as archive:
        names = archive.namelist()
        offenders = [n for n in names
                     if Path(n).name in NEVER_INCLUDE_NAMES
                     or Path(n).name.startswith(".env")]
        if offenders:
            partial.unlink(missing_ok=True)
            print(f"REFUSED: archive contains {offenders}. No zip kept.")
            return 1
        leaked: List[str] = []
        for name in names:
            if Path(name).suffix.lower() not in {".py", ".md", ".txt", ".json"}:
                continue
            if Path(name).name in SKIP_CONTENT_SCAN:
                continue
            try:
                text = archive.read(name).decode("utf-8", errors="replace")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if len(line) > 4000:
                    line = line[:4000]
                for pname, pattern in SECRET_PATTERNS:
                    for match in pattern.finditer(line):
                        value = match.group(1) if match.groups() else match.group(0)
                        value = value.strip().strip("\"'")
                        if not value or BENIGN_VALUE.match(value):
                            continue
                        if SHA256_HEX.fullmatch(value):
                            continue
                        leaked.append(f"{name}:{lineno} {pname}")
        if leaked:
            partial.unlink(missing_ok=True)
            print(f"REFUSED: {len(leaked)} credential-like string(s) inside "
                  f"the archive. No zip kept.")
            for item in leaked[:20]:
                print(f"  {item}")
            return 1

    short = sha256_file(partial)[:8]
    final = outdir / f"genesis_backend_{stamp}_{gate}_{short}.zip"
    partial.rename(final)

    manifest_path = final.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps({
        "archive": final.name,
        "archive_sha256": sha256_file(final),
        "archive_sha256_prefix": short,
        "gate_result": gate,
        "created_local": _dt.datetime.now().isoformat(timespec="seconds"),
        "file_count": len(manifest),
        "seal_digests": seal,
        "files": manifest,
    }, indent=2, sort_keys=True), encoding="utf-8")

    print(f"archive : {final.name}")
    print(f"manifest: {manifest_path.name}")
    print(f"files   : {len(manifest)}")
    print(f"gate    : {gate}")
    print("seal    :")
    for key in sorted(seal):
        print(f"    {key} = {seal[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())