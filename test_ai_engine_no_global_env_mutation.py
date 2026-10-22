"""Item 28A (L4): AIEngine.__init__ mutated the process-global os.environ.

ai/ai_engine.py called ``load_dotenv()`` inside the constructor. That
writes every key of the .env file into the PROCESS-GLOBAL
``os.environ``, so constructing an engine changed the environment for
every other component and every other test in the process. The
repository already has the answer for the deliberate, global case:
``genesis_os/genesis_config.py`` loads configuration explicitly at the
process entry point (``genesis.py`` -> ``announce_boundary_state``).

The fix makes the engine read its configuration from a LOCAL snapshot
(``dotenv_values()`` merged with the real environment, the real
environment still winning) and never touch ``os.environ``.

These tests pin:
  * the constructor never calls load_dotenv,
  * constructing an engine adds NO key to os.environ,
  * the engine still sees its .env configuration,
  * the real process environment still wins over the .env file,
  * a missing/unreadable .env is not an error,
  * the module does not import load_dotenv at all.
"""
from __future__ import annotations

import ast
import os
import pathlib

import ai.ai_engine as ai_engine_module
from ai.ai_engine import AIEngine
from ai.provider import LLMProvider, ProviderHealth

MODULE = pathlib.Path("ai") / "ai_engine.py"


class _StubProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "Ollama"

    @property
    def model_id(self) -> str:
        return "stub-model"

    @property
    def is_available(self) -> bool:
        return True

    def generate(
        self,
        prompt: str,
        *,
        tools=None,
        temperature=None,
        max_tokens=None,
    ) -> str:
        return "stub answer"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name, available=True, model_id=self.model_id
        )


def _engine() -> AIEngine:
    return AIEngine(providers=[_StubProvider()])


def test_the_constructor_never_calls_load_dotenv(monkeypatch):
    calls = []

    def fake_load_dotenv(*args, **kwargs):
        calls.append((args, kwargs))
        os.environ["FAKE_DOTENV_INJECTED_KEY"] = "1"

    monkeypatch.setattr(
        ai_engine_module, "load_dotenv", fake_load_dotenv, raising=False
    )

    _engine()

    assert calls == [], (
        "AIEngine.__init__ called load_dotenv(): a constructor must not "
        "mutate the process-global environment"
    )


def test_constructing_the_engine_adds_no_key_to_os_environ(monkeypatch):
    def fake_load_dotenv(*args, **kwargs):
        os.environ["FAKE_DOTENV_INJECTED_KEY"] = "1"

    monkeypatch.setattr(
        ai_engine_module, "load_dotenv", fake_load_dotenv, raising=False
    )
    monkeypatch.setattr(
        ai_engine_module,
        "dotenv_values",
        lambda *a, **k: {"FAKE_DOTENV_INJECTED_KEY": "1"},
        raising=False,
    )
    monkeypatch.delenv("FAKE_DOTENV_INJECTED_KEY", raising=False)

    before = dict(os.environ)

    _engine()

    assert "FAKE_DOTENV_INJECTED_KEY" not in os.environ, (
        "constructing the engine wrote a .env key into os.environ"
    )
    assert set(os.environ) == set(before), (
        "constructing the engine added or removed environment keys: "
        f"{set(os.environ) ^ set(before)}"
    )


def test_the_engine_still_sees_its_dotenv_configuration(monkeypatch):
    monkeypatch.setattr(
        ai_engine_module,
        "dotenv_values",
        lambda *a, **k: {"GENESIS_AI_MODE": "local"},
        raising=False,
    )
    monkeypatch.delenv("GENESIS_AI_MODE", raising=False)

    engine = _engine()

    assert engine.mode == "local", (
        "the engine no longer sees its .env configuration "
        f"(mode={engine.mode!r})"
    )


def test_the_real_process_environment_wins_over_the_dotenv_file(monkeypatch):
    monkeypatch.setattr(
        ai_engine_module,
        "dotenv_values",
        lambda *a, **k: {"OLLAMA_MODEL": "from-dotenv-file"},
        raising=False,
    )
    monkeypatch.setenv("OLLAMA_MODEL", "from-process-environment")

    engine = AIEngine()

    assert engine.local_model == "from-process-environment", (
        "the real environment must still win over the .env file "
        f"(model={engine.local_model!r})"
    )


def test_a_missing_or_unreadable_dotenv_file_is_not_an_error(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no .env here")

    monkeypatch.setattr(
        ai_engine_module, "dotenv_values", boom, raising=False
    )
    monkeypatch.delenv("GENESIS_AI_MODE", raising=False)

    engine = _engine()

    assert engine.mode == "auto", (
        f"an unreadable .env changed the default mode: {engine.mode!r}"
    )


def test_the_module_does_not_import_load_dotenv():
    tree = ast.parse(MODULE.read_text(encoding="utf-8-sig"))
    imported = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)

    assert "load_dotenv" not in imported, (
        "ai/ai_engine.py still imports load_dotenv; the constructor "
        "must not mutate the global environment"
    )
    assert "dotenv_values" in imported, (
        "ai/ai_engine.py does not import dotenv_values; the engine "
        "must read its configuration into a local mapping"
    )
