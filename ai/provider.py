"""
Genesis OS — Level 4.0 Model-Agnostic LLM Provider Interface.

Defines the explicit contract that every LLM provider must satisfy
so the rest of Genesis never depends on a specific model or vendor.

The interface is an ABC (not a Protocol) so Pydantic validation can
be layered on for structured provider configs, and concrete
implementations get a shared ``generate`` contract enforced at
construction time.

Design constraints:
    - ``generate`` is synchronous (matches existing AIEngine callers).
    - Tool-calling schemas flow through the same OpenAI-compatible
      ``tools`` kwarg regardless of provider.
    - Health checks are lightweight and non-blocking.
    - Provider errors are normalised into ``ProviderError`` so a 429
      from ANY provider is handled identically upstream.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# =========================================================
# STANDARDIZED ERROR
# =========================================================


class ProviderError(Exception):
    """
    Standardised error raised by any ``LLMProvider`` implementation.

    Carries enough metadata so upstream code (AIEngine fallback,
    logging, user-facing messages) can handle ANY provider's errors
    uniformly without provider-specific ``except`` branches.
    """

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: Optional[int] = None,
        retryable: bool = False,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.provider = provider
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.original_error = original_error
        super().__init__(f"[{provider}] {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "message": self.message,
            "status_code": self.status_code,
            "retryable": self.retryable,
        }


# =========================================================
# HEALTH CHECK RESULT
# =========================================================


@dataclass(frozen=True)
class ProviderHealth:
    """
    Structured health-check result for any provider.

    Same shape regardless of whether the provider is Ollama,
    OpenRouter, Anthropic, or anything else.
    """

    provider: str
    available: bool
    latency_ms: Optional[float] = None
    model_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "latency_ms": self.latency_ms,
            "model_id": self.model_id,
            "error": self.error,
        }


# =========================================================
# PROVIDER ABC
# =========================================================


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Every concrete provider must implement ``generate`` and
    ``health_check``.  The ``name`` and ``model_id`` properties
    identify the provider in logs, status reports, and error
    messages.

    The ``generate`` signature is deliberately minimal — just a
    prompt string in, text string out — matching the existing
    ``AIEngine.generate_response`` contract that every Genesis
    consumer already depends on.

    Unified tool-calling flows through the gateway:

        - ``supports_tool_calling`` reports per-provider capability.
        - ``generate_with_tools`` performs OpenAI-compatible
          function-calling via the provider's own client and
          returns a structured ``{text, tool_calls}`` dict.
        - ``AIEngine.generate_with_tools`` routes across providers
          with fallback, so the Agent Framework adapter calls the
          gateway instead of constructing ``AsyncOpenAI`` directly.
          Streaming is not used by any current Genesis consumer.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'Ollama', 'OpenRouter')."""
        ...

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Model identifier (e.g. 'qwen2.5:0.5b', 'nvidia/nemotron-3-super-120b-a12b:free')."""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """True when the provider has been initialised and is ready to serve requests."""
        ...

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Send a prompt to the LLM and return the text response.

        Parameters
        ----------
        prompt:
            The user/system prompt text.
        tools:
            Optional OpenAI-format tool definitions for
            function-calling.  Providers that support tool-calling
            forward these to the model; providers that don't
            ignore them silently (the caller checks
            ``supports_tool_calling`` before passing tools).

        Returns
        -------
        str
            The model's response text (stripped of leading/trailing
            whitespace).

        Raises
        ------
        ProviderError
            On any failure (network, auth, rate-limit, empty
            response).  ``retryable`` is True when the caller
            should try a different provider or retry later.
        """
        ...

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """
        Lightweight, non-blocking availability check.

        Returns a ``ProviderHealth`` with ``available=True`` when
        the provider can serve requests, ``False`` otherwise.
        """
        ...

    @property
    def supports_tool_calling(self) -> bool:
        """True when the provider passes ``tools`` through to the model."""
        return False

    def generate_with_tools(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Send a prompt plus OpenAI-format tool definitions and return
        a structured result.

        Default implementation for providers without tool-calling
        support.  Concrete providers that support function-calling
        override this using their own client (OpenAI-compatible
        ``chat.completions`` with ``tools`` param, or the native
        equivalent).

        Returns
        -------
        dict
            On success: ``{"text": str, "tool_calls": [...]}``.
            When unsupported: ``{"error": "tool calling not supported"}``.
        """
        return {"error": "tool calling not supported"}

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} model={self.model_id!r}>"
