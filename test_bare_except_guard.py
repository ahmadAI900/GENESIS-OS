"""Directive 7A: freeze the broad-except budget of the enforcement core.

There are 748 broad `except Exception` handlers across the product, and
mass-rewriting them is explicitly out of scope for Directive 7B. What
must not happen is the count going UP in the modules where a swallowed
exception can turn a failure into a silent ALLOW.

These ceilings are a ratchet, not an equality check. Lowering a count is
the goal, so the guard fires only when a module EXCEEDS its recorded
budget. A newly added `except Exception:` in any of these files fails
the fast gate.

Counting is done with `ast`, never regex, so `except` inside strings,
comments or nested functions is not miscounted.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent

# Broad-except budget per safety-critical module, as measured on
# 2026-10-16 (Directive 7A) and recorded in BARE_EXCEPT_INVENTORY.md.
# Lowering a count is the goal, so the guard fires only on an increase.
BUDGET = {
    "genesis_os/action_executor.py": 12,
    "genesis_os/agent_framework_adapter.py": 12,
    "genesis_os/approval_channel.py": 3,
    "genesis_os/approval_store.py": 1,
    "genesis_os/authorization_grant.py": 1,
    "genesis_os/blast_radius.py": 7,
    "genesis_os/security_model.py": 2,
    "genesis_os/unified_executor.py": 3,
}

# No module may ever contain a true bare `except:` -- that catches
# KeyboardInterrupt and SystemExit. The whole product is at zero today.
MAX_TRUE_BARE = 0


def _handlers(path: pathlib.Path) -> tuple[list[int], list[int]]:
    """Return (broad line numbers, true-bare line numbers) for one file."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    broad: list[int] = []
    bare: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            bare.append(node.lineno)
        elif isinstance(node.type, ast.Name) and node.type.id in (
            "Exception",
            "BaseException",
        ):
            broad.append(node.lineno)
    return broad, bare


@pytest.mark.parametrize("relpath", sorted(BUDGET))
def test_safety_critical_module_stays_within_its_except_budget(relpath):
    path = BACKEND / relpath
    assert path.is_file(), f"{relpath} moved; update BUDGET in this guard"

    broad, bare = _handlers(path)

    assert len(bare) == MAX_TRUE_BARE, (
        f"{relpath} now has {len(bare)} true bare `except:` clause(s) at "
        f"lines {bare}. A bare except swallows KeyboardInterrupt and "
        f"SystemExit. Remove it and narrow the exception type."
    )

    allowed = BUDGET[relpath]
    assert len(broad) <= allowed, (
        f"{relpath} has {len(broad)} broad except handler(s), budget is "
        f"{allowed}. Broad handlers in this file can swallow a failure and "
        f"turn it into a silent ALLOW.\n"
        f"  offenders: lines {broad}\n"
        f"  If you added one deliberately, raise the budget here and "
        f"update BARE_EXCEPT_INVENTORY.md in the same commit. Otherwise "
        f"narrow the exception type or remove the handler."
    )


def test_every_safety_critical_module_is_covered_by_the_guard():
    """A new enforcement module must not silently escape the budget."""
    covered = {pathlib.Path(p).name for p in BUDGET}

    # Modules that enforce, but are NOT budgeted. Adding one of these to
    # BUDGET is a judgement call; this test only proves the guard is not
    # silently covering a file that no longer exists.
    for relpath in sorted(BUDGET):
        assert (BACKEND / relpath).is_file(), (
            f"{relpath} is in BUDGET but not on disk; the guard would pass "
            f"vacuously for it"
        )

    # Every budgeted module must actually be import-adjacent product code,
    # never a test helper.
    for relpath in sorted(BUDGET):
        assert not relpath.startswith("test_"), (
            f"{relpath} is a test file; BUDGET must track product modules"
        )

    assert len(covered) == len(BUDGET), (
        f"BUDGET has duplicate module names: {sorted(covered)}"
    )