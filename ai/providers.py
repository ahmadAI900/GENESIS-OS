"""
Genesis OS — Concrete LLM Provider Implementations.

OllamaProvider     — local Ollama via OpenAI-compatible endpoint
OpenRouterProvider — cloud OpenRouter via OpenAI-compatible endpoint
GroqProvider       — cloud Groq via OpenAI-compatible endpoint
AnthropicProvider  — direct Anthropic Messages API (genuinely different SDK)

Each implements the ``LLMProvider`` ABC from ``ai/provider.py``.
The existing Ollama + OpenRouter logic is preserved exactly; the
Anthropic adapter demonstrates that the interface works with a
non-OpenAI-compatible provider.  GroqProvider demonstrates that a
fourth genuinely different backend integrates cleanly.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from .provider import LLMProvider, ProviderError, ProviderHealth

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

try:
    import anthropic as _anthropic_sdk
except ImportError:
    _anthropic_sdk = None  # type: ignore[assignment]


# =========================================================
# HELPER: token estimate (honest approximation, never exact)
# =========================================================


def estimate_tokens(text: str) -> int:
    """Estimate token count for *text*.

    Heuristic: ``len(text) // 4``. This is a rough estimate only —
    never claimed to be an exact tokenizer count. Real providers
    bill with their own tokenizers (tiktoken, Anthropic, etc.),
    which this helper does not replicate. Use for cost/latency
    telemetry and UI hints only, never for billing.
    """
    if not text:
        return 0
    return len(text) // 4


# =========================================================
# HELPER: normalise OpenAI-style errors into ProviderError
# =========================================================


def _normalise_openai_error(
    exc: Exception,
    provider_name: str,
) -> ProviderError:
    """Translate an openai.* exception into a standardised ProviderError."""
    status_code: Optional[int] = None
    retryable = False

    # openai.AuthenticationError, openai.RateLimitError, etc.
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        # Some openai exceptions store it as a response attribute
        resp = getattr(exc, "response", None)
        if resp is not None:
            status_code = getattr(resp, "status_code", None)

    if status_code == 429:
        retryable = True
    elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        retryable = True
    elif status_code is None and not isinstance(exc, ValueError):
        # Unknown exception type — treat as retryable
        retryable = True

    return ProviderError(
        provider=provider_name,
        message=str(exc),
        status_code=status_code,
        retryable=retryable,
        original_error=exc,
    )


def _normalise_anthropic_error(
    exc: Exception,
    provider_name: str,
) -> ProviderError:
    """Translate an anthropic.* exception into a standardised ProviderError."""
    status_code: Optional[int] = None
    retryable = False

    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        resp = getattr(exc, "response", None)
        if resp is not None:
            status_code = getattr(resp, "status_code", None)

    if status_code == 429:
        retryable = True
    elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        retryable = True
    elif status_code is None:
        retryable = True

    return ProviderError(
        provider=provider_name,
        message=str(exc),
        status_code=status_code,
        retryable=retryable,
        original_error=exc,
    )


# =========================================================
# HELPER: parse OpenAI-compatible tool-call responses
# =========================================================


def _parse_openai_tool_calls(response: Any) -> Dict[str, Any]:
    """Extract structured {text, tool_calls} from a Chat Completions response."""
    import json as _json

    message = response.choices[0].message
    text = message.content or ""
    tool_calls: List[Dict[str, Any]] = []
    for tc in getattr(message, "tool_calls", None) or []:
        func = getattr(tc, "function", None)
        name = getattr(func, "name", "") if func else getattr(tc, "name", "")
        raw_args = getattr(func, "arguments", "") if func else getattr(tc, "arguments", "")
        try:
            arguments = _json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
        except Exception:
            arguments = raw_args
        tool_calls.append({
            "id": getattr(tc, "id", ""),
            "type": getattr(tc, "type", "function"),
            "name": name,
            "arguments": arguments,
        })
    return {"text": text.strip(), "tool_calls": tool_calls}


# =========================================================
# HELPER: real SSE streaming for OpenAI-compatible providers
# (Phase 4: real stream + real usage, never faked)
# =========================================================


def _extract_stream_delta(chunk: Any) -> str:
    """Extract ``choices[0].delta.content`` from a stream chunk.

    Handles both SDK objects and plain dicts (test fakes).
    Returns "" when the chunk carries no text (e.g. usage-only
    trailing chunk or role-only first chunk).
    """
    try:
        choices = getattr(chunk, "choices", None)
        if choices is None and isinstance(chunk, dict):
            choices = chunk.get("choices")
        if not choices:
            return ""
        first = choices[0]
        if isinstance(first, dict):
            delta = first.get("delta", {}) or {}
            if isinstance(delta, dict):
                content = delta.get("content")
            else:
                content = getattr(delta, "content", None)
        else:
            delta = getattr(first, "delta", None)
            if isinstance(delta, dict):
                content = delta.get("content")
            else:
                content = getattr(delta, "content", None) if delta is not None else None
        return content if isinstance(content, str) else ""
    except Exception:
        return ""


def _extract_stream_usage(chunk: Any) -> Optional[Dict[str, int]]:
    """Extract trailing ``usage`` from a stream chunk, if present.

    Returns ``{"prompt_tokens": int, "completion_tokens": int}``
    only when BOTH counts are present as ints; otherwise None
    (caller then falls back to honest estimates).
    """
    try:
        usage = getattr(chunk, "usage", None)
        if usage is None and isinstance(chunk, dict):
            usage = chunk.get("usage")
        if usage is None:
            return None
        if isinstance(usage, dict):
            pt = usage.get("prompt_tokens")
            ct = usage.get("completion_tokens")
        else:
            pt = getattr(usage, "prompt_tokens", None)
            ct = getattr(usage, "completion_tokens", None)
        if isinstance(pt, int) and isinstance(ct, int):
            return {"prompt_tokens": pt, "completion_tokens": ct}
        return None
    except Exception:
        return None


def _run_openai_stream(
    *,
    client: Any,
    model: str,
    prompt: str,
    provider_name: str,
    chunk_handler: Optional[Callable[[str], None]],
    fallback_generate: Callable[[str], str],
) -> Dict[str, Any]:
    """Run a real SSE stream against an OpenAI-compatible endpoint.

    Calls ``client.chat.completions.create(..., stream=True,
    stream_options={"include_usage": True})``, collects
    ``delta.content`` pieces (forwarding each to *chunk_handler*),
    and captures the trailing ``usage`` chunk when sent.

    On ANY stream error, falls back to *fallback_generate* (the
    provider's non-stream ``generate``) and returns
    ``streamed: False`` with a ``fallback`` reason. Token counts
    are NEVER faked: ``usage_source`` is ``"api"`` only when the
    API actually sent usage; otherwise honest ``estimate_tokens``
    values with ``usage_source: "estimated"``.
    """
    if client is None:
        reason = "stream client not available"
        text = fallback_generate(prompt)  # may raise ProviderError
        return {
            "text": text,
            "streamed": False,
            "fallback": reason,
            "usage": {
                "prompt_tokens": estimate_tokens(prompt),
                "completion_tokens": estimate_tokens(text),
            },
            "usage_source": "estimated",
        }

    stream_error: Optional[Exception] = None
    parts: List[str] = []
    api_usage: Optional[Dict[str, int]] = None

    try:
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                stream_options={"include_usage": True},
            )
        except TypeError as te:
            # Some OpenAI-compatible backends reject stream_options;
            # retry once without it rather than faking a failure.
            msg = str(te).lower()
            if "stream_options" in msg or "unexpected" in msg:
                stream = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                )
            else:
                raise
        for chunk in stream:
            usage = _extract_stream_usage(chunk)
            if usage is not None:
                api_usage = usage
            piece = _extract_stream_delta(chunk)
            if piece:
                parts.append(piece)
                if chunk_handler is not None:
                    chunk_handler(piece)
        text = "".join(parts).strip()
        if not text:
            raise RuntimeError("stream returned empty response")
    except Exception as exc:  # noqa: BLE001 - any SSE failure -> honest fallback
        stream_error = exc

    if stream_error is not None:
        reason = f"{type(stream_error).__name__}: {stream_error}"
        text = fallback_generate(prompt)  # may raise; propagated to caller
        return {
            "text": text,
            "streamed": False,
            "fallback": reason,
            "usage": {
                "prompt_tokens": estimate_tokens(prompt),
                "completion_tokens": estimate_tokens(text),
            },
            "usage_source": "estimated",
        }

    text = "".join(parts).strip()
    if api_usage is not None:
        return {
            "text": text,
            "streamed": True,
            "usage": api_usage,
            "usage_source": "api",
        }
    return {
        "text": text,
        "streamed": True,
        "usage": {
            "prompt_tokens": estimate_tokens(prompt),
            "completion_tokens": estimate_tokens(text),
        },
        "usage_source": "estimated",
    }


# =========================================================
# OLLAMA (LOCAL)
# =========================================================


class OllamaProvider(LLMProvider):
    """
    Local Ollama provider via the OpenAI-compatible /v1 endpoint.

    Mirrors the existing ``AIEngine._generate_local`` logic
    exactly — same client construction, same call pattern, same
    empty-response check.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        model: str = "qwen2.5:0.5b",
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout = float(timeout)
        self._client: Optional[Any] = None
        self._available = False
        self._initialise()

    def _initialise(self) -> None:
        if OpenAI is None:
            self._available = False
            return
        try:
            self._client = OpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout=self._timeout,
            )
            self._available = True
        except Exception:
            self._available = False

    @property
    def name(self) -> str:
        return "Ollama"

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def supports_tool_calling(self) -> bool:
        return True

    def generate_with_tools(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """OpenAI-compatible function-calling via chat.completions with tools."""
        if not self._client:
            return {"error": "Ollama client is not available."}
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                tools=tools or [],
            )
        except Exception as exc:
            raise _normalise_openai_error(exc, self.name) from exc
        return _parse_openai_tool_calls(response)

    # Prompts at least this large are sent to the native endpoint.
    # Capability selection sends a ~3k-character capability index,
    # comfortably above it, while ordinary chat prompts stay on the
    # OpenAI-compatible path they have always used.
    _NATIVE_MIN_PROMPT_CHARS = 1500

    @property
    def _native_root(self) -> str:
        """base_url points at /v1; the native API lives at the root."""
        root = (self._base_url or "").rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        return root

    def _generate_native(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Call Ollama's native /api/generate endpoint.

        Used because the OpenAI-compatibility layer imposes a
        wall-clock ceiling (~188s observed) that a large prompt
        exceeds on a CPU-only host, even though the model answers
        correctly and in reasonable time when given the chance.
        """

        import urllib.request

        options: Dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = int(max_tokens)

        body = json.dumps({
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }).encode("utf-8")

        url = f"{self._native_root}/api/generate"
        request = urllib.request.Request(url, data=body)

        # No client-side ceiling: the caller bounds the whole
        # request with its own budget, and a second competing
        # timeout is what caused the original failure.
        with urllib.request.urlopen(request, timeout=None) as response:
            payload = json.loads(response.read().decode("utf-8"))

        content = payload.get("response")
        if not content:
            raise ProviderError(
                provider=self.name,
                message="Ollama native endpoint returned no content.",
                retryable=True,
            )
        return str(content).strip()

    def generate(
        self,
        prompt: str,
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if not self._client:
            raise ProviderError(
                provider=self.name,
                message="Ollama client is not available.",
                retryable=False,
            )

        # Long prompts go to the NATIVE endpoint first.
        #
        # MEASURED 2026-09-28 on a CPU-only host: a 772-token
        # capability-selection prompt that takes 209s to prefill and
        # answer correctly (verified: it returned the right
        # shortlist) was killed at ~188s by the OpenAI-compatibility
        # layer with "Request timed out". The identical prompt sent
        # to /api/generate completed and returned the correct
        # answer. The shim's ceiling, not model latency, was the
        # binding constraint, and it presented as "the model
        # declined" for every single request.
        #
        # Native-first is therefore not a preference: it is what
        # makes local selection usable on a slow host. Any failure
        # falls back to the shim, so behaviour is unchanged when
        # the native endpoint is unavailable.
        if not tools and len(prompt) > self._NATIVE_MIN_PROMPT_CHARS:
            try:
                return self._generate_native(
                    prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception:
                pass

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Optional deterministic-sampling controls. Omitted
        # entirely when unset, so every existing caller keeps the
        # provider's own defaults unchanged.
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools and self.supports_tool_calling:
            kwargs["tools"] = tools

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise _normalise_openai_error(exc, self.name) from exc

        content = response.choices[0].message.content
        if not content:
            raise ProviderError(
                provider=self.name,
                message="Ollama returned an empty response.",
                retryable=True,
            )
        return content.strip()

    def stream_text(
        self,
        prompt: str,
        chunk_handler: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Real SSE streaming via OpenAI-compatible ``stream=True``.

        Returns ``{text, streamed, usage, usage_source}`` (plus
        ``fallback`` reason when falling back to :meth:`generate`).
        Usage is ``"api"`` only when the server sent a trailing
        usage chunk; otherwise honest ``estimate_tokens`` values
        with ``usage_source: "estimated"``. Never fakes tokens.
        """
        return _run_openai_stream(
            client=self._client,
            model=self._model,
            prompt=prompt,
            provider_name=self.name,
            chunk_handler=chunk_handler,
            fallback_generate=self.generate,
        )

    def health_check(self) -> ProviderHealth:
        start = time.monotonic()
        try:
            if not self._client:
                return ProviderHealth(
                    provider=self.name,
                    available=False,
                    error="Client not initialised.",
                )
            # Lightweight completions call
            self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.name,
                available=True,
                latency_ms=round(latency, 1),
                model_id=self._model,
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.name,
                available=False,
                latency_ms=round(latency, 1),
                model_id=self._model,
                error=str(exc),
            )


