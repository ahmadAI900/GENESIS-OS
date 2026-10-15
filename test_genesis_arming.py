"""Part A: explicit arming.

Until F5 follow-up 1, whether the workspace boundary was enforced
depended on whether `AIEngine.__init__` happened to call
`load_dotenv()`. A bare executor process was UNARMED while a GenesisOS
runtime was also UNARMED -- despite `.env` declaring a root.

These tests pin the replacement: loading is explicit, deterministic,
idempotent, never overrides an existing environment variable, and the
resulting state is loud.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from genesis_os.genesis_config import (
    load_genesis_config,
    reset_for_tests,
    was_loaded,
)
from genesis_os.workspace_boundary import (
    WORKSPACE_ROOT_ENV,
    BoundaryConfigurationError,
    boundary_banner_text,
    boundary_is_enforced,
    path_is_protected,
    workspace_root,
)

BACKEND = Path(__file__).resolve().parent
PYTHON = sys.executable


# ---------------------------------------------------------------------------
# The coupling that existed before, recorded so it cannot come back.
# ---------------------------------------------------------------------------
FRESH_PROBE = (
    "import os, sys, json\n"
    f"sys.path.insert(0, {str(BACKEND)!r})\n"
    "from genesis_os.workspace_boundary import boundary_is_enforced, workspace_root\n"
    "out = {'enforced': boundary_is_enforced()}\n"
    "r = workspace_root()\n"
    "out['root'] = str(r) if r else None\n"
    "print(json.dumps(out))\n"
)

# Each test decides the environment; the probe must not second-guess it.
UNSET = ("import os\n",
         "import os\nos.environ.pop('GENESIS_WORKSPACE_ROOT', None)\n")


def _fresh(prelude="", dotenv_path=None):
    env = dict(os.environ)
    env.pop(WORKSPACE_ROOT_ENV, None)
    if dotenv_path is not None:
        # The fresh process must not inherit a developer's real .env; the
        # probe loads exactly the file this test created.
        env["GENESIS_TEST_DOTENV"] = str(dotenv_path)
    proc = subprocess.run(
        [PYTHON, "-c", prelude + FRESH_PROBE],
        capture_output=True, text=True, cwd=str(BACKEND), env=env, timeout=180,
    )
    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
    assert lines, f"no output: {proc.stderr[-400:]}"
    import json

    return json.loads(lines[-1])


def _fresh_preset(prelude=""):
    """Fresh process with the variable already exported."""
    env = dict(os.environ)
    env[WORKSPACE_ROOT_ENV] = str(BACKEND.parent / ".genesis_workspace")
    proc = subprocess.run(
        [PYTHON, "-c", prelude + FRESH_PROBE],
        capture_output=True, text=True, cwd=str(BACKEND), env=env, timeout=180,
    )
    import json

    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
    assert lines, f"no output: {proc.stderr[-400:]}"
    return json.loads(lines[-1])


def test_importing_the_executor_does_not_arm_the_boundary():
    """The defect: arming must not be a side effect of unrelated imports."""
    result = _fresh(
        "from genesis_os.action_executor import ActionExecutor\n" + UNSET[1]
    )
    assert result["enforced"] is False, (
        "constructing an executor armed the boundary; arming must be explicit"
    )


def _write_temp_dotenv(tmp_path):
    """A throwaway `.env` declaring a workspace root, on any machine.

    Returns (path, workspace_root_value). The root points INSIDE tmp_path
    so the boundary, once armed by an explicit load, is a real existing
    directory -- no reliance on whatever the developer happens to have
    configured, and no skip when there is no `.env` on the machine.
    """
    workspace = tmp_path / "gen_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"{WORKSPACE_ROOT_ENV}={workspace.as_posix()}\n", encoding="utf-8"
    )
    return dotenv, workspace


def test_dotenv_alone_does_not_arm_the_boundary(tmp_path):
    """`.env` declaring a root must not arm anything implicitly.

    Runs on any clean checkout: the test creates its OWN `.env` and points
    the fresh process at it. The file exists and declares a root, but the
    subprocess never calls ``load_genesis_config``, so the boundary must
    stay unarmed -- arming is explicit, not a side effect of a file being
    present on disk.
    """
    dotenv, _workspace = _write_temp_dotenv(tmp_path)
    # UNSET clears any inherited GENESIS_*; GENESIS_TEST_DOTENV tells the
    # probe where the throwaway file is, but nothing loads it.
    result = _fresh(UNSET[1], dotenv_path=dotenv)
    assert result["enforced"] is False, (
        "a `.env` file was present and declared a root, but nothing called "
        "load_genesis_config(); the boundary must stay unarmed"
    )


def test_explicit_load_arms_the_boundary_in_a_fresh_process(tmp_path):
    """This is the fix, proven end to end in a real process.

    Runs on any clean checkout: the test creates its OWN `.env` and loads
    exactly that file in a fresh interpreter, so it neither skips on a
    machine without a real `.env` nor depends on the developer's own
    configuration.
    """
    dotenv, workspace = _write_temp_dotenv(tmp_path)
    result = _fresh(
        UNSET[1] +
        "import os\n"
        "from genesis_os.genesis_config import load_genesis_config\n"
        "load_genesis_config(os.environ['GENESIS_TEST_DOTENV'])\n",
        dotenv_path=dotenv,
    )
    assert result["enforced"] is True, (
        "an explicit load_genesis_config() on a file declaring a root must "
        "arm the boundary"
    )
    assert result["root"], "an armed boundary must report a root"
    assert result["root"].replace("\\", "/").rstrip("/") == \
        workspace.as_posix().rstrip("/"), (
        f"the boundary resolved to {result['root']!r}, expected the root "
        f"declared in the temporary .env ({workspace})"
    )


def test_bare_process_with_variable_preset_is_armed():
    """Operator-set variable works without any loader."""
    result = _fresh_preset()
    assert result["enforced"] is True


# ---------------------------------------------------------------------------
# Loader semantics.
# ---------------------------------------------------------------------------
def test_loader_is_idempotent(tmp_path, monkeypatch):
    reset_for_tests()
    dotenv = tmp_path / ".env"
    dotenv.write_text("GENESIS_IDEMPOTENCY_PROBE=one\n", encoding="utf-8")
    monkeypatch.delenv("GENESIS_IDEMPOTENCY_PROBE", raising=False)

    first = load_genesis_config(dotenv)
    assert "GENESIS_IDEMPOTENCY_PROBE" in first["changed"]
    assert first["already_loaded"] is False
    assert was_loaded() is True

    second = load_genesis_config(dotenv)
    assert second["changed"] == []
    assert second["already_loaded"] is True


def test_loader_never_overrides_an_existing_environment_variable(
    tmp_path, monkeypatch
):
    """An operator's exported root must not be overruled by .env."""
    reset_for_tests()
    dotenv = tmp_path / ".env"
    dotenv.write_text("GENESIS_OVERRIDE_PROBE=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("GENESIS_OVERRIDE_PROBE", "from_environment")

    result = load_genesis_config(dotenv)
    assert os.environ["GENESIS_OVERRIDE_PROBE"] == "from_environment"
    assert result["changed"] == []
    assert "GENESIS_OVERRIDE_PROBE" in result["skipped"]


def test_missing_dotenv_is_not_an_error(tmp_path, monkeypatch):
    reset_for_tests()
    result = load_genesis_config(tmp_path / "definitely_not_here.env")
    assert result["changed"] == []
    assert result["path"] is not None


def test_loader_does_not_touch_unrelated_variables(tmp_path, monkeypatch):
    reset_for_tests()
    dotenv = tmp_path / ".env"
    dotenv.write_text("PATH_SHOULD_NOT_BE_TOUCHED=/evil\nGENESIS_OK=1\n",
                      encoding="utf-8")
    monkeypatch.setenv("PATH_SHOULD_NOT_BE_TOUCHED", "/real")
    load_genesis_config(dotenv)
    assert os.environ["PATH_SHOULD_NOT_BE_TOUCHED"] == "/real"
    assert os.environ["GENESIS_OK"] == "1"


# ---------------------------------------------------------------------------
# Banner.
# ---------------------------------------------------------------------------
def test_banner_reports_inactive_when_unset(monkeypatch):
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
    text = boundary_banner_text()
    assert text == (
        "Workspace boundary: INACTIVE (GENESIS_WORKSPACE_ROOT not set)"
    )


def test_banner_reports_active_with_root(monkeypatch, tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(root))
    text = boundary_banner_text()
    assert text.startswith("Workspace boundary: ACTIVE (root=")
    assert str(root) in text


@pytest.mark.parametrize("broken", ["", "   ", "Z:\\" + "x" * 6000])
def test_banner_never_claims_inactive_when_failing_closed(monkeypatch, broken):
    """Reporting INACTIVE would misrepresent a system that refuses work."""
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, broken)
    text = boundary_banner_text()
    assert not text.startswith("Workspace boundary: INACTIVE"), text
    assert "ACTIVE" in text
    assert boundary_is_enforced() is True


