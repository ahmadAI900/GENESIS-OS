"""Genesis OS — workspace boundary.

A second, independent escalation axis that applies to EVERY capability
regardless of its classified tier.

WHY THIS EXISTS SEPARATELY FROM BLAST RADIUS
--------------------------------------------
``blast_radius`` answers "is this kind of operation reversible?".
That is a property of the capability and says nothing about WHERE it
acts. A Tier 2 capability such as ``file.create`` is genuinely
reversible -- but only if you are willing to delete whatever it wrote,
and "reversible" should not mean "may write anywhere on the disk".

So the boundary is a per-CALL check on the target, not a per-capability
classification. It feeds the SAME resolver both the adapter and the
executor already share, so an out-of-bounds call is escalated to Tier 1
and must present a genuine ``AuthorizationGrant`` — no parallel gate
was introduced.

CONFIGURATION
-------------
The active root comes from the ``GENESIS_WORKSPACE_ROOT`` environment
variable. When it is unset the boundary is ARMED with the default
workspace root (``<parent-of-backend>/.genesis_workspace``), not
inactive: an unset variable must not silently disable a security
control. Enforcement is OFF only when a human explicitly sets
``GENESIS_WORKSPACE_BOUNDARY=disabled`` (matched exactly).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional

__all__ = [
    "WORKSPACE_ROOT_ENV",
    "workspace_root",
    "boundary_banner_text",
    "path_is_protected",
    "protected_paths",
    "boundary_is_enforced",
    "resolve_target_path",
    "path_is_within",
    "arguments_escape_workspace",
]

WORKSPACE_ROOT_ENV = "GENESIS_WORKSPACE_ROOT"

# Item 10A (S1): the boundary is ARMED BY DEFAULT. Disarming now requires
# naming the decision explicitly, so a MISSING variable can no longer
# silently turn a security control off. Matched EXACTLY ("disabled");
# anything else -- including a typo like "DISABLED", "off", "false" or "0"
# -- leaves the boundary armed, because a control that a typo disarms is
# not a control.
BOUNDARY_STATE_ENV = "GENESIS_WORKSPACE_BOUNDARY"
BOUNDARY_DISABLED = "disabled"

# Used when GENESIS_WORKSPACE_ROOT is absent. Chosen to match the repo's
# OWN convention rather than invent one: .env in this repository already
# points at <parent-of-backend>/.genesis_workspace, and its comment
# records why -- "deliberately NOT backend\ (secrets, sealed corpora,
# safety code) and NOT system temp (writable by other processes)".
#
# That rules out both alternatives named in the directive:
#   * the user's HOME would be PERMISSIVE -- almost nothing lives outside
#     it, so the boundary would gate nearly nothing while reporting
#     itself armed. That is the same failure as being off, with a
#     reassuring banner over it.
#   * the backend tree itself is what .env explicitly rejects, because
#     Genesis's own secrets and safety code live there.
DEFAULT_WORKSPACE_DIRNAME = ".genesis_workspace"


def default_workspace_root() -> Path:
    """The root used when GENESIS_WORKSPACE_ROOT is not set.

    The root is the SIBLING of the backend tree, i.e.
    <parent-of-backend>/.genesis_workspace, which is exactly what this
    repository's own .env already points at. Using two parents (rather
    than three) would place it at backend/.genesis_workspace, which is
    the placement .env explicitly rejects.

    Created on demand. This is Genesis's own scratch workspace, not
    user data, so creating it is safe; refusing to would turn a first
    run into a configuration error for a directory the product owns.
    A failure to create it raises BoundaryConfigurationError, so an
    unusable default still fails CLOSED and loudly.
    """
    root = (
        Path(__file__).resolve().parent.parent.parent
        / DEFAULT_WORKSPACE_DIRNAME
    )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BoundaryConfigurationError(
            f"{WORKSPACE_ROOT_ENV} is not set and the default workspace "
            f"root {root} could not be created: {exc}. Failing closed."
        ) from exc
    return root.resolve()

# Argument names that can carry a filesystem target. Generic: any
# capability whose arguments include one of these is checked. Matching
# the existing canonicaliser in approval_store keeps the two in step.
#
# DELIBERATELY NOT INCLUDED: `sheet1` / `sheet2`.
#
# The directive for Item 9D named all three of other_path, sheet1 and
# sheet2 as "the live schema's second-file targets". Only one of them
# is. The executor dispatches
#
#     sheet_compare(path, p["sheet1"], p["other_path"], p["sheet2"])
#                                       ^^^^^^^^^^^^ a FILE
#     doc_compare(path, p["other_path"])
#
# so sheet1 and sheet2 are WORKSHEET NAMES, not paths. Scanning them
# would resolve a sheet called "Sheet1" to "<cwd>/Sheet1", which is
# outside any scratch workspace, and so escalate EVERY
# spreadsheet.compare to Tier 1 regardless of where its files live --
# the exact false escalation this module already warns about for
# `target` and for UI element names (see _CATEGORY_SCOPED_KEYS). The
# real second-file key is `other_path`, and it is the one added.
_PATH_KEYS = (
        "path", "file_path", "folder", "directory", "source", "destination",
        "output", "output_path", "save_path", "target_path",
        # Added by the registry key-coverage audit:
        #   path1/path2 - document.compare, document.compare_intel,
        #                spreadsheet.compare. Without these, comparing an
        #                in-workspace file against an outside one was not
        #                gated at all.
        #   new_name   - file.rename, folder.rename.
        #   location   - filesystem.search.
        "path1", "path2", "new_name", "location",
        # Added by Item 9D (S2): other_path - the SECOND file of a
        # two-document operation, read by action_executor.py:2084
        # (document.compare) and :2125 (spreadsheet.compare). Measured
        # before this: with the first file inside the workspace and
        # other_path outside it, arguments_escape_workspace returned
        # None -- the outside file was not gated at all, so a
        # multi-file compare could read across the boundary while an
        # equivalent single-file read was refused.
        "other_path",
    )

# Keys that are only filesystem paths for SOME capabilities. `target`
# means a file for document.*/spreadsheet.*, but a UI element name for
# gui.*, an application name for application.window_list, and a settings
# name for system.open_settings. Scanning it unconditionally would
# resolve every GUI click on a relative element name to a path under
# cwd, which is outside the scratch root, escalating all GUI automation
# to Tier 1. So it is scoped to the categories where it is a path.
_CATEGORY_SCOPED_KEYS = {
    # DOCUMENT: document.create/inspect/search.
    # DATA: spreadsheet.add_column/create_from_dicts/update_cell
    # (spreadsheet capabilities are categorised DATA, not DOCUMENT).
    # Every DATA owner of `target` treats it as a file path.
    "target": frozenset({"DOCUMENT", "DATA"}),
}

# Values that look like paths but are not, and must not be misread as
# escaping the workspace.
#
# Deliberately EXCLUDES "" and "." and "..". Those are real relative
# paths that resolve to the parent directory, which is outside a
# scratch-only root, so classifying them as "not a path" was a
# fail-open: the caller reads None as IN-SIDE.
_NON_PATH = frozenset({"-", "computer", "screen", "default"})


class UnresolvablePathError(ValueError):
    """A path-bearing argument could not be interpreted.

    Raised instead of silently returning None. A None result means
    "no filesystem target", which the caller reads as inside the
    boundary, so anything that merely FAILED to parse must fail
    closed rather than be skipped.
    """


class BoundaryConfigurationError(RuntimeError):
    """The workspace boundary is ARMED but its root is unusable.

    Distinct from the boundary being explicitly disabled. A root that is
    set-but-broken, or a default root that cannot be created, must not
    silently disable the boundary while an operator believes it is armed
    -- so it raises instead of returning None.
    """


def workspace_root() -> Optional[Path]:
    """The active workspace root, or None ONLY when explicitly disabled.

    Item 10A (S1) changed the default. This used to document "unset is
    the deliberate off-switch", which meant a MISSING variable silently
    disabled the boundary: every caller read None as "not escaping", so
    with no .env present Genesis ran with the boundary INACTIVE and
    nothing said so.

    Now:

      * UNSET           -> ARMED with the default root (see
                          default_workspace_root). The boundary is on
                          unless someone says otherwise.
      * EXPLICIT        -> the configured root, and a broken one still
                          raises BoundaryConfigurationError.
      * GENESIS_WORKSPACE_BOUNDARY=disabled (exact) -> None, i.e. off,
                          but only when a human spelled that out.

    The asymmetry is the point. Turning a security control OFF is now
    harder than leaving it on.

    STRICTER SINCE 2026-10-14 (audit D-12). Two more cases fail closed
    instead of being accepted:

      * a RELATIVE root. `Path("somewhere").resolve()` silently
        resolves against the process CWD, which changes between the
        shell that launched the process and wherever the test or agent
        happens to be running. The operator set a path; they got a
        different one, and nothing reported it.
      * a root that DOES NOT EXIST. A nonexistent root makes every
        comparison vacuously fail-closed at the argument check, so the
        symptom is "everything is outside the workspace", not "the
        root is wrong". Failing at configuration time names the cause.

    Neither case is speculative: both were observed on this machine.
    """
    if (
        os.environ.get(BOUNDARY_STATE_ENV, "").strip()
        == BOUNDARY_DISABLED
    ):
        return None

    raw = os.environ.get(WORKSPACE_ROOT_ENV)
    if raw is None:
        return default_workspace_root()
    text = raw.strip()
    if not text:
        raise BoundaryConfigurationError(
            f"{WORKSPACE_ROOT_ENV} is set but empty; the boundary "
            f"cannot be enforced"
        )

    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise BoundaryConfigurationError(
            f"{WORKSPACE_ROOT_ENV}={text!r} is a RELATIVE path. It would "
            f"be resolved against the process working directory, which "
            f"changes, so the effective boundary would differ from the "
            f"configured one. Give an absolute path."
        )
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise BoundaryConfigurationError(
            f"{WORKSPACE_ROOT_ENV}={text!r} is not a usable path: {exc}"
        ) from exc
    if not resolved.is_dir():
        raise BoundaryConfigurationError(
            f"{WORKSPACE_ROOT_ENV}={text!r} does not exist or is not a "
            f"directory. A nonexistent root makes every path look like "
            f"an escape rather than naming the real problem. Create it or "
            f"unset {WORKSPACE_ROOT_ENV}."
        )
    return resolved


def boundary_banner_text() -> str:
    """One line, loud, for CLI startup.

    A security control whose state is invisible is easy to forget about.
    This makes the armed/disarmed state loud and testable rather than a
    property you discover by reading a constructor.

    Item 10A added the "armed with a DEFAULT root" wording, because
    "ACTIVE (root=...)" is now not the only way to be armed, and an
    operator who never configured anything must still be able to tell
    which root they are getting:

      Workspace boundary: ARMED (root=<path>)
      Workspace boundary: ARMED (default root=<path>; no GENESIS_WORKSPACE_ROOT set)
      Workspace boundary: DISABLED (GENESIS_WORKSPACE_BOUNDARY=disabled)
      Workspace boundary: ARMED (root UNUSABLE - ...; failing closed)

    A root that is armed but unusable is reported as such rather than
    DISABLED, because it really does refuse work: reporting DISABLED
    would misrepresent a system that is failing closed.
    """
    explicit_disable = (
        os.environ.get(BOUNDARY_STATE_ENV, "").strip()
        == BOUNDARY_DISABLED
    )
    try:
        root = workspace_root()
    except BoundaryConfigurationError as exc:
        return (
            "Workspace boundary: ARMED (root UNUSABLE - "
            f"{exc}; failing closed)"
        )
    if root is None:
        return (
            "Workspace boundary: DISABLED "
            f"({BOUNDARY_STATE_ENV}={BOUNDARY_DISABLED})"
        )
    if explicit_disable:
        # Unreachable while the opt-out is honoured, but stated so the
        # banner can never read ARMED while the env says disabled.
        return (
            "Workspace boundary: DISABLED "
            f"({BOUNDARY_STATE_ENV}={BOUNDARY_DISABLED})"
        )
    if os.environ.get(WORKSPACE_ROOT_ENV) is None:
        return (
            "Workspace boundary: ARMED "
            f"(default root={root}; no {WORKSPACE_ROOT_ENV} set)"
        )
    return f"Workspace boundary: ARMED (root={root})"


# Genesis's own foundations. Reading or writing inside the backend tree
# is treated as protected, because that is where .env, the sealed
# corpora, and the safety logic live. Used to make approval prompts
# visibly distinct (F5 follow-up 1, property 3).
def protected_paths() -> tuple:
    """Absolute paths Genesis treats as its own protected surface.

    ORDER MATTERS: specific files come before the directory that contains
    them, because the first match wins. With the directory first, every
    module inside `genesis_os` reported as "the genesis_os directory",
    which is useless in an approval prompt - the human needs to be told
    they are about to modify the boundary module itself.

    The final entry is the WHOLE backend root, so `genesis.py` and every
    other module in the repository are protected by default rather than by
    having to be listed one at a time. Before this, `path_is_protected()`
    returned None for `backend/genesis.py`: the `genesis_os` directory
    entry covers only that subdirectory, so the primary entry point -
    the 108 KB module that constructs every capability - was not
    shielded from a destructive operation.
    """
    backend_root = Path(__file__).resolve().parent.parent
    return (
        Path(__file__).resolve(),                       # boundary module
        backend_root / "genesis_os" / "authorization_grant.py",
        backend_root / ".env",
        backend_root / "phase3_v4_SEALED.json",
        backend_root / "genesis.py",                    # primary entry point
        backend_root / "conftest.py",
        backend_root / "genesis_os",                    # then the tree
        backend_root,                                   # then ALL of backend
    )


# Human-readable reasons, keyed by the protected entry's name.
_PROTECTED_REASONS = {
    "workspace_boundary.py": "the workspace boundary module itself",
    "authorization_grant.py": "the authorization grant module itself",
    ".env": "the Genesis .env (API keys and secrets)",
    "phase3_v4_SEALED.json": "a sealed Genesis corpus",
    "genesis.py": "the Genesis OS primary entry point (genesis.py)",
}


def path_is_protected(candidate: Path) -> Optional[str]:
    """Return a reason string when ``candidate`` is protected, else None."""
    try:
        resolved = Path(candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        return f"{candidate} could not be resolved for a protected-path check"
    for protected in protected_paths():
        try:
            resolved.relative_to(Path(protected).resolve())
        except ValueError:
            continue
        name = Path(protected).name
        if name in _PROTECTED_REASONS:
            return _PROTECTED_REASONS[name]
        if name == "genesis_os":
            return "the genesis_os capability directory"
        if resolved == Path(protected).resolve():
            return "the Genesis backend source tree itself"
        return str(protected)
    return None


def boundary_is_enforced() -> bool:
    try:
        return workspace_root() is not None
    except BoundaryConfigurationError:
        # Configured but broken still counts as armed: the boundary
        # will refuse work, which is the safe direction.
        return True


def resolve_target_path(value: Any) -> Optional[Path]:
    """Resolve one argument value to an absolute, symlink-resolved path.

    Returns None ONLY when the value genuinely is not a filesystem
    target (absent, empty, a UI sentinel, or a URL). Anything that
    fails to parse or resolve raises UnresolvablePathError so the
    caller can fail closed.
    """
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, (int, float)):
        raise UnresolvablePathError(
            f"expected a filesystem path, got {type(value).__name__} {value!r}"
        )
    if isinstance(value, (list, dict, tuple, set)):
        raise UnresolvablePathError(
            f"expected a single filesystem path, got {type(value).__name__} "
            f"with {len(value)} item(s)"
        )
    try:
        text = os.fspath(value)
    except TypeError as exc:
        raise UnresolvablePathError(
            f"expected a filesystem path, got {type(value).__name__} {value!r}"
        ) from exc
    if not isinstance(text, str):
        raise UnresolvablePathError(
            f"expected a filesystem path, got {type(text).__name__}"
        )
    text = text.strip()
    if not text:
        return None
    if text.lower() in _NON_PATH:
        return None
    # A URL is not a filesystem path. Treating one as a path is exactly
    # the kind of accidental catch this function exists to avoid.
    if "://" in text:
        return None
    # Strip the Windows extended-length prefix (\\?\) before resolving.
    # pathlib does not normalise it consistently, so a long path
    # addressed as \\?\C:\... compared unequal to its own non-prefixed
    # form and was wrongly judged outside the workspace. That is the
    # safe direction (over-gating) but it is still wrong, and agents
    # addressing long paths legitimately use this prefix.
    #
    # UNC paths (\\server\share) are deliberately NOT stripped: they
    # denote a network location, which is genuinely outside a local
    # workspace root, and must stay gated.
    if text.startswith("\\\\?\\"):
        text = text[4:]
        if text.startswith("UNC\\"):
            # \\?\UNC\server\share -> \\server\share. Restored rather
            # than bailing out: returning None here would mean "not a
            # filesystem target", which the caller reads as IN-SIDE,
            # i.e. a network path would look inside the workspace.
            # Rebuilt as a real UNC path it resolves and correctly
            # compares as outside.
            text = "\\\\" + text[4:]
    try:
        # expanduser + resolve collapses `..` AND follows symlinks, so a
        # link pointing outside the root is caught rather than trusted
        # by its in-root path text.
        return Path(text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        # Includes embedded NUL bytes and over-long paths. Previously
        # swallowed into a None, which read as INSIDE: a fail-open.
        raise UnresolvablePathError(
            f"{text!r} could not be resolved as a path: {exc}"
        ) from exc


def path_is_within(candidate: Path, root: Path) -> bool:
    """True when ``candidate`` is ``root`` or lies beneath it.

    Uses os.path.commonpath semantics rather than str.startswith,
    which would wrongly accept a sibling directory sharing a name
    prefix (e.g. root "C:/work" vs "C:/workspace-secret").
    """
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _keys_for_capability(capability_id: Optional[str]) -> frozenset:
    """The scanned key set, given the capability the call belongs to."""
    if not capability_id:
        return frozenset(_PATH_KEYS)
    from .capability_registry import CapabilityRegistry

    try:
        descriptor = CapabilityRegistry.get(capability_id)
    except Exception:
        # Unknown capability id: fall back to the base key set rather
        # than raising. resolve_blast_radius fails CLOSED on any
        # exception from the boundary check, so raising here would
        # escalate an unknown capability to Tier 1 instead of just
        # scanning the base keys.
        return frozenset(_PATH_KEYS)
    if descriptor is None:
        return frozenset(_PATH_KEYS)
    category = getattr(descriptor.category, "name", str(descriptor.category))
    extra = set()
    for key, categories in _CATEGORY_SCOPED_KEYS.items():
        if category in categories:
            extra.add(key)
    return frozenset(_PATH_KEYS) | extra


def arguments_escape_workspace(
    arguments: Optional[Mapping[str, Any]] = None,
    *,
    capability_id: Optional[str] = None,
) -> Optional[str]:
    """Return a reason string when any target argument leaves the root.

    Returns None when the call is inside the boundary, when the boundary
    has been EXPLICITLY disabled, or when the capability has no path-like
    argument at all.

    Item 10A: "not configured" is no longer one of the None cases. An
    unset GENESIS_WORKSPACE_ROOT now means ARMED with a default root, so
    this function only returns None for a call that genuinely stays
    inside. It used to return None whenever the variable was missing.

    Fails closed: a broken configuration, or a path-bearing value that
    could not be parsed, is reported as an escape rather than skipped.
    """
    try:
        root = workspace_root()
    except BoundaryConfigurationError as exc:
        return f"workspace boundary is configured but unusable: {exc}"
    if root is None:
        return None
    if not isinstance(arguments, Mapping):
        return None

    for key in _keys_for_capability(capability_id):
        if key not in arguments:
            continue
        try:
            resolved = resolve_target_path(arguments[key])
        except UnresolvablePathError as exc:
            return f"argument {key!r} is not a usable path: {exc}"
        if resolved is None:
            continue
        if not path_is_within(resolved, root):
            return (
                f"argument {key!r} resolves to {resolved}, which is "
                f"outside the configured workspace root {root}"
            )
    return None