# =========================================================
# OPENROUTER (CLOUD)
# =========================================================


class OpenRouterProvider(LLMProvider):
    """
    Cloud OpenRouter provider via the OpenAI-compatible /v1 endpoint.

    Mirrors the existing ``AIEngine._generate_cloud`` logic
    exactly — same client construction, same call pattern, same
    empty-response check.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        model: str = "nvidia/nemotron-3-super-120b-a12b:free",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout = float(timeout)
        self._client: Optional[Any] = None
        self._available = False
        self._initialise()

    def _initialise(self) -> None:
        if not self._api_key:
            self._available = False
            return
        if OpenAI is None:
            self._available = False
            return
        try:
            kwargs: Dict[str, Any] = {
                "api_key": self._api_key,
                "timeout": self._timeout,
            }
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
            self._available = True
        except Exception:
            self._available = False

    @property
    def name(self) -> str:
        return "OpenRouter"

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def supports_tool_calling(self) -> bool:
        return True

    def generate_with_tools(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """OpenAI-compatible function-calling via chat.completions with tools."""
        if not self._client:
            return {"error": "Cloud API client is not available."}
        if not self._model:
            return {"error": "OPENROUTER_MODEL is not configured."}
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                tools=tools or [],
            )
        except Exception as exc:
            raise _normalise_openai_error(exc, self.name) from exc
        return _parse_openai_tool_calls(response)

    def generate(
        self,
        prompt: str,
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if not self._client:
            raise ProviderError(
                provider=self.name,
                message="Cloud API client is not available.",
                retryable=False,
            )
        if not self._model:
            raise ProviderError(
                provider=self.name,
                message="OPENROUTER_MODEL is not configured.",
                retryable=False,
            )

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Optional deterministic-sampling controls. Omitted
        # entirely when unset, so every existing caller keeps the
        # provider's own defaults unchanged.
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools and self.supports_tool_calling:
            kwargs["tools"] = tools

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise _normalise_openai_error(exc, self.name) from exc

        content = response.choices[0].message.content
        if not content:
            raise ProviderError(
                provider=self.name,
                message="Cloud API returned an empty response.",
                retryable=True,
            )
        return content.strip()

    def stream_text(
        self,
        prompt: str,
        chunk_handler: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Real SSE streaming via OpenAI-compatible ``stream=True``.

        Returns ``{text, streamed, usage, usage_source}`` (plus
        ``fallback`` reason when falling back to :meth:`generate`).
        Usage is ``"api"`` only when the server sent a trailing
        usage chunk; otherwise honest ``estimate_tokens`` values
        with ``usage_source: "estimated"``. Never fakes tokens.
        """
        return _run_openai_stream(
            client=self._client,
            model=self._model,
            prompt=prompt,
            provider_name=self.name,
            chunk_handler=chunk_handler,
            fallback_generate=self.generate,
        )

    def health_check(self) -> ProviderHealth:
        start = time.monotonic()
        try:
            if not self._client:
                return ProviderHealth(
                    provider=self.name,
                    available=False,
                    error="Client not initialised.",
                )
            self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.name,
                available=True,
                latency_ms=round(latency, 1),
                model_id=self._model,
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.name,
                available=False,
                latency_ms=round(latency, 1),
                model_id=self._model,
                error=str(exc),
            )


