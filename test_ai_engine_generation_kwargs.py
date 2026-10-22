"""Item 28B (L5): generation_kwargs were silently dropped in AUTO mode.

ai/ai_engine.py's generate_response forwarded ``generation_kwargs`` in
the explicit "local" and "cloud" modes, but the AUTO branch called
``_generate_from_provider(...)`` WITHOUT them -- so temperature and
max_tokens vanished and the provider used its own defaults, with no
warning.

That is not academic. ``genesis_os/llm_intent_resolver.py`` calls
generate_response with ``temperature=0.0, max_tokens=256`` precisely so
the capability selection is deterministic and bounded; in AUTO mode
both were dropped (the resolver's own comment records a 10,859-second
generation caused by the missing output cap).

Two silent drops are pinned here:
  * the ENGINE dropped the kwargs in AUTO mode,
  * the Anthropic provider accepted temperature/max_tokens and then
    ignored them (hardcoded max_tokens=4096).

These tests pin:
  * AUTO mode forwards the kwargs to the provider,
  * the AUTO fallback provider also receives them,
  * explicit modes still forward them,
  * no kwargs by default means the provider's own defaults,
  * an UNSUPPORTED kwarg is reported loudly, never dropped,
  * the Anthropic provider honours temperature and max_tokens.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.ai_engine import AIEngine
from ai.provider import LLMProvider, ProviderError, ProviderHealth
from ai.providers import AnthropicProvider


class RecordingProvider(LLMProvider):
    """Accepts the sampling controls and records every call."""

    def __init__(
        self,
        name: str,
        *,
        available: bool = True,
        raise_on_generate: Exception | None = None,
    ):
        self._name = name
        self._available = available
        self._raise = raise_on_generate
        self.calls: list[dict] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_id(self) -> str:
        return f"{self._name}-model"

    @property
    def is_available(self) -> bool:
        return self._available

    def generate(
        self,
        prompt: str,
        *,
        tools=None,
        temperature=None,
        max_tokens=None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self._raise:
            raise self._raise
        return f"{self._name} answer"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name, available=self._available
        )


class NarrowProvider(LLMProvider):
    """A provider that CANNOT accept the sampling controls."""

    @property
    def name(self) -> str:
        return "Ollama"

    @property
    def model_id(self) -> str:
        return "narrow-model"

    @property
    def is_available(self) -> bool:
        return True

    def generate(self, prompt: str, *, tools=None) -> str:
        return "narrow answer"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, available=True)


def test_auto_mode_forwards_generation_kwargs_to_the_provider():
    provider = RecordingProvider("Ollama")
    engine = AIEngine(providers=[provider])

    engine.generate_response(
        "hello",
        mode="auto",
        generation_kwargs={"temperature": 0.25, "max_tokens": 7},
    )

    assert provider.calls, "the provider was never called"
    assert provider.calls[0]["temperature"] == 0.25, (
        "AUTO mode dropped the temperature: "
        f"{provider.calls[0]!r}"
    )
    assert provider.calls[0]["max_tokens"] == 7, (
        "AUTO mode dropped the max_tokens: " f"{provider.calls[0]!r}"
    )


def test_auto_mode_fallback_also_forwards_generation_kwargs():
    local = RecordingProvider(
        "Ollama", raise_on_generate=RuntimeError("local is down")
    )
    cloud = RecordingProvider("OpenRouter")
    engine = AIEngine(providers=[local, cloud])

    engine.generate_response(
        "hello",
        mode="auto",
        generation_kwargs={"temperature": 0.0, "max_tokens": 256},
    )

    assert cloud.calls, (
        "the fallback provider was never called; the local provider "
        "failed on purpose"
    )
    assert cloud.calls[0]["temperature"] == 0.0
    assert cloud.calls[0]["max_tokens"] == 256, (
        "the AUTO fallback dropped the generation kwargs: "
        f"{cloud.calls[0]!r}"
    )


def test_explicit_local_mode_still_forwards_generation_kwargs():
    provider = RecordingProvider("Ollama")
    engine = AIEngine(providers=[provider])

    engine.generate_response(
        "hello",
        mode="local",
        generation_kwargs={"temperature": 0.5},
    )

    assert provider.calls[0]["temperature"] == 0.5


def test_no_kwargs_means_the_providers_own_defaults():
    provider = RecordingProvider("Ollama")
    engine = AIEngine(providers=[provider])

    engine.generate_response("hello", mode="auto")

    assert provider.calls[0]["temperature"] is None
    assert provider.calls[0]["max_tokens"] is None


def test_an_unsupported_generation_kwarg_is_reported_not_dropped():
    engine = AIEngine(providers=[NarrowProvider()])

    with pytest.raises(ProviderError) as excinfo:
        engine.generate_response(
            "hello",
            mode="auto",
            generation_kwargs={"totally_unsupported": 1},
        )

    assert "totally_unsupported" in str(excinfo.value), (
        "the unsupported kwarg was not named in the error: "
        f"{excinfo.value!r}"
    )


def test_an_unsupported_generation_kwarg_is_reported_in_explicit_mode():
    engine = AIEngine(providers=[NarrowProvider()])

    with pytest.raises(ProviderError) as excinfo:
        engine.generate_response(
            "hello",
            mode="local",
            generation_kwargs={"totally_unsupported": 1},
        )

    assert "totally_unsupported" in str(excinfo.value)


# --------------------------------------------------------------------------
# Provider level: Anthropic accepted the controls and ignored them
# --------------------------------------------------------------------------

class _FakeAnthropicResponse:
    def __init__(self, text: str):
        self.content = [SimpleNamespace(type="text", text=text)]


class _FakeMessages:
    def __init__(self, sink: list):
        self._sink = sink

    def create(self, **kwargs):
        self._sink.append(kwargs)
        return _FakeAnthropicResponse("anthropic answer")


class _FakeAnthropicClient:
    def __init__(self):
        self.calls: list[dict] = []

    @property
    def messages(self):
        return _FakeMessages(self.calls)


def test_the_anthropic_provider_honours_max_tokens_and_temperature():
    provider = AnthropicProvider(api_key="fake-key")
    fake = _FakeAnthropicClient()
    provider._client = fake
    provider._available = True

    provider.generate("hello", temperature=0.0, max_tokens=256)

    assert fake.calls, "the Anthropic client was never called"
    sent = fake.calls[0]
    assert sent.get("max_tokens") == 256, (
        f"Anthropic ignored max_tokens: {sent!r}"
    )
    assert sent.get("temperature") == 0.0, (
        f"Anthropic ignored temperature: {sent!r}"
    )


def test_the_anthropic_provider_keeps_its_default_output_cap():
    provider = AnthropicProvider(api_key="fake-key")
    fake = _FakeAnthropicClient()
    provider._client = fake
    provider._available = True

    provider.generate("hello")

    assert fake.calls[0].get("max_tokens") == 4096, (
        "the Anthropic default output cap changed: " f"{fake.calls[0]!r}"
    )
