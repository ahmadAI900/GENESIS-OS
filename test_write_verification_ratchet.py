"""Directive 29A Step 3: ratchet guard against re-introduction of C12 debt.

Scans all product .py files for `success = <literal True>` beside a
computed `verified` (non-literal True/False). This pattern means a write
claims success without binding it to verification evidence -- the exact
C12 debt fixed across 33 sites in 16 modules.

Budget is ZERO for every module: no module may contain this pattern.
The guard uses ast, never regex, so dict literals inside strings or
comments are not miscounted.

Any site that genuinely cannot be verified must use verified=None with a
stated reason (per Directive 29A step 2) and never a bare literal
success=True.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent

# Product modules to scan (tests are excluded). Every one of these must
# have ZERO violations after the Directive 29A fixes.
MODULES = sorted(
    str(p.relative_to(BACKEND))
    for p in BACKEND.rglob("genesis_os/**/*.py")
    if p.is_file()
    and not p.name.startswith("test_")
    and "__pycache__" not in str(p)
) + sorted(
    str(p.relative_to(BACKEND))
    for p in (BACKEND / "agents").rglob("*.py")
    if p.is_file()
    and not p.name.startswith("test_")
    and "__pycache__" not in str(p)
)

# Explicit, justified allowlist for sites that cannot be refactored.
# Format: {relpath: [line_number, ...]}
# After Directive 29A, this is empty: every site was fixed to derive
# success from verification or from dispatch outcome.
ALLOWLIST: dict[str, list[int]] = {}


def _find_violations(path: pathlib.Path) -> list[int]:
    """Return line numbers where success is literal True beside computed verified."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    violations: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {}
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys[k.value] = v

        success = keys.get("success")
        verified = keys.get("verified")

        if success is None or verified is None:
            continue

        # success must not be literal True
        success_is_literal_true = (
            isinstance(success, ast.Constant) and success.value is True
        )
        if not success_is_literal_true:
            continue

        # verified must be computed (not literal True/False/None)
        verified_is_computed = not (
            isinstance(verified, ast.Constant)
            and verified.value in (True, False, None)
        )
        if not verified_is_computed:
            continue

        violations.append(success.lineno)

    return violations


def _parameter_names(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    args = node.args
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return names


def _verified_binding_uses(node: ast.AST) -> tuple[list[int], list[int]]:
    loads: list[int] = []
    bindings: list[int] = [node.lineno] if "verified" in _parameter_names(node) else []

    def walk(child: ast.AST) -> None:
        if child is not node and isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        ):
            return
        if isinstance(child, ast.Name) and child.id == "verified":
            if isinstance(child.ctx, ast.Store):
                bindings.append(child.lineno)
            elif isinstance(child.ctx, ast.Load):
                loads.append(child.lineno)
        for grandchild in ast.iter_child_nodes(child):
            walk(grandchild)

    walk(node)
    return loads, bindings


def _find_verified_binding_violations(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        loads, bindings = _verified_binding_uses(node)
        if not loads:
            continue
        first_binding = min(bindings) if bindings else None
        early_loads = [
            line for line in sorted(loads)
            if first_binding is None or line < first_binding
        ]
        if early_loads:
            violations.append(f"{node.name} loads at {early_loads}")
    return violations


@pytest.mark.parametrize("relpath", MODULES)
def test_no_verified_load_before_its_binding(relpath):
    path = BACKEND / relpath
    violations = _find_verified_binding_violations(path)
    assert not violations, (
        f"{relpath} reads `verified` before binding it in the same function: "
        f"{violations}. This raises NameError/UnboundLocalError on exactly "
        f"the path where no verification happened."
    )


def test_verified_binding_guard_fires_on_scratch_functions(tmp_path):
    scratch = tmp_path / "scratch_verified_binding.py"
    scratch.write_text(
        "def early_load():\n"
        "    return {'verified': verified}\n"
        "    verified = True\n"
        "\n"
        "def missing_binding():\n"
        "    return {'verified': verified}\n"
        "\n"
        "def parameter(verified):\n"
        "    return {'verified': verified}\n"
        "\n"
        "def bound_first():\n"
        "    verified = True\n"
        "    return {'verified': verified}\n",
        encoding="utf-8",
    )

    violations = _find_verified_binding_violations(scratch)

    assert any("early_load" in violation for violation in violations), violations
    assert any("missing_binding" in violation for violation in violations), violations
    assert not any("parameter" in violation for violation in violations), violations
    assert not any("bound_first" in violation for violation in violations), violations


@pytest.mark.parametrize("relpath", MODULES)
def test_no_new_success_true_beside_computed_verified(relpath):
    path = BACKEND / relpath
    allowed = ALLOWLIST.get(relpath, [])
    violations = _find_violations(path)

    unexpected = [v for v in violations if v not in allowed]
    assert not unexpected, (
        f"{relpath} has {len(unexpected)} new success=True beside computed "
        f"verified violation(s) at lines {unexpected}. success must derive "
        f"from verification (success = verified) or dispatch outcome "
        f"(success = 'dispatched'/'local'), never a bare literal True.\n"
        f"If you added one deliberately, add it to ALLOWLIST in this test "
        f"and justify it above."
    )


def test_all_scanned_modules_exist():
    """The guard must not pass vacuously for missing modules."""
    for relpath in MODULES:
        assert (BACKEND / relpath).is_file(), (
            f"{relpath} is in MODULES but not on disk"
        )