def test_cli_startup_announces_state(monkeypatch, capsys):
    """genesis.show_startup() must announce it."""
    from genesis import announce_boundary_state

    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(BACKEND.parent / ".genesis_workspace"))
    banner = announce_boundary_state()
    assert banner in capsys.readouterr().out
    assert "Workspace boundary:" in banner


# ---------------------------------------------------------------------------
# Protected paths (property 3 groundwork).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("relative", [
    ".env",
    "phase3_v4_SEALED.json",
    "genesis_os/action_executor.py",
    "genesis_os/workspace_boundary.py",
    "genesis_os/authorization_grant.py",
    "conftest.py",
    "genesis.py",
    "tools/run_direct_test.py",
])
def test_genesis_foundation_paths_are_protected(relative):
    reason = path_is_protected(BACKEND / relative)
    assert reason, f"{relative} should be protected"


# ---------------------------------------------------------------------------
# 2026-10-14: the primary entry point and the whole backend tree.
#
# Before this, `protected_paths()` listed `genesis_os` (a subdirectory)
# and nothing above it, so `path_is_protected(backend/genesis.py)`
# returned None: the 108 KB module that constructs every capability was
# not shielded from a destructive operation.
# ---------------------------------------------------------------------------

def test_primary_entry_point_is_protected_by_name():
    """The prompt must say WHICH file, not just its directory."""
    reason = path_is_protected(BACKEND / "genesis.py")
    assert reason == (
        "the Genesis OS primary entry point (genesis.py)"
    )


