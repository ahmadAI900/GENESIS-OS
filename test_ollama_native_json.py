"""Item 5A -- OllamaProvider._generate_native must not NameError.

The method serialised its request with `json.dumps` and parsed the reply
with `json.loads`, but `ai/providers.py` never imported `json` at module
scope. Every call on Ollama's native `/api/generate` fallback therefore
died with `NameError: name 'json' is not defined` -- before any network
call was even attempted.

Reproduced 2026-10-15 with `urllib.request.urlopen` patched to return a
valid JSON body: the provider raised NameError rather than returning the
response text.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai.providers import OllamaProvider


class _FakeResponse(io.BytesIO):
    """A minimal urlopen context manager returning canned bytes."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


CANNED = b'{"response": "hello from ollama", "done": true}'


@pytest.fixture
def provider():
    return OllamaProvider(api_key="test-key", model="llama3")


def test_generate_native_returns_the_response_text(provider):
    """The whole point: a valid response must come back as text."""
    with mock.patch("urllib.request.urlopen",
                    return_value=_FakeResponse(CANNED)):
        result = provider._generate_native("hi")

    assert result == "hello from ollama", result


def test_generate_native_sends_a_json_request_body(provider):
    """It must serialise the payload, not raise while doing so."""
    captured = {}

    def capture(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = request.data
        return _FakeResponse(CANNED)

    with mock.patch("urllib.request.urlopen", capture):
        provider._generate_native("prompt text", temperature=0.2,
                                  max_tokens=64)

    assert captured["url"].endswith("/api/generate"), captured["url"]
    # A valid JSON object, with the options wired through.
    import json as _json

    payload = _json.loads(captured["body"].decode("utf-8"))
    assert payload["prompt"] == "prompt text", payload
    assert payload["model"] == "llama3", payload
    assert payload["stream"] is False, payload
    assert payload["options"]["temperature"] == 0.2, payload
    assert payload["options"]["num_predict"] == 64, payload


def test_json_is_imported_at_module_scope():
    """Structural: the fix must be a module-scope import.

    A function-local `import json` would also work, but the bug existed
    precisely because the two call sites assumed a module-level binding.
    """
    import ai.providers as providers

    assert hasattr(providers, "json"), (
        "ai.providers still has no module-level `json` binding"
    )


def test_no_bare_json_use_remains_unbound():
    """Every `json.` use in the module must resolve.

    Walks the AST for `json.<attr>` loads and confirms the module binds
    `json`, so a future removal cannot reintroduce a NameError silently.
    """
    import ast

    import ai.providers as providers

    source = Path(providers.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    bare = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "json"
        and isinstance(node.ctx, ast.Load)
    ]
    assert bare, "expected json.* call sites to still exist in the module"
    assert hasattr(providers, "json"), (
        f"bare json references at lines {bare} have no module binding"
    )


def test_an_empty_response_still_raises_provider_error(provider):
    """The pre-existing no-content error path is unchanged."""
    from ai.provider import ProviderError

    empty = _FakeResponse(b'{"done": true}')
    with mock.patch("urllib.request.urlopen", return_value=empty):
        with pytest.raises(ProviderError):
            provider._generate_native("hi")