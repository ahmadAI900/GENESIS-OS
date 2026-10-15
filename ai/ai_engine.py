"""
Genesis OS — Level 4.0 Dual Model Intelligence Layer

Supports:

    LOCAL
        Ollama
        Qwen 2.5 0.5B

    CLOUD
        OpenAI-compatible API (OpenRouter)

    EXTRA
        Additional providers via the LLMProvider interface

Modes:

    auto
    local
    cloud

AUTO mode:
    1. Prefer cloud for complex requests
    2. Use local for simple requests
    3. Automatically fall back if the selected backend fails

The rest of Genesis only talks to AIEngine.

Level 4.0 change: internal routing now goes through ``LLMProvider``
instances instead of raw ``OpenAI`` clients.  The public API
(``generate_response``, ``status``, ``use_local/cloud/auto``) is
unchanged.
"""

import concurrent.futures
import logging
import os
import time
from typing import Any, Dict, Iterator, List, Optional

from dotenv import load_dotenv

from .provider import LLMProvider, ProviderError, ProviderHealth
from .providers import AnthropicProvider, GroqProvider, OllamaProvider, OpenRouterProvider

logger = logging.getLogger("genesis_os.ai_engine")


def estimate_tokens(text: str) -> int:
    """Estimate token count for *text*.

    Heuristic: ``len(text) // 4``. This is a documented estimate
    only — never claimed to be exact. Provider tokenizers differ
    per model; use for telemetry/cost hints, never for billing.
    """
    if not text:
        return 0
    return len(text) // 4


