"""Directive 8C: keep the phantom-method wiring from coming back.

Items 8A and 8B fixed two methods that had been wired to methods which
did not exist on the objects they were called on:

  * `_handle_level_1` probed `ConversationEngine` for `.respond()` and
    then `.chat()`. It defines neither, so every conversation request
    silently returned a placeholder.
  * `_synthesize` probed `AIEngine` for `.generate()` and then
    `.chat()`. It defines neither, so synthesis never ran and the raw
    agent payload was returned as the user's answer.

The probe pattern is the real hazard, not those two call sites. A
`hasattr()` guard before a call looks defensive and costs nothing, and
it converts "this method does not exist" into "silently take the other
branch" instead of "fail loudly". Both of these failures were invisible
because the probe made the missing method unreachable rather than
reported: no AttributeError, no log line, no failed test.

So this guard is written against the PATTERN, not against the two
incidents, and scans every product directory rather than just the
runtime.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent

RUNTIME = BACKEND / "runtime" / "genesis_runtime.py"

PRODUCT_ROOTS = (
    "genesis_os", "core", "agents", "ai", "memory", "tools", "runtime",
    "knowledge", "brain", "planner", "reasoning", "router", "personality",
    "emotion", "conversation", "collaboration", "internet", "agent_context",
    "integration",
)

# Method names that were probed for but do not exist on the objects the
# runtime holds. Reintroducing a probe for any of these re-creates the
# silent-fallback bug.
PHANTOM_METHODS = frozenset({"respond", "chat", "generate"})

# The placeholder the dead branch used to return. It claimed the
# pipeline was connected while consulting nothing.
DEAD_PLACEHOLDER = "Level 1 conversation pipeline is connected"

# The real methods the runtime must be calling.
REQUIRED_REAL_CALLS = {
    "process_request": "Brain.process_request (brain/brain.py:51)",
    "generate_response": "AIEngine.generate_response (ai/ai_engine.py:239)",
}


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


def _parse(path: pathlib.Path):
    return ast.parse(path.read_text(encoding="utf-8-sig"))


# =====================================================================
# The pattern itself
# =====================================================================

def test_no_product_code_probes_for_a_phantom_method():
    """No `hasattr(obj, "respond"|"chat"|"generate")` anywhere.

    A probe before a call hides the absence of the method instead of
    surfacing it. Every occurrence found here is a bug that reports
    itself only by never doing the thing it claims to do.
    """
    offenders = []
    for path in _product_files():
        try:
            tree = _parse(path)
        except SyntaxError as exc:  # pragma: no cover
            offenders.append(f"{path.name}: unparseable ({exc})")
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "hasattr"
            ):
                continue
            if len(node.args) < 2:
                continue
            second = node.args[1]
            if (
                isinstance(second, ast.Constant)
                and isinstance(second.value, str)
                and second.value in PHANTOM_METHODS
            ):
                rel = path.relative_to(BACKEND).as_posix()
                offenders.append(f"{rel}:{node.lineno} -> {second.value!r}")

    assert not offenders, (
        "Product code probes for a method that does not exist on the "
        "target. This is the exact shape of the Item 8A/8B silent "
        "fallback bug.\n  offenders:\n    " + "\n    ".join(offenders)
    )


def test_the_target_classes_still_lack_the_phantom_methods():
    """If one of these ever appears, the runtime should be re-examined
    rather than the phantom branch silently becoming the real one."""
    from ai.ai_engine import AIEngine
    from conversation.conversation import ConversationEngine

    for method in ("respond", "chat"):
        assert not hasattr(ConversationEngine, method), (
            f"ConversationEngine.{method} now exists; revisit "
            f"_handle_level_1, because two answers would then compete"
        )
    for method in ("chat", "generate"):
        assert not hasattr(AIEngine, method), (
            f"AIEngine.{method} now exists; revisit _synthesize, because "
            f"two answers would then compete"
        )


# =====================================================================
# The runtime must keep calling what is real
# =====================================================================

@pytest.mark.parametrize("method", sorted(REQUIRED_REAL_CALLS))
def test_runtime_references_the_real_method(method):
    """A guard against someone deleting the real wiring.

    The runtime resolves the callable with `getattr(obj, "name", None)`
    and calls the local, precisely so a brain or engine missing the
    method degrades instead of crashing. So both spellings count as
    real wiring: an attribute call (`brain.process_request(...)`) and a
    getattr resolution against that name.
    """
    tree = _parse(RUNTIME)
    found = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        ):
            found.add(node.func.attr)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("getattr", "hasattr")
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            found.add(node.args[1].value)

    assert method in found, (
        f"GenesisRuntime no longer references {REQUIRED_REAL_CALLS[method]}. "
        f"Level 1 would stop producing real answers again. "
        f"Currently referenced: {sorted(found)}"
    )


def test_runtime_never_returns_the_dead_placeholder():
    """The lying string must not come back, in code or in a message."""
    offenders = []
    for path in _product_files():
        try:
            source = path.read_text(encoding="utf-8-sig")
        except Exception:  # pragma: no cover
            continue
        if DEAD_PLACEHOLDER in source:
            offenders.append(path.relative_to(BACKEND).as_posix())
    assert not offenders, (
        "The dead L1 placeholder string is back in product code. It "
        "claimed the conversation pipeline was connected while "
        "consulting nothing.\n  found in: " + ", ".join(offenders)
    )


def test_the_placeholder_is_not_produced_at_runtime():
    """Belt and braces: the degraded answer must not contain it either."""
    from conversation.conversation import ConversationEngine
    from runtime.genesis_runtime import GenesisRuntime

    runtime = GenesisRuntime(
        brain=None,
        conversation=ConversationEngine(),
        memory=None,
        ai_engine=None,
        agent_bridge=None,
    )
    message = runtime._handle_level_1("hello", None)["response"]["message"]
    assert DEAD_PLACEHOLDER not in message, message
    assert "unavailable" in message, message