from __future__ import annotations

import json
import time
import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ModalityType(Enum):
    TEXT = "text"
    VISION = "vision"
    AUDIO = "audio"
    CODE = "code"
    MULTIMODAL = "multimodal"


class RoutingStrategy(Enum):
    FASTEST = "fastest"
    HIGHEST_QUALITY = "highest_quality"
    LOWEST_COST = "lowest_cost"
    SPECULATIVE = "speculative"
    ROUND_ROBIN = "round_robin"


@dataclass
class ModelEndpoint:
    endpoint_id: str
    name: str
    modalities: List[ModalityType]
    base_url: str
    api_key: str
    model_id: str
    cost_per_1k_tokens: float
    max_tokens: int
    supports_streaming: bool
    supports_tools: bool
    latency_p50_ms: float
    latency_p99_ms: float
    quality_score: float = 0.8
    available: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "name": self.name,
            "modalities": [m.value for m in self.modalities],
            "base_url": self.base_url,
            "model_id": self.model_id,
            "cost_per_1k_tokens": self.cost_per_1k_tokens,
            "max_tokens": self.max_tokens,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.supports_tools,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "quality_score": self.quality_score,
            "available": self.available,
            "metadata": self.metadata,
        }


@dataclass
class RouterRequest:
    request_id: str
    content: Any
    modality: ModalityType
    strategy: RoutingStrategy = RoutingStrategy.FASTEST
    tools: List[Dict] = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "content": self.content,
            "modality": self.modality.value,
            "strategy": self.strategy.value,
            "tools": self.tools,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }


@dataclass
class RouterResponse:
    response_id: str
    request_id: str
    content: Any
    endpoint_id: str
    latency_ms: float
    tokens_used: int
    cost_usd: float
    quality_score: float = 1.0
    from_speculative: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response_id": self.response_id,
            "request_id": self.request_id,
            "content": self.content,
            "endpoint_id": self.endpoint_id,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "quality_score": self.quality_score,
            "from_speculative": self.from_speculative,
            "error": self.error,
        }