class AIEngine:
    """
    Unified intelligence interface for Genesis OS.

    Brain, agents, reasoning and synthesis do not need to know
    which model is being used.
    """

    def __init__(
        self,
        providers: Optional[List[LLMProvider]] = None,
    ):
        load_dotenv()

        # =====================================================
        # CONFIGURATION
        # =====================================================

        self.mode = os.getenv(
            "GENESIS_AI_MODE",
            "auto"
        ).lower().strip()

        # =====================================================
        # PROVIDERS
        # =====================================================

        if providers is not None:
            # DI path: callers supply pre-built providers.
            self._providers: List[LLMProvider] = list(providers)
        else:
            # Default path: build from .env (backward-compatible).
            self._providers = self._build_default_providers()

        # Build name-indexed lookup for status / switching
        self._provider_by_name: Dict[str, LLMProvider] = {
            p.name: p for p in self._providers
        }

        # Legacy attributes preserved for callers that read them
        # directly (status(), _print_status(), etc.)
        self._sync_legacy_attributes()

        # Per-call token/cost telemetry (estimates only, never exact).
        # Each record: {provider, model, prompt_tokens_est,
        #   completion_tokens_est, latency_ms, timestamp}.
        self._usage_records: List[Dict[str, Any]] = []
        self.request_timeout = float(os.getenv("GENESIS_LLM_TIMEOUT_SECONDS", "60"))

        # -----------------------------------------------------
        # STARTUP REPORT
        # -----------------------------------------------------

        self._print_status()

    # =========================================================
    # DEFAULT PROVIDER CONSTRUCTION (backward-compatible)
    # =========================================================

    @staticmethod
    def _build_default_providers() -> List[LLMProvider]:
        """
        Construct the default Ollama + OpenRouter providers from
        environment variables, mirroring the original AIEngine
        constructor logic exactly.
        """
        providers: List[LLMProvider] = []

        # LOCAL / OLLAMA
        ollama = OllamaProvider(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"),
        )
        providers.append(ollama)

        # CLOUD / OPENROUTER
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            openrouter = OpenRouterProvider(
                api_key=openrouter_key,
                base_url=os.getenv(
                    "OPENROUTER_BASE_URL",
                    "https://openrouter.ai/api/v1",
                ),
                model=os.getenv(
                    "OPENROUTER_MODEL",
                    "nvidia/nemotron-3-super-120b-a12b:free",
                ),
            )
            providers.append(openrouter)

        # CLOUD / GROQ
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            groq = GroqProvider(
                api_key=groq_key,
                base_url=os.getenv(
                    "GROQ_BASE_URL",
                    "https://api.groq.com/openai/v1",
                ),
                model=os.getenv(
                    "GROQ_MODEL",
                    "openai/gpt-oss-120b",
                ),
            )
            providers.append(groq)

        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            providers.append(
                AnthropicProvider(
                    api_key=anthropic_key,
                    model=os.getenv(
                        "ANTHROPIC_MODEL",
                        "claude-sonnet-4-20250514",
                    ),
                )
            )

        return providers

    # =========================================================
    # LEGACY ATTRIBUTE SYNC
    # =========================================================
    #
    # Some callers (status, _print_status, tests) read attributes
    # like ``self.local_available``, ``self.cloud_model``, etc.
    # We sync these from the provider objects so existing code
    # continues to work without modification.

    def _sync_legacy_attributes(self) -> None:
        local = self._get_provider("Ollama")
        cloud = self._get_provider("OpenRouter")

        self.local_available = local.is_available if local else False
        self.cloud_available = cloud.is_available if cloud else False

        self.local_model = local.model_id if local else ""
        self.cloud_model = cloud.model_id if cloud else ""

        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.ollama_api_key = os.getenv("OLLAMA_API_KEY", "ollama")
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.api_base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        # Clients kept for backward compat (agents may check truthiness)
        self.local_client = local._client if local and hasattr(local, "_client") else None
        self.cloud_client = cloud._client if cloud and hasattr(cloud, "_client") else None

    def _get_provider(self, name: str) -> Optional[LLMProvider]:
        return self._provider_by_name.get(name)

    # =========================================================
    # STATUS
    # =========================================================

    def _print_status(self) -> None:
        logger.info("AI Engine Intelligence Layer initialized.")
        logger.info("Mode: %s", self.mode)

        local = self._get_provider("Ollama")
        logger.info("Ollama: %s",
            f"ONLINE ({local.model_id})" if local and local.is_available else "OFFLINE")

        cloud = self._get_provider("OpenRouter")
        logger.info("Cloud API: %s",
            f"ONLINE ({cloud.model_id})" if cloud and cloud.is_available else "OFFLINE")

        for p in self._providers:
            if p.name not in ("Ollama", "OpenRouter"):
                status_str = "ONLINE" if p.is_available else "OFFLINE"
                logger.info("%s: %s (%s)", p.name, status_str, p.model_id)

    # =========================================================
    # PUBLIC API
    # =========================================================

    def generate_response(
        self,
        prompt: str,
        mode: Optional[str] = None,
        complexity: Optional[str] = None,
        generation_kwargs: Optional[dict] = None,
    ) -> str:
        if not prompt or not prompt.strip():
            return "Genesis AI received an empty prompt."

        requested_mode = (mode or self.mode).lower().strip()

        # -----------------------------------------------------
        # EXPLICIT LOCAL
        # -----------------------------------------------------

        if requested_mode == "local":
            return self._generate_from_provider(
                self._get_provider("Ollama"), "local", prompt,
                generation_kwargs=generation_kwargs,
            )

        # -----------------------------------------------------
        # EXPLICIT CLOUD
        # -----------------------------------------------------

        if requested_mode == "cloud":
            return self._generate_from_provider(
                self._get_cloud_provider(), "cloud", prompt,
                generation_kwargs=generation_kwargs,
            )

        # -----------------------------------------------------
        # AUTO
        # -----------------------------------------------------

        selected = self._select_backend(prompt, complexity)
        logger.debug("Selected backend: %s", selected)

        # -----------------------------------------------------
        # LOCAL FIRST
        # -----------------------------------------------------

        if selected == "local":
            local = self._get_provider("Ollama")
            cloud = self._get_cloud_provider()

            try:
                return self._generate_from_provider(local, "local", prompt)
            except Exception as local_error:
                logger.debug("Local model failed: %s", local_error)

                if cloud and cloud.is_available:
                    logger.debug("Falling back to cloud.")
                    try:
                        return self._generate_from_provider(cloud, "cloud", prompt)
                    except Exception as cloud_error:
                        return (
                            "Genesis AI could not generate "
                            "a response.\n"
                            f"Local error: {local_error}\n"
                            f"Cloud error: {cloud_error}"
                        )

                return (
                    "Genesis AI could not generate "
                    "a response from the local model."
                )

        # -----------------------------------------------------
        # CLOUD FIRST
        # -----------------------------------------------------

        cloud = self._get_cloud_provider()
        local = self._get_provider("Ollama")

        try:
            return self._generate_from_provider(cloud, "cloud", prompt)
        except Exception as cloud_error:
            logger.debug("Cloud model failed: %s", cloud_error)

            if local and local.is_available:
                logger.debug("Falling back to Ollama.")
                try:
                    return self._generate_from_provider(local, "local", prompt)
                except Exception as local_error:
                    return (
                        "Genesis AI could not generate "
                        "a response.\n"
                        f"Cloud error: {cloud_error}\n"
                        f"Local error: {local_error}"
                    )

            return (
                "Genesis AI could not generate "
                "a response from the cloud model."
            )

    # =========================================================
    # PROVIDER HELPERS
    # =========================================================

    def _get_cloud_provider(self) -> Optional[LLMProvider]:
        """Return the first available cloud provider.

        Tries OpenRouter first, then Groq, then any non-Ollama
        provider that is available.
        """
        for name in ("OpenRouter", "Groq"):
            p = self._get_provider(name)
            if p and p.is_available:
                return p
        for p in self._providers:
            if p.name != "Ollama" and p.is_available:
                return p
        return None

    # =========================================================
    # PROVIDER DISPATCH
    # =========================================================

    @property
    def supports_tool_calling(self) -> bool:
        """True when any available provider supports tool-calling."""
        return any(
            p.supports_tool_calling and p.is_available
            for p in self._providers
        )

    def generate_with_tools(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Unified tool-calling gateway for the Agent Framework adapter.

        Routes via ``_get_cloud_provider`` or Ollama, falling back
        across all supporting providers.  Never bypasses the gateway:
        only ``LLMProvider.generate_with_tools`` is called — no direct
        ``OpenAI``/``AsyncOpenAI`` client use here.

        Returns ``{"text": str, "tool_calls": [...]}`` on success or
        ``{"error": ...}`` when no supporting provider can serve.
        """
        tool_defs: List[Dict[str, Any]] = list(tools or [])

        # Ordered candidates: cloud first, then Ollama, then the rest.
        candidates: List[LLMProvider] = []
        cloud = self._get_cloud_provider()
        if (
            cloud is not None
            and cloud.supports_tool_calling
            and cloud.is_available
        ):
            candidates.append(cloud)
        local = self._get_provider("Ollama")
        if (
            local is not None
            and local not in candidates
            and local.supports_tool_calling
            and local.is_available
        ):
            candidates.append(local)
        for p in self._providers:
            if (
                p not in candidates
                and p.supports_tool_calling
                and p.is_available
            ):
                candidates.append(p)

        if not candidates:
            return {"error": "tool calling not supported"}

        last_error: Optional[str] = None
        for provider in candidates:
            try:
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = executor.submit(provider.generate_with_tools, prompt, tool_defs)
                try:
                    result = future.result(timeout=self.request_timeout)
                except concurrent.futures.TimeoutError as exc:
                    future.cancel()
                    raise ProviderError(
                        provider=provider.name,
                        message=f"Tool request exceeded {self.request_timeout:g} seconds.",
                        retryable=True,
                    ) from exc
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            except ProviderError as exc:
                last_error = str(exc)
                continue
            except Exception as exc:  # defensive: keep falling back
                last_error = str(exc)
                continue
            if (
                isinstance(result, dict)
                and result.get("error") == "tool calling not supported"
            ):
                last_error = result["error"]
                continue
            if isinstance(result, dict):
                return result
            last_error = f"{provider.name} returned malformed tool result."
        return {"error": last_error or "tool calling not supported"}

    def _generate_from_provider(
        self,
        provider: Optional[LLMProvider],
        label: str,
        prompt: str = "",
        generation_kwargs: Optional[dict] = None,
    ) -> str:
        """
        Generate from a single provider, translating ProviderError
        and unexpected exceptions into the string-return pattern
        callers expect.

        Records per-call usage telemetry (token estimates + latency)
        on success. Token counts are ``estimate_tokens`` heuristics,
        never exact provider counts.

        ``generation_kwargs`` carries optional sampling controls
        (temperature, max_tokens) to the provider. It is optional and
        defaults to None so every existing caller keeps the provider
       's own defaults unchanged; it exists because some callers need
        DETERMINISTIC output and a bounded response length, which the
        OpenAI-compatible endpoints otherwise do not provide.
        """
        if provider is None:
            raise RuntimeError(f"{label} provider is not configured.")

        if not provider.is_available:
            raise RuntimeError(f"{label} provider is not available.")

        logger.debug("%s -> %s", label, provider.model_id)
        start = time.monotonic()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            provider.generate,
            prompt=prompt,
            **dict(generation_kwargs or {}),
        )
        try:
            result = future.result(timeout=self.request_timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise ProviderError(
                provider=provider.name,
                message=f"Provider request exceeded {self.request_timeout:g} seconds.",
                retryable=True,
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        self._usage_records.append(
            {
                "provider": provider.name,
                "model": provider.model_id,
                "prompt_tokens_est": estimate_tokens(prompt),
                "completion_tokens_est": estimate_tokens(result),
                "latency_ms": latency_ms,
                "timestamp": time.time(),
            }
        )
        return result

    # =========================================================
    # INTELLIGENT BACKEND SELECTION
    # =========================================================

    def _select_backend(
        self,
        prompt: str,
        complexity: Optional[str] = None,
    ) -> str:
        local = self._get_provider("Ollama")
        cloud = self._get_cloud_provider()

        # -----------------------------------------------------
        # Explicit complexity from caller
        # -----------------------------------------------------

        if complexity:
            complexity = complexity.lower().strip()

            if complexity in ("simple", "low"):
                if local and local.is_available:
                    return "local"

            if complexity in ("complex", "high", "reasoning"):
                if cloud and cloud.is_available:
                    return "cloud"

        # -----------------------------------------------------
        # Automatic complexity detection
        # -----------------------------------------------------

        text = prompt.lower()

        complex_signals = [
            "research",
            "analyze",
            "analysis",
            "compare",
            "strategy",
            "strategic",
            "roadmap",
            "architecture",
            "design a system",
            "debug",
            "security",
            "multi-agent",
            "comprehensive",
            "end-to-end",
            "synthesize",
            "synthesis",
            "business plan",
            "technical report",
            "evaluate",
            "reason",
        ]

        if any(signal in text for signal in complex_signals):
            if cloud and cloud.is_available:
                return "cloud"
            if local and local.is_available:
                return "local"

        # -----------------------------------------------------
        # Simple request
        # -----------------------------------------------------

        if local and local.is_available:
            return "local"

        if cloud and cloud.is_available:
            return "cloud"

        return "local"

    # =========================================================
    # INFORMATION API
    # =========================================================

    def status(self) -> Dict:
        prompt_total = sum(r["prompt_tokens_est"] for r in self._usage_records)
        completion_total = sum(
            r["completion_tokens_est"] for r in self._usage_records
        )
        return {
            "mode": self.mode,
            "local": {
                "available": self.local_available,
                "model": self.local_model,
            },
            "cloud": {
                "available": self.cloud_available,
                "model": self.cloud_model,
            },
            "providers": [
                {
                    "name": p.name,
                    "model": p.model_id,
                    "available": p.is_available,
                }
                for p in self._providers
            ],
            "usage": {
                "calls": len(self._usage_records),
                "prompt_tokens_est": prompt_total,
                "completion_tokens_est": completion_total,
                "total_tokens_est": prompt_total + completion_total,
            },
        }

    def last_usage(self) -> Dict | None:
        """Return the most recent per-call usage record, or None.

        Records are estimates (see ``estimate_tokens``), never exact
        provider-billed token counts.
        """
        if not self._usage_records:
            return None
        return dict(self._usage_records[-1])

    def stream_generate(
        self,
        prompt: str,
        mode: Optional[str] = None,
        chunk_size: int = 200,
    ) -> Iterator[str]:
        """Yield real SSE streaming chunks when a provider supports it.

        Tries each available provider's ``stream_text()`` in routing
        order (respecting *mode* / auto-selection) and yields the
        genuine ``delta.content`` chunks as collected from the SSE
        stream — these are live model tokens, not local slices.
        Per-call usage is recorded into ``_usage_records`` with an
        honest ``usage_source`` (``"api"`` when the server sent a
        trailing usage chunk, else ``"estimated"``); token counts
        are never faked.

        Fallback: only when NO provider streams successfully
        (no ``stream_text`` support, all providers unavailable, or
        every stream fell back to ``streamed=False``), this calls
        :meth:`generate_response` once and yields the finished text
        in ``chunk_size``-character slices for UI progressive
        rendering. That fallback path is local chunking, NOT live
        tokens (``generate_response`` already records its own usage
        entry in that case).
        """
        requested_mode = (mode or self.mode).lower().strip()

        # ---- Build ordered streaming candidates (routing-aware) ----
        ordered: List[LLMProvider] = []
        if requested_mode == "local":
            local = self._get_provider("Ollama")
            if local is not None:
                ordered.append(local)
        elif requested_mode == "cloud":
            cloud = self._get_cloud_provider()
            if cloud is not None:
                ordered.append(cloud)
        else:  # auto: selected backend first, then the other side
            selected = self._select_backend(prompt, None)
            local = self._get_provider("Ollama")
            cloud = self._get_cloud_provider()
            if selected == "local":
                if local is not None:
                    ordered.append(local)
                if cloud is not None and cloud not in ordered:
                    ordered.append(cloud)
            else:
                if cloud is not None:
                    ordered.append(cloud)
                if local is not None and local not in ordered:
                    ordered.append(local)
            for p in self._providers:
                if p not in ordered:
                    ordered.append(p)

        # ---- Try real streaming on each supporting provider ----
        for provider in ordered:
            if provider is None or not provider.is_available:
                continue
            stream_fn = getattr(provider, "stream_text", None)
            if not callable(stream_fn):
                continue
            collected: List[str] = []
            start = time.monotonic()
            try:
                result = stream_fn(prompt, chunk_handler=collected.append)
            except Exception:
                continue  # try next provider
            if not isinstance(result, dict) or not result.get("text"):
                continue
            if not result.get("streamed"):
                # Provider fell back to non-stream generate internally;
                # not a real stream — try the next provider.
                continue
            usage = result.get("usage") or {}
            usage_source = result.get("usage_source", "estimated")
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            self._usage_records.append(
                {
                    "provider": provider.name,
                    "model": provider.model_id,
                    "prompt_tokens_est": usage.get(
                        "prompt_tokens", estimate_tokens(prompt)
                    ),
                    "completion_tokens_est": usage.get(
                        "completion_tokens",
                        estimate_tokens(result["text"]),
                    ),
                    "prompt_tokens": usage.get(
                        "prompt_tokens", estimate_tokens(prompt)
                    ),
                    "completion_tokens": usage.get(
                        "completion_tokens",
                        estimate_tokens(result["text"]),
                    ),
                    "usage_source": usage_source,
                    "streamed": True,
                    "latency_ms": latency_ms,
                    "timestamp": time.time(),
                }
            )
            if collected:
                for piece in collected:
                    yield piece
            else:
                # Streamed flag true but handler got nothing (e.g.
                # mock returns text without per-chunk callbacks):
                # yield the real text as a single chunk.
                yield result["text"]
            return

        # ---- Fallback: single generate + honest local chunking ----
        # generate_response() records its own _usage_records entry.
        text = self.generate_response(prompt, mode=mode)
        if not text:
            return
        if chunk_size <= 0:
            yield text
            return
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]

    # =========================================================
    # BACKEND CONTROL
    # =========================================================

    def use_local(self) -> None:
        self.mode = "local"
        logger.debug("Backend switched to LOCAL.")

    def use_cloud(self) -> None:
        self.mode = "cloud"
        logger.debug("Backend switched to CLOUD.")

    def use_auto(self) -> None:
        self.mode = "auto"
        logger.debug("Backend switched to AUTO.")

    # =========================================================
    # HEALTH CHECK (Level 4.0 addition)
    # =========================================================

    def health_check(self) -> Dict[str, ProviderHealth]:
        """
        Run health checks on all registered providers.

        Returns a dict keyed by provider name.
        """
        results: Dict[str, ProviderHealth] = {}
        for p in self._providers:
            results[p.name] = p.health_check()
        return results