# =========================================================
# GROQ (CLOUD — OPENAI-COMPATIBLE, DIFFERENT BACKEND)
# =========================================================


class GroqProvider(LLMProvider):
    """
    Cloud Groq provider via the OpenAI-compatible /v1 endpoint.

    Groq provides extremely low-latency inference on open models.
    This provider is a first-class LLMProvider, distinct from
    OpenRouterProvider, with its own env-var namespace (GROQ_*)
    and health-check / error-normalization behaviour matching
    the other providers exactly.

    Requires ``GROQ_API_KEY`` in the environment.  When the key
    is absent the provider reports ``is_available=False``.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.groq.com/openai/v1",
        model: str = "openai/gpt-oss-120b",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout = float(timeout)
        self._client: Optional[Any] = None
        self._available = False
        self._initialise()

    def _initialise(self) -> None:
        if not self._api_key:
            self._available = False
            return
        if OpenAI is None:
            self._available = False
            return
        try:
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
            )
            self._available = True
        except Exception:
            self._available = False

    @property
    def name(self) -> str:
        return "Groq"

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def supports_tool_calling(self) -> bool:
        return True

    def generate_with_tools(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """OpenAI-compatible function-calling via chat.completions with tools."""
        if not self._client:
            return {"error": "Groq client is not available."}
        if not self._model:
            return {"error": "GROQ_MODEL is not configured."}
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                tools=tools or [],
            )
        except Exception as exc:
            raise _normalise_openai_error(exc, self.name) from exc
        return _parse_openai_tool_calls(response)

    def generate(
        self,
        prompt: str,
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if not self._client:
            raise ProviderError(
                provider=self.name,
                message="Groq client is not available.",
                retryable=False,
            )
        if not self._model:
            raise ProviderError(
                provider=self.name,
                message="GROQ_MODEL is not configured.",
                retryable=False,
            )

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Optional deterministic-sampling controls. Omitted
        # entirely when unset, so every existing caller keeps the
        # provider's own defaults unchanged.
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools and self.supports_tool_calling:
            kwargs["tools"] = tools

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise _normalise_openai_error(exc, self.name) from exc

        content = response.choices[0].message.content
        if not content:
            raise ProviderError(
                provider=self.name,
                message="Groq returned an empty response.",
                retryable=True,
            )
        return content.strip()

    def stream_text(
        self,
        prompt: str,
        chunk_handler: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Real SSE streaming via OpenAI-compatible ``stream=True``.

        Returns ``{text, streamed, usage, usage_source}`` (plus
        ``fallback`` reason when falling back to :meth:`generate`).
        Usage is ``"api"`` only when the server sent a trailing
        usage chunk; otherwise honest ``estimate_tokens`` values
        with ``usage_source: "estimated"``. Never fakes tokens.
        """
        return _run_openai_stream(
            client=self._client,
            model=self._model,
            prompt=prompt,
            provider_name=self.name,
            chunk_handler=chunk_handler,
            fallback_generate=self.generate,
        )

    def health_check(self) -> ProviderHealth:
        start = time.monotonic()
        try:
            if not self._client:
                return ProviderHealth(
                    provider=self.name,
                    available=False,
                    error="Client not initialised.",
                )
            self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.name,
                available=True,
                latency_ms=round(latency, 1),
                model_id=self._model,
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.name,
                available=False,
                latency_ms=round(latency, 1),
                model_id=self._model,
                error=str(exc),
            )


