"""Static signal: what the test files SAY they do, independent of runtime.

The dynamic recorder in `record_probe.py` says what actually happened
during a run. It cannot say what a test would do on a machine where the
GUI stack is missing, a browser is absent, or the test skipped early. The
static scan says what the source contains, before anything runs.

That makes the two signals cross-checkable. A test that statically
imports a GUI library but recorded nothing is either mocking it, or a
recorder blind spot. Either way it is not silently marked `runtime`.

Pure AST, no imports and no execution: importing the file to inspect it
would run its module-level code, which is exactly the thing being
measured.

Usage:

    python tools/static_scan.py [--out docs/fast_gate_static_scan.json]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# A GUI or driver library import is a static signal wherever it appears:
# top level, inside a function, inside a method.
FORBIDDEN_IMPORT_ROOTS = (
    "win32gui", "win32api", "win32con", "win32com", "win32process",
    "pyautogui", "pyautogui_screenshot",
    "selenium", "playwright",
)

# A call that launches or drives something.
FORBIDDEN_CALLS = {
    "subprocess": ("Popen", "run", "call", "check_call", "check_output",
                   "getoutput", "getstatusoutput"),
    "os": ("system", "startfile", "spawnl", "spawnle", "spawnlp", "spawnlpe",
           "spawnv", "spawnve", "spawnvp", "spawnvpe", "execv", "execve",
           "execvp", "popen"),
    "ctypes": ("windll", "cdll", "WinDLL", "CDLL"),
}

# A name bound with `from x import y` before the recorder installed is a
# stale reference that module-attribute wrapping cannot reach.
_STALE_RISK_MODULES = ("win32gui", "win32api", "pyautogui", "selenium",
                       "playwright")

# Constructing any of these imports pyautogui, which probes the keyboard
# with ~110 user32 calls AT IMPORT TIME -- once per process.
#
# That one-shot cost is invisible to the dynamic recorder for every test
# except whichever one happens to trigger the first import. Measured in
# Continuation A5: 19 fast-tier tests construct a GUI provider, and the
# recorded evidence caught NONE of them, because some earlier test had
# already paid the cost. A rule that depends on collection order is not
# a rule, so this signal is STATIC: it does not care who imported first.
GUI_PROVIDER_CONSTRUCTORS = {
    "GUIController", "WindowsGUIProvider", "UIAutomationProvider",
    "GUIObserver", "GUIVerifier",
}


def _dotted(node) -> str:
    """Render `a.b.c` from an AST node, or '' if it is not a name chain."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def scan_source(source: str, filename: str) -> dict:
    """Return the static signal for one file."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return {
            "file": filename,
            "parse_error": f"{exc.__class__.__name__}: {exc}",
            "imports": [],
            "calls": [],
            "from_imports": [],
            "tests": [],
            "signals": [],
        }

    imports: set = set()
    from_imports: list = []
    calls: set = set()
    # nodeid-ish label -> signals observed lexically inside its body
    scoped: list = []

    def visit(node, active_test):
        label = active_test
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_test = node.name.startswith("test")
            if is_test and active_test is None:
                label = node.name
            elif active_test is not None:
                label = f"{active_test}::{node.name}"
        elif isinstance(node, ast.ClassDef):
            if active_test is None:
                label = node.name

        found: list = []

        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS or alias.name in FORBIDDEN_IMPORT_ROOTS:
                    imports.add(alias.name)
                    found.append({"signal": "gui_import", "detail": alias.name})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS or module in FORBIDDEN_IMPORT_ROOTS:
                imports.add(module)
                found.append({"signal": "gui_import", "detail": module})
                for alias in node.names:
                    from_imports.append({"module": module, "name": alias.name})
                    if module.split(".")[0] in _STALE_RISK_MODULES:
                        found.append({
                            "signal": "stale_risk_from_import",
                            "detail": f"from {module} import {alias.name}",
                        })

        if isinstance(node, ast.Call):
            fn = node.func
            dotted = _dotted(fn)
            tail = dotted.rpartition(".")[2] if dotted else ""
            if tail in GUI_PROVIDER_CONSTRUCTORS:
                found.append({"signal": "gui_construct", "detail": dotted})
            if dotted:
                head, _, tail = dotted.partition(".")
                if head in FORBIDDEN_CALLS and tail in FORBIDDEN_CALLS[head]:
                    calls.add(dotted)
                    found.append({"signal": "process_call", "detail": dotted})
                # module.attribute(...) where module is one of the
                # forbidden roots
                if head in FORBIDDEN_IMPORT_ROOTS:
                    calls.add(dotted)
                    found.append({"signal": "gui_call", "detail": dotted})
            elif isinstance(fn, ast.Attribute) and fn.attr in ("windll", "cdll"):
                calls.add(f"ctypes.{fn.attr}")
                found.append({"signal": "process_call",
                              "detail": f"ctypes.{fn.attr}"})

        if found and label:
            scoped.append({"test": label, "signals": found})

        for child in ast.iter_child_nodes(node):
            visit(child, label)

    visit(tree, None)

    return {
        "file": filename,
        "parse_error": None,
        "imports": sorted(imports),
        "from_imports": from_imports,
        "calls": sorted(calls),
        "tests": scoped,
        "signals": sorted({
            s["signal"] for entry in scoped for s in entry["signals"]
        }),
    }


def scan_file(path: Path) -> dict:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"file": path.name, "parse_error": str(exc), "imports": [],
                "calls": [], "from_imports": [], "tests": [], "signals": []}
    return scan_source(source, path.name)


def iter_targets(root: Path):
    """Every test file and every conftest, recursively."""
    seen = set()
    for pattern in ("test_*.py", "*_test.py", "conftest.py"):
        for path in sorted(root.rglob(pattern)):
            if any(part in {".venv", "__pycache__", ".git", "node_modules",
                            ".pytest_cache", "backups"}
                   for part in path.parts):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(BACKEND))
    parser.add_argument("--out", default=str(BACKEND / "docs" /
                                             "fast_gate_static_scan.json"))
    args = parser.parse_args(argv)

    root = Path(args.root)
    files = {}
    errors = {}
    for path in iter_targets(root):
        result = scan_file(path)
        rel = str(path.relative_to(root)).replace("\\", "/")
        result["file"] = rel
        files[rel] = result
        if result["parse_error"]:
            errors[rel] = result["parse_error"]

    payload = {
        "root": str(root),
        "files_scanned": len(files),
        "parse_errors": errors,
        "files": files,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True),
                   encoding="utf-8")

    flagged = {k: v for k, v in files.items() if v["signals"]}
    print(f"scanned {len(files)} files -> {out}")
    print(f"parse errors: {len(errors)}")
    print(f"files with a static signal: {len(flagged)}")
    for name in sorted(flagged):
        print(f"  {name}: {', '.join(flagged[name]['signals'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())