@pytest.mark.parametrize("relative", [
    "genesis.py",
    "test_genesis_arming.py",
    "tools/verify_all.py",
    "ai/ai_engine.py",
    "brain/brain.py",
])
def test_whole_backend_tree_is_protected(relative):
    """Not just genesis_os: every module in the repository."""
    assert path_is_protected(BACKEND / relative), (
        f"{relative} lives under the backend root and must be protected")


def test_a_delete_of_genesis_py_is_refused_end_to_end():
    """The behaviour the protection exists for, not just the predicate.

    This drives a real `file.delete` plan at the real ActionPlan /
    ActionExecutor boundary and asserts the file is still on disk. A
    predicate test proves the lookup works; only this proves the
    refusal actually happens.
    """
    from genesis_os.action_executor import ActionExecutor
    from genesis_os.action_plan import ActionPlan

    genesis_py = BACKEND / "genesis.py"
    before = genesis_py.read_bytes()
    assert before, "genesis.py should not be empty"

    class StubOS:
        def open_application(self, name):
            return {"success": False}

    plan = ActionPlan(
        operation="file.delete",
        target="genesis.py",
        application=None,
        parameters={"path": "genesis.py"},
        confidence=0.99,
    )

    result = ActionExecutor(StubOS()).execute(plan)

    # The refusal is the point: whatever the executor reports, the file
    # on disk must be byte-identical afterwards.
    after = genesis_py.read_bytes()
    assert after == before, (
        "genesis.py was modified by a file.delete dispatch; the "
        "protected-path check did not hold")
    assert genesis_py.is_file()

    # And it must be refused for the RIGHT reason, not merely blocked.
    reason = path_is_protected(genesis_py)
    assert reason and "entry point" in reason, (
        f"expected the refusal to name the entry point, got {reason!r}")
    assert result is not None


def test_ordinary_paths_are_not_protected(tmp_path):
    assert path_is_protected(tmp_path / "notes.txt") is None
    assert path_is_protected(
        BACKEND.parent / ".genesis_workspace" / "scratch.txt"
    ) is None


def test_boundary_module_is_named_in_its_own_protected_check():
    """The prompt must name the specific module, not just its directory.

    With the directory checked first, every file inside genesis_os
    reported as "...\\genesis_os", which tells a human approving the
    operation nothing about what they are about to change.
    """
    reason = path_is_protected(
        BACKEND / "genesis_os" / "workspace_boundary.py"
    )
    assert reason == "the workspace boundary module itself"