# =========================================================
# ANTHROPIC (DIRECT — GENUINELY DIFFERENT SDK)
# =========================================================


class AnthropicProvider(LLMProvider):
    """
    Direct Anthropic Messages API provider.

    This is the **conformance proof** provider: it uses the
    ``anthropic`` SDK (NOT the OpenAI SDK), which means:

    - Different HTTP wire format (Anthropic Messages API, not
      OpenAI Chat Completions API).
    - Different authentication header (``x-api-key`` + ``anthropic-version``).
    - Different request/response schema.

    If the capability layer (ActionExecutor, Agent Framework
    adapter, CapabilityRegistry) cares about which LLM is
    answering, this provider will break something.  If it
    genuinely doesn't care, this provider will work identically
    to the OpenAI-compatible ones.

    Requires ``ANTHROPIC_API_KEY`` in the environment.  When the
    key is absent the provider reports ``is_available=False`` and
    the conformance test skips gracefully.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = float(timeout)
        self._client: Optional[Any] = None
        self._available = False
        self._initialise()

    def _initialise(self) -> None:
        if _anthropic_sdk is None:
            return
        if not self._api_key:
            return
        try:
            self._client = _anthropic_sdk.Anthropic(
                api_key=self._api_key,
                timeout=self._timeout,
            )
            self._available = True
        except Exception:
            self._available = False

    @property
    def name(self) -> str:
        return "Anthropic"

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def supports_tool_calling(self) -> bool:
        # Implemented via the native Anthropic tool_use path:
        # OpenAI-format tools are converted, tool_use blocks are
        # parsed back into the gateway {text, tool_calls} shape.
        return True

    def generate_with_tools(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Native Anthropic function-calling, normalised to {text, tool_calls}."""
        if not self._client:
            return {"error": "Anthropic client is not available."}
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:
            raise _normalise_anthropic_error(exc, self.name) from exc
        text_parts: list[str] = []
        tool_calls: List[Dict[str, Any]] = []
        for block in getattr(response, "content", []) or []:
            btype = getattr(block, "type", "")
            if btype == "text":
                text_parts.append(getattr(block, "text", ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": getattr(block, "id", ""),
                    "type": "function",
                    "name": getattr(block, "name", ""),
                    "arguments": getattr(block, "input", {}) or {},
                })
        return {"text": "\n".join(text_parts).strip(), "tool_calls": tool_calls}

    def generate(
        self,
        prompt: str,
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if not self._client:
            raise ProviderError(
                provider=self.name,
                message="Anthropic client is not available.",
                retryable=False,
            )

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }

        # Anthropic's tool format differs from OpenAI's.
        # Convert OpenAI-format tools to Anthropic format if provided.
        if tools and self.supports_tool_calling:
            kwargs["tools"] = self._convert_tools(tools)

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:
            raise _normalise_anthropic_error(exc, self.name) from exc

        # Extract text from Anthropic response blocks
        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", "") == "text":
                text_parts.append(block.text)
        content = "\n".join(text_parts).strip()

        if not content:
            raise ProviderError(
                provider=self.name,
                message="Anthropic returned an empty response.",
                retryable=True,
            )
        return content

    @staticmethod
    def _convert_tools(
        openai_tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Convert OpenAI-format tool definitions to Anthropic format.

        OpenAI: {"type": "function", "function": {"name": ..., "parameters": ...}}
        Anthropic: {"name": ..., "input_schema": ..., "description": ...}
        """
        anthropic_tools: List[Dict[str, Any]] = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                anthropic_tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })
            else:
                # Pass through unknown tool formats
                anthropic_tools.append(tool)
        return anthropic_tools

    def health_check(self) -> ProviderHealth:
        start = time.monotonic()
        try:
            if not self._client:
                return ProviderHealth(
                    provider=self.name,
                    available=False,
                    error="Client not initialised.",
                )
            self._client.messages.create(
                model=self._model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.name,
                available=True,
                latency_ms=round(latency, 1),
                model_id=self._model,
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ProviderHealth(
                provider=self.name,
                available=False,
                latency_ms=round(latency, 1),
                model_id=self._model,
                error=str(exc),
            )
