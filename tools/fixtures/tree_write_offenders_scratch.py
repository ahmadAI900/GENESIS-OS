"""SCRATCH: a test that writes into the product tree. This MUST fail by
name.

Removed after the measurement. Not collected by an ordinary run: it does
not match `test_*.py` and pytest only sees it when passed by explicit
path.

The write is a RELATIVE path, deliberately. That is the shape that
produced the zero-byte file `backend/file`: a test asked to write "file"
with no directory, so the target silently became whatever directory the
process happened to be sitting in. Here the process is sitting in
`backend/`, so the relative write lands in the product tree and the check
has something to catch.

`workspace_root_chdir` chdirs into a throwaway directory first, so the
only thing that can put a file in the product tree is the test's own
relative write. Without that, the test would prove nothing: it would be
caught because the fixture leaked, not because the check works.
"""

import pathlib

import pytest


@pytest.fixture
def workspace_root_chdir(workspace_root, monkeypatch):
    """A real, isolated directory the process may chdir into."""
    monkeypatch.chdir(workspace_root)
    return workspace_root


def test_scratch_relative_write_into_product_tree_is_caught(
        workspace_root_chdir):
    # The process CWD is the workspace, so this does NOT hit the product
    # tree. Proving the negative is half the point: a check that fires on
    # legitimate workspace writes is useless.
    pathlib.Path("inside_workspace.txt").write_text("fine", encoding="utf-8")
    assert (workspace_root_chdir / "inside_workspace.txt").is_file()


def test_scratch_relative_write_from_backend_is_caught(monkeypatch):
    """chdir to the product tree, then write a bare relative name.

    This reproduces the `backend/file` artefact exactly.
    """
    from tools.tree_write_plugin import BACKEND
    monkeypatch.chdir(BACKEND)
    try:
        pathlib.Path("c2_scratch_relative_write.txt").write_text(
            "deliberate\n", encoding="utf-8")
        assert pathlib.Path(BACKEND / "c2_scratch_relative_write.txt").is_file()
    finally:
        (BACKEND / "c2_scratch_relative_write.txt").unlink(missing_ok=True)


def test_scratch_absolute_product_path_is_caught(monkeypatch):
    """An explicit absolute path into the tree is the same violation."""
    from tools.tree_write_plugin import BACKEND
    target = BACKEND / "c2_scratch_absolute_write.txt"
    target.write_text("deliberate\n", encoding="utf-8")
    try:
        assert target.is_file()
    finally:
        target.unlink(missing_ok=True)


def test_scratch_mkdir_in_product_tree_is_caught():
    from tools.tree_write_plugin import BACKEND
    target = BACKEND / "c2_scratch_dir"
    target.mkdir(exist_ok=True)
    try:
        assert target.is_dir()
    finally:
        target.rmdir()