class MultimodalRouter:
    VERSION = "1.0.0"

    def __init__(
        self,
        default_strategy: RoutingStrategy = RoutingStrategy.FASTEST,
        speculative_window_ms: float = 2000.0,
        max_workers: int = 4,
    ):
        self._lock = threading.RLock()
        self.default_strategy = default_strategy
        self.speculative_window_ms = speculative_window_ms
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._endpoints: Dict[str, ModelEndpoint] = {}
        self._usage_history: List[Dict] = []
        self._quality_history: List[float] = []
        self._latency_history: List[float] = []
        self._cost_history: List[float] = []
        self._distillation_cache: Dict[str, Any] = {}
        self._round_robin_index: int = 0

    def register_endpoint(self, endpoint: ModelEndpoint) -> None:
        with self._lock:
            self._endpoints[endpoint.endpoint_id] = endpoint

    def unregister_endpoint(self, endpoint_id: str) -> None:
        with self._lock:
            self._endpoints.pop(endpoint_id, None)

    def route(self, request: RouterRequest, handler: Any) -> RouterResponse:
        with self._lock:
            strategy = request.strategy or self.default_strategy
            candidates = self._select_candidates(request)
            if not candidates:
                return RouterResponse(
                    response_id=f"resp_{request.request_id}", request_id=request.request_id,
                    content=None, endpoint_id="", latency_ms=0, tokens_used=0,
                    cost_usd=0, error="No available endpoint for modality",
                )
            if strategy == RoutingStrategy.SPECULATIVE and len(candidates) > 1:
                return self._speculative_route(request, handler, candidates)
            return self._single_route(request, handler, candidates[0])

    def _select_candidates(self, request: RouterRequest) -> List[ModelEndpoint]:
        strategy = request.strategy or self.default_strategy
        candidates = [ep for ep in self._endpoints.values()
                      if ep.available and (request.modality in ep.modalities
                      or ModalityType.MULTIMODAL in ep.modalities)]
        if strategy == RoutingStrategy.FASTEST:
            candidates.sort(key=lambda e: e.latency_p50_ms)
        elif strategy == RoutingStrategy.HIGHEST_QUALITY:
            candidates.sort(key=lambda e: e.quality_score, reverse=True)
        elif strategy == RoutingStrategy.LOWEST_COST:
            candidates.sort(key=lambda e: e.cost_per_1k_tokens)
        elif strategy == RoutingStrategy.ROUND_ROBIN:
            idx = self._round_robin_index % max(len(candidates), 1)
            if candidates:
                candidates = [candidates[idx]]
                self._round_robin_index += 1
        elif strategy != RoutingStrategy.SPECULATIVE:
            candidates.sort(key=lambda e: e.latency_p50_ms)
        return candidates

    def _single_route(self, request: RouterRequest, handler: Any,
                       endpoint: ModelEndpoint) -> RouterResponse:
        start = time.time()
        try:
            content, tokens = handler(endpoint, request)
            latency = (time.time() - start) * 1000
            cost = (tokens / 1000.0) * endpoint.cost_per_1k_tokens
            resp = RouterResponse(
                response_id=f"resp_{request.request_id}", request_id=request.request_id,
                content=content, endpoint_id=endpoint.endpoint_id,
                latency_ms=latency, tokens_used=tokens, cost_usd=cost,
                quality_score=endpoint.quality_score,
            )
            self._record_usage(endpoint.endpoint_id, latency, tokens, cost)
            return resp
        except Exception as exc:
            latency = (time.time() - start) * 1000
            return RouterResponse(
                response_id=f"resp_{request.request_id}", request_id=request.request_id,
                content=None, endpoint_id=endpoint.endpoint_id,
                latency_ms=latency, tokens_used=0, cost_usd=0, error=str(exc),
            )

    def _speculative_route(self, request: RouterRequest, handler: Any,
                           candidates: List[ModelEndpoint]) -> RouterResponse:
        import uuid
        futures: Dict[str, concurrent.futures.Future] = {}
        for ep in candidates[:3]:
            futures[ep.endpoint_id] = self._executor.submit(self._safe_call, handler, ep, request)
        deadline = time.time() + self.speculative_window_ms / 1000.0
        best: Optional[Tuple[str, Any, int, float, float]] = None
        while time.time() < deadline:
            for eid, fut in list(futures.items()):
                if fut.done():
                    result = fut.result()
                    if result is not None:
                        content, tokens, ep_id = result
                        ep = self._endpoints[ep_id]
                        cost = (tokens / 1000.0) * ep.cost_per_1k_tokens
                        if best is None or ep.quality_score > best[4]:
                            best = (eid, content, tokens, cost, ep.quality_score)
                    del futures[eid]
            if not futures:
                break
            time.sleep(0.01)
        for fut in futures.values():
            fut.cancel()
        if best is None:
            return self._single_route(request, handler, candidates[0])
        eid, content, tokens, cost, qs = best
        return RouterResponse(
            response_id=f"resp_{uuid.uuid4().hex[:12]}", request_id=request.request_id,
            content=content, endpoint_id=eid, latency_ms=self.speculative_window_ms,
            tokens_used=tokens, cost_usd=cost, quality_score=qs, from_speculative=True,
        )

    def _safe_call(self, handler: Any, endpoint: ModelEndpoint, request: RouterRequest
                   ) -> Optional[Tuple[Any, int, str]]:
        try:
            content, tokens = handler(endpoint, request)
            return content, tokens, endpoint.endpoint_id
        except Exception:
            return None

    def _record_usage(self, endpoint_id: str, latency_ms: float, tokens: int, cost_usd: float) -> None:
        with self._lock:
            self._latency_history.append(latency_ms)
            self._cost_history.append(cost_usd)
            self._quality_history.append(self._endpoints[endpoint_id].quality_score)
            self._usage_history.append({
                "endpoint_id": endpoint_id, "latency_ms": latency_ms,
                "tokens": tokens, "cost_usd": cost_usd, "timestamp": time.time(),
            })

    def distill(self, teacher_endpoint_id: str, student_endpoint_id: str,
                sample_prompts: List[Any], handler: Any) -> Dict[str, Any]:
        with self._lock:
            teacher = self._endpoints.get(teacher_endpoint_id)
            student = self._endpoints.get(student_endpoint_id)
            if not teacher or not student:
                return {"error": "endpoint not found"}
            req = RouterRequest(
                request_id="distill",
                content=sample_prompts[0] if sample_prompts else "",
                modality=ModalityType.TEXT,
            )
            t_resp = self._safe_call(handler, teacher, req)
            s_resp = self._safe_call(handler, student, req)
            ratio = 1.0
            if t_resp and s_resp:
                ratio = s_resp[1] / max(t_resp[1], 1)
            key = f"{teacher_endpoint_id}->{student_endpoint_id}"
            result = {
                "teacher": teacher_endpoint_id, "student": student_endpoint_id,
                "quality_ratio": ratio,
                "teacher_available": t_resp is not None,
                "student_available": s_resp is not None,
            }
            self._distillation_cache[key] = result
            return result

    def get_router_summary(self) -> Dict[str, Any]:
        with self._lock:
            total_cost = sum(self._cost_history)
            total_calls = len(self._usage_history)
            avg_lat = (sum(self._latency_history) / len(self._latency_history)
                       if self._latency_history else 0)
            return {
                "version": self.VERSION,
                "endpoint_count": len(self._endpoints),
                "total_calls": total_calls,
                "total_cost_usd": round(total_cost, 6),
                "avg_latency_ms": round(avg_lat, 2),
                "distillations_cached": len(self._distillation_cache),
                "endpoints": {k: v.to_dict() for k, v in self._endpoints.items()},
            }

    def get_endpoint_stats(self, endpoint_id: str) -> Dict[str, Any]:
        with self._lock:
            records = [r for r in self._usage_history if r["endpoint_id"] == endpoint_id]
            if not records:
                return {"endpoint_id": endpoint_id, "calls": 0}
            latencies = [r["latency_ms"] for r in records]
            tokens = [r["tokens"] for r in records]
            costs = [r["cost_usd"] for r in records]
            errors = [r for r in records if r.get("error")]
            return {
                "endpoint_id": endpoint_id,
                "calls": len(records),
                "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
                "total_tokens": sum(tokens),
                "total_cost_usd": round(sum(costs), 6),
                "success_rate": round((len(records) - len(errors)) / max(len(records), 1), 4),
            }
