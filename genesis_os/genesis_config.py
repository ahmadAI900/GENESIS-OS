"""Explicit Genesis configuration loading.

WHY THIS EXISTS
---------------
Until now, arming the workspace boundary depended on an unrelated
constructor calling ``load_dotenv()``. ``ai/ai_engine.py`` calls it
inside ``AIEngine.__init__``, so whether the boundary was enforced
depended on whether that engine had been built. Measured in fresh
processes on 2026-10-08:

    bare executor process   -> enforced = False   (.env declares the root)
    AIEngine constructed    -> enforced = True
    GenesisOS runtime       -> enforced = False

That is a side effect masquerading as configuration. A security control
whose state depends on an unrelated object's construction order is not a
control you can reason about.

DESIGN
------
Loading is EXPLICIT. ``workspace_boundary.workspace_root()``
deliberately does NOT call this module, because auto-loading would make
"variable unset" unreachable: any machine with a ``.env`` would be
permanently armed and no test could ever verify the unarmed path.

So:
  * production entry points call :func:`load_genesis_config` once, at
    startup, on purpose;
  * the boundary reads only ``os.environ``.

That keeps the two properties we need: arming is explicit rather than
accidental, and the unarmed path stays reachable.

DETERMINISM AND IDEMPOTENCE
---------------------------
* Idempotent: repeat calls are no-ops and report ``changed=[]``.
* Never overrides a variable already present in the environment. An
  operator who exports ``GENESIS_WORKSPACE_ROOT`` to a scratch directory
  for one run must not be overruled by the checked-in ``.env``. This is a
  deliberate decision, not an oversight; use ``override=True`` to opt out.
* A missing or unreadable ``.env`` is not an error: Genesis must still
  run, unarmed, on a machine with no configuration at all.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Mapping, Optional

__all__ = [
    "load_genesis_config",
    "default_dotenv_path",
    "current_genesis_env",
    "was_loaded",
    "reset_for_tests",
]

_LOADED = False
_LOADED_FROM: Optional[str] = None


def default_dotenv_path() -> Optional[Path]:
    """The ``.env`` beside this package's parent, or None if absent.

    Located relative to this module rather than the current working
    directory, so arming does not depend on where a process was started.
    """
    backend_root = Path(__file__).resolve().parent.parent
    candidate = backend_root / ".env"
    return candidate if candidate.is_file() else None


def current_genesis_env() -> Dict[str, str]:
    """The GENESIS_* variables currently visible to this process."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.startswith("GENESIS_")
    }


def load_genesis_config(
    dotenv_path: Optional[Path] = None,
    *,
    override: bool = False,
) -> Dict[str, object]:
    """Load Genesis configuration into ``os.environ``.

    Returns a dict with ``changed`` (keys this call newly set) and
    ``skipped`` (GENESIS_* keys the file declared that were left alone),
    plus ``path`` and ``already_loaded``.

    Idempotent: a second call with the same arguments changes nothing.
    """
    global _LOADED, _LOADED_FROM

    path = Path(dotenv_path) if dotenv_path is not None else default_dotenv_path()
    result: Dict[str, object] = {
        "path": str(path) if path else None,
        "changed": [],
        "skipped": [],
        "already_loaded": _LOADED,
    }
    if path is None or not path.is_file():
        _LOADED = True
        return result

    if not override:
        try:
            from dotenv import dotenv_values

            declared = {
                k: v for k, v in dotenv_values(path).items()
                if k is not None and k.startswith("GENESIS_")
            }
        except Exception:
            declared = {}
        for key, value in declared.items():
            if key in os.environ:
                result["skipped"].append(key)  # type: ignore[union-attr]
        target = {k: v for k, v in declared.items() if k not in os.environ}
    else:
        target = {
            k: v for k, v in _read_simple(path).items()
            if k.startswith("GENESIS_")
        }

    for key, value in target.items():
        if value is None:
            continue
        os.environ[key] = str(value)
        result["changed"].append(key)  # type: ignore[union-attr]

    _LOADED = True
    _LOADED_FROM = str(path)
    return result


def _read_simple(path: Path) -> Mapping[str, Optional[str]]:
    """Minimal KEY=VALUE reader used only when override=True.

    Avoids depending on python-dotenv semantics for the override path,
    which exists purely for operators deliberately re-pointing config.
    """
    out: Dict[str, Optional[str]] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def was_loaded() -> bool:
    """True once :func:`load_genesis_config` has run in this process."""
    return _LOADED


def reset_for_tests() -> None:
    """Forget that loading happened. Does not touch os.environ."""
    global _LOADED, _LOADED_FROM
    _LOADED = False
    _LOADED_FROM = None