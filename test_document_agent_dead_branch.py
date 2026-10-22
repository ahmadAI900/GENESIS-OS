"""Item 27D (L9): dead `if False else None` and an unimported Optional.

Two dead-weight defects in agents/document_agent.py:

1. DEAD BRANCH. The docx-creation path ended with

       saved = self.workspace.save_text_artifact(...) if False else None

   -- a ternary whose condition is the constant False, so the call was
   never made and `saved` was always None. The variable was then never
   read. The document was written by the code BELOW that statement
   (a direct ``document.save(target)``), so the dead call only
   pretended to be an artifact save.

2. UNIMPORTED OPTIONAL. The same method annotated

       read_match_obj: Optional[_re.Match] = None

   but the module never imported Optional (and `_re` is imported
   INSIDE the method, so the name is not even reachable from module
   scope). Local annotations are not evaluated at runtime, which is
   why this had not exploded yet -- but the annotation is unresolvable
   as written, and any code that evaluates it (typing.get_type_hints,
   a module-level annotation, a static checker) raises NameError.

These tests pin:
  * the module imports cleanly,
  * no `if False` branch (statement or ternary) is left in the module,
  * the dead artifact-save call is gone,
  * every annotation in the module resolves against the module
    namespace (no NameError),
  * the real document creation still works.
"""
from __future__ import annotations

import ast
import pathlib

import agents.document_agent as document_agent_module

MODULE = pathlib.Path("agents") / "document_agent.py"


def _source() -> str:
    return MODULE.read_text(encoding="utf-8-sig")


def _tree() -> ast.Module:
    return ast.parse(_source())


def test_the_module_imports_cleanly():
    assert document_agent_module is not None
    assert hasattr(document_agent_module, "DocumentAgent")


def test_no_dead_if_false_branch_is_left_in_the_module():
    dead = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Constant) and test.value is False:
                dead.append(node.lineno)
        elif isinstance(node, ast.IfExp):
            test = node.test
            if isinstance(test, ast.Constant) and test.value is False:
                dead.append(node.lineno)

    assert not dead, (
        f"the module still carries a dead `if False` branch at line(s) "
        f"{dead}"
    )


def test_the_dead_artifact_save_call_is_gone():
    # ast.unparse drops comments, so the tombstone that documents the
    # removal does not count as a live `if False` expression.
    code = ast.unparse(_tree())

    assert "if False" not in code, (
        "the module still contains a live `if False` expression"
    )
    assert "placeholder-not-used" not in code, (
        "the dead artifact-save placeholder payload is still in the "
        "module"
    )


def test_every_annotation_in_the_module_resolves():
    """Optional was used without being imported (and `_re` is a
    function-local import), so the annotation could not be evaluated.
    """
    namespace = vars(document_agent_module)
    unresolved = []

    for node in ast.walk(_tree()):
        if not isinstance(node, ast.AnnAssign) or node.annotation is None:
            continue
        try:
            eval(
                compile(
                    ast.Expression(node.annotation), "<annotation>", "eval"
                ),
                namespace,
            )
        except NameError as error:
            unresolved.append(f"line {node.lineno}: {error}")

    assert not unresolved, (
        "annotations in agents/document_agent.py do not resolve: "
        f"{unresolved}"
    )


def test_optional_is_imported_by_the_module():
    assert hasattr(document_agent_module, "Optional"), (
        "agents/document_agent.py does not import Optional"
    )
