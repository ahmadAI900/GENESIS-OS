"""Item 3B-3b -- `confirmed` is no longer an authority anywhere.

Before this item the OS managers each carried their own
``if not confirmed: return confirmation_required`` gate, and
``UnifiedExecutor`` injected a blanket ``confirmed=True`` to walk past
them. Authority was therefore split between a boolean in model-visible
JSON and a real AuthorizationGrant.

The single authority is now the executor's blast-radius gate plus a
valid grant. These tests pin the resulting POLICY through the executor,
which is the only live path to the managers:

  (a) a free-target folder.rename / file.move is Tier 2 and proceeds
      without any grant;
  (b) an overwrite is still Tier 1 and returns confirmation_required;
  (c) a Tier 1 op with a valid grant still executes exactly once.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan, attach_authorization
from genesis_os.approval_store import ApprovalStore
from genesis_os.authorization_grant import issue_authorization_grant


class _CountingOSM:
    """Records dispatches so 'did it execute, and how often' is provable."""

    def __init__(self):
        self.calls = []

    def inspect_file(self, path, **k):
        self.calls.append(("inspect_file", path))
        return {"exists": True}

    def inspect_folder(self, path, **k):
        self.calls.append(("inspect_folder", path))
        return {"exists": True}

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a))
            return {
                "success": True, "operation": name, "executed": True,
                "verified": True, "file_exists": False, "folder_exists": False,
                "post_state_matches": True, "path": a[0] if a else None,
                "message": "ok", "result": {},
            }
        return call

    def dispatched(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def tree(tmp_path):
    existing = tmp_path / "existing.txt"
    existing.write_text("irreplaceable", encoding="utf-8")
    free = tmp_path / "free_name.txt"
    src = tmp_path / "source.txt"
    src.write_text("src", encoding="utf-8")
    srcdir = tmp_path / "srcdir"
    srcdir.mkdir()
    return {"existing": existing, "free": free, "src": src,
            "srcdir": srcdir, "root": tmp_path}


def _grant(capability_id, arguments):
    token = ApprovalStore.issue_token(capability_id, dict(arguments))
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    return issue_authorization_grant(
        operation=capability_id, arguments=dict(arguments), token=token
    )


# ----------------------------------------------------------------------
# (a) Tier 2 -- free target proceeds, no grant required
# ----------------------------------------------------------------------
def test_free_target_folder_rename_proceeds_without_a_grant(tree):
    osm = _CountingOSM()
    plan = ActionPlan(
        operation="folder.rename",
        target=str(tree["srcdir"]),
        parameters={"source": str(tree["srcdir"]),
                    "new_name": tree["free"].name},
        capability_id="folder.rename",
    )
    result = ActionExecutor(osm).execute(plan)

    assert result.status != "confirmation_required", (
        "a rename to a FREE target is Tier 2 and must not be gated: "
        f"{result.status}"
    )
    assert osm.dispatched("rename_folder"), (
        f"the free-target rename did not dispatch: {osm.calls}"
    )


def test_free_target_file_move_proceeds_without_a_grant(tree):
    osm = _CountingOSM()
    plan = ActionPlan(
        operation="file.move",
        target=str(tree["src"]),
        parameters={"source": str(tree["src"]),
                    "destination": str(tree["free"])},
        capability_id="file.move",
    )
    result = ActionExecutor(osm).execute(plan)

    assert result.status != "confirmation_required", result.status
    assert osm.dispatched("move_file"), osm.calls


# ----------------------------------------------------------------------
# (b) Tier 1 -- overwrite is still gated
# ----------------------------------------------------------------------
def test_overwriting_rename_is_still_gated(tree):
    osm = _CountingOSM()
    plan = ActionPlan(
        operation="folder.rename",
        target=str(tree["srcdir"]),
        parameters={"source": str(tree["srcdir"]),
                    "new_name": tree["existing"].name},
        capability_id="folder.rename",
    )
    result = ActionExecutor(osm).execute(plan)

    assert result.status == "confirmation_required", (
        f"an overwrite rename must be gated, got {result.status!r}"
    )
    assert not osm.dispatched("rename_folder"), (
        f"an overwriting rename dispatched: {osm.calls}"
    )


def test_overwriting_copy_is_still_gated(tree):
    osm = _CountingOSM()
    plan = ActionPlan(
        operation="file.copy",
        target=str(tree["src"]),
        parameters={"source": str(tree["src"]),
                    "destination": str(tree["existing"])},
        capability_id="file.copy",
    )
    result = ActionExecutor(osm).execute(plan)

    assert result.status == "confirmation_required", result.status
    assert not osm.dispatched("copy_file"), osm.calls


# ----------------------------------------------------------------------
# (c) Tier 1 with a valid grant executes exactly once
# ----------------------------------------------------------------------
def test_tier1_with_a_valid_grant_executes_exactly_once(tree):
    osm = _CountingOSM()
    args = {"source": str(tree["src"]), "destination": str(tree["existing"])}
    plan = attach_authorization(
        ActionPlan(
            operation="file.copy",
            target=str(tree["src"]),
            parameters=dict(args),
            capability_id="file.copy",
        ),
        _grant("file.copy", args),
        arguments=args,
    )
    result = ActionExecutor(osm).execute(plan)

    assert result.status != "confirmation_required", (
        f"a properly granted overwrite was still gated: {result.status}"
    )
    assert len(osm.dispatched("copy_file")) == 1, (
        f"expected exactly one dispatch, got {osm.dispatched('copy_file')}"
    )


# ----------------------------------------------------------------------
# No code path may branch on `confirmed` any more.
# ----------------------------------------------------------------------
@pytest.mark.parametrize("module_path,function", [
    ("genesis_os/filesystem/folder_manager.py", "rename"),
    ("genesis_os/filesystem/folder_manager.py", "move"),
    ("genesis_os/filesystem/folder_manager.py", "delete"),
    ("genesis_os/filesystem/folder_manager.py", "organize"),
    ("genesis_os/safe_file_manager.py", "create"),
    ("genesis_os/safe_file_manager.py", "rename"),
    ("genesis_os/safe_file_manager.py", "delete"),
    ("genesis_os/safe_file_manager.py", "_mutate"),
    ("genesis_os/document_manager.py", "create_docx"),
    ("genesis_os/network_manager.py", "connect_wifi"),
])
def test_manager_functions_do_not_branch_on_confirmed(module_path, function):
    """Structural: the removed gates must not reappear.

    The functions legitimately still ACCEPT a `confirmed` parameter (so
    existing callers keep working); what must be gone is any decision
    that depends on it.
    """
    import ast
    import importlib

    module = importlib.import_module(module_path.rsplit(".", 1)[0].replace("/", "."))
    source = Path(module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == function),
        None,
    )
    assert fn is not None, f"{module_path}:{function} not found"

    offenders = [
        node.lineno for node in ast.walk(fn)
        if isinstance(node, ast.If)
        and "confirmed" in ast.unparse(node.test)
    ]
    assert not offenders, (
        f"{module_path}:{function} still branches on `confirmed` at line(s) "
        f"{offenders}"
    )