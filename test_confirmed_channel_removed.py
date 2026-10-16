"""Directive 7C: the vestigial `confirmed` channel must stay gone.

Item 3B-3b removed confirmed-only authority, which left a `confirmed`
parameter stranded on thirteen public manager methods. It was accepted,
documented as "accepted but ignored", and then forwarded around the
codebase purely to be dropped on the floor. Worse, OSManager exposes
`**kwargs` on copy_file/move_file/rename_file/delete_file/
organize_folder/sort_spreadsheet, so `confirmed=True` could travel from a
caller, through a passthrough wrapper, into a manager, and be silently
absorbed -- which reads exactly like a working bypass.

This guard fails if a `confirmed` parameter reappears on any product
function, or if any product call site passes `confirmed=` again.

The guarantee that `confirmed` is NOT authority is asserted properly at
the executor and adapter layers, in test_confirmed_is_not_authority.py
and test_phase2_destructive_capabilities.py. Those tests are the real
regression coverage for the security property; this file only keeps the
dead parameter from being reintroduced.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent

PRODUCT_ROOTS = (
    "genesis_os", "core", "agents", "ai", "memory", "tools", "runtime",
    "knowledge", "brain", "planner", "reasoning", "router", "personality",
    "emotion", "conversation", "collaboration", "internet", "agent_context",
    "integration",
)

# Methods that historically carried the parameter. Kept as documentation
# of where it used to live, and so the failure message can name them.
FORMERLY_DECLARING_CONFIRMED = (
    "genesis_os/document_manager.py:create_docx",
    "genesis_os/filesystem/folder_manager.py:rename",
    "genesis_os/filesystem/folder_manager.py:move",
    "genesis_os/filesystem/folder_manager.py:delete",
    "genesis_os/filesystem/folder_manager.py:organize",
    "genesis_os/network_manager.py:connect_wifi",
    "genesis_os/safe_file_manager.py:create",
    "genesis_os/safe_file_manager.py:copy",
    "genesis_os/safe_file_manager.py:move",
    "genesis_os/safe_file_manager.py:rename",
    "genesis_os/safe_file_manager.py:delete",
    "genesis_os/safe_file_manager.py:_mutate",
    "genesis_os/spreadsheet_manager.py:sort",
)


def _product_files():
    for root in PRODUCT_ROOTS:
        base = BACKEND / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts or "backups" in path.parts:
                continue
            if path.name.startswith("test_"):
                continue
            yield path


def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def test_no_product_function_declares_a_confirmed_parameter():
    offenders = []
    for path in _product_files():
        try:
            tree = _parse(path)
        except SyntaxError as exc:  # pragma: no cover - guard the guard
            offenders.append(f"{path}: unparseable ({exc})")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            if "confirmed" in names:
                rel = path.relative_to(BACKEND).as_posix()
                offenders.append(f"{rel}:{node.lineno} {node.name}()")

    assert not offenders, (
        "A product function declares a `confirmed` parameter again. That "
        "parameter is NOT authority -- it was removed in Item 3B-3b and "
        "deleted in Item 7C. Reintroducing it suggests a confirmation "
        "bypass that does not exist.\n"
        "  offenders:\n    " + "\n    ".join(offenders) + "\n"
        "  It used to live on: " + ", ".join(FORMERLY_DECLARING_CONFIRMED)
    )


def test_no_product_call_site_passes_confirmed_again():
    offenders = []
    for path in _product_files():
        try:
            tree = _parse(path)
        except SyntaxError:  # pragma: no cover - guard the guard
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "confirmed":
                    rel = path.relative_to(BACKEND).as_posix()
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "A product call site passes `confirmed=` again. Since no product "
        "function declares the parameter any more, this can only reach a "
        "`**kwargs` passthrough (OSManager.copy_file and friends) and be "
        "silently absorbed, which reads like a working bypass.\n"
        "  offenders: " + ", ".join(offenders)
    )


@pytest.mark.parametrize("relpath", sorted(FORMERLY_DECLARING_CONFIRMED))
def test_the_former_host_module_still_exists(relpath):
    """The guard must not pass vacuously if a module is moved or deleted."""
    module = relpath.split(":")[0]
    assert (BACKEND / module).is_file(), (
        f"{module} is gone, so the confirmed-parameter guard would silently "
        f"cover nothing. Update PRODUCT_ROOTS/FORMERLY_DECLARING_CONFIRMED."
    )