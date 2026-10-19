"""
ITEM 19B (T14) -- pytest collection must contain only real test modules.

Before this item, pytest collected 174 modules matching the default
patterns (`test_*.py` / `*_test.py`), of which 11 defined ZERO tests:
they are runnable scripts/proofs whose execution belongs to an explicit
command line, not to a test run. Separately, pytest.ini `--ignore=`d six
more zero-test scripts while documenting the rule inaccurately: it
claimed ignored modules match `*_test.py` (two match `test_*.py`) and
did not name any of the six files, so nobody could audit the list.

Fix: the 11 collected scripts were renamed with a `script_` prefix
(preserving their names, now matching neither pattern), the pytest.ini
comment now states both patterns and documents every ignore entry by
name with its reason, and the meta-tests below keep both properties
true. No test is added or removed by the renames -- the renamed files
contributed zero tests to the count.
"""
import ast
import configparser
import fnmatch
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parent
PYTEST_INI = BACKEND / "pytest.ini"

# Directories pytest never recurses into (hidden dirs, build output,
# venvs, caches); a test file inside one of these is not collected.
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    "build", "dist", ".pytest_cache", ".tox", ".hypothesis",
    "_darcs", "CVS",
}


def _pytest_ini_text():
    return PYTEST_INI.read_text(encoding="utf-8")


def _pytest_ini_comment():
    # Everything above the `addopts =` assignment is the comment block.
    # Split on the line-start assignment: the word "addopts" also occurs
    # in the prose (line 11: "NOT in addopts").
    return _pytest_ini_text().split("\naddopts", 1)[0]


def _ignore_entries():
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI, encoding="utf-8")
    addopts = parser["pytest"]["addopts"]
    entries = []
    for token in addopts.split():
        if token.startswith("--ignore="):
            entries.append(token.split("=", 1)[1])
    return entries


def _is_ignored(rel_path):
    return any(
        rel_path == entry or rel_path.endswith("/" + entry)
        for entry in _ignore_entries()
    )


def _test_defs(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = []

    def scan(nodes):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    found.append(node.name)
            elif isinstance(node, ast.ClassDef):
                if node.name.startswith("Test"):
                    scan(node.body)
            elif isinstance(node, ast.If):
                scan(node.body)
            elif isinstance(node, ast.Try):
                scan(node.body)
                for handler in node.handlers:
                    scan(handler.body)
                scan(node.orelse)
                scan(node.finalbody)
            elif isinstance(node, (ast.With, ast.For, ast.While)):
                scan(node.body)

    scan(tree.body)
    return found


def _collected_candidates():
    for path in sorted(BACKEND.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        name = path.name
        if fnmatch.fnmatch(name, "test_*.py") or fnmatch.fnmatch(
            name, "*_test.py"
        ):
            yield path


def test_ignore_entries_exist_are_named_in_the_comment_and_define_no_tests():
    entries = _ignore_entries()
    assert entries, "pytest.ini should document why files are ignored"
    comment = _pytest_ini_comment()
    for entry in entries:
        path = BACKEND / entry
        assert path.exists(), f"--ignore={entry} but the file does not exist"
        assert entry in comment, (
            f"--ignore={entry} is not documented by name in the pytest.ini "
            "comment; every ignore entry must state its reason there"
        )
        assert _test_defs(path) == [], (
            f"--ignore={entry}: the module defines tests; ignoring it would "
            "hide coverage. Tests with real risk belong behind the `live` "
            "marker, not in --ignore"
        )


def test_pytest_ini_documents_both_collection_patterns():
    comment = _pytest_ini_comment()
    assert "test_*.py" in comment, (
        "the comment must document the `test_*.py` collection pattern"
    )
    assert "*_test.py" in comment, (
        "the comment must document the `*_test.py` collection pattern"
    )


def test_every_collected_module_defines_at_least_one_test():
    zero_test_modules = []
    for path in _collected_candidates():
        rel = path.relative_to(BACKEND).as_posix()
        if _is_ignored(rel):
            continue
        try:
            defs = _test_defs(path)
        except SyntaxError as exc:
            raise AssertionError(
                f"{rel} does not parse: collection would error out"
            ) from exc
        if not defs:
            zero_test_modules.append(rel)

    assert not zero_test_modules, (
        "collected module(s) define zero tests; pytest imports every "
        "candidate at collection time, so scripts must be renamed out of "
        "the patterns (script_ prefix) instead of being collected: "
        + ", ".join(zero_test_modules)
    )
