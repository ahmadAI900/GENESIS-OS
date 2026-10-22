"""Item 28C (L15): core/exceptions.py defined a class named OSError.

``core/exceptions.py`` declared ``class OSError(GenesisError)`` -- so
inside that module the name ``OSError`` resolved to the CUSTOM class
instead of the builtin. Any ``except OSError`` / ``raise OSError`` in
that module would have caught/raised the Genesis error, not the
operating-system error. The class's own docstring even says it "is
intentionally named GenesisOSError rather than replacing Python's
built-in OSError" -- the NAME was the bug, not the design.

The fix renames the class to ``GenesisOSError`` (its documented name)
and keeps the same code and base class, so the error is caught only by
its own type and the builtin is reachable again.

These tests pin:
  * the module defines no class named OSError,
  * the module's OSError attribute is the BUILTIN,
  * the custom error exists under its own name with its own code,
  * a builtin OSError is NOT caught by the custom error,
  * the custom error IS caught by its own type.
"""
from __future__ import annotations

import ast
import builtins
import pathlib

import core.exceptions as exceptions_module

MODULE = pathlib.Path("core") / "exceptions.py"


def test_the_module_defines_no_class_named_oserror():
    tree = ast.parse(MODULE.read_text(encoding="utf-8-sig"))
    names = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]

    assert "OSError" not in names, (
        "core/exceptions.py still defines a class named OSError; it "
        "shadows the builtin inside the module"
    )


def test_the_modules_oserror_attribute_is_the_builtin():
    assert getattr(exceptions_module, "OSError", builtins.OSError) is (
        builtins.OSError
    ), (
        "core/exceptions.OSError is not the builtin OSError"
    )


def test_the_custom_error_lives_under_its_own_name():
    assert hasattr(exceptions_module, "GenesisOSError"), (
        "core/exceptions.py does not define GenesisOSError"
    )

    error = exceptions_module.GenesisOSError("boom")

    assert isinstance(error, exceptions_module.GenesisError)
    assert error.code == "OS_ERROR"
    assert str(error) == "boom"


def test_a_builtin_oserror_is_not_caught_by_the_custom_error():
    caught = None

    try:
        try:
            raise builtins.OSError("disk on fire")
        except exceptions_module.GenesisOSError as error:  # noqa: B902
            caught = error
    except builtins.OSError as error:
        caught = error

    assert isinstance(caught, builtins.OSError), (
        f"a builtin OSError was swallowed by the custom error: {caught!r}"
    )
    assert not isinstance(caught, exceptions_module.GenesisOSError)


def test_the_custom_error_is_caught_by_its_own_type():
    caught = None

    try:
        raise exceptions_module.GenesisOSError("genesis boom")
    except exceptions_module.GenesisOSError as error:
        caught = error

    assert isinstance(caught, exceptions_module.GenesisOSError)
    assert str(caught) == "genesis boom"
