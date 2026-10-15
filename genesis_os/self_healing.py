from __future__ import annotations

import time
import threading
import random
import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class HealthMetric(str, Enum):
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    MEMORY = "memory"
    CPU = "cpu"
    THROUGHPUT = "throughput"
    AVAILABILITY = "availability"


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    FAILED = "failed"


@dataclass
class ProviderHealth:
    provider_name: str
    state: HealthState = HealthState.HEALTHY
    metrics: Dict[str, float] = field(default_factory=dict)
    history: deque = field(default_factory=lambda: deque(maxlen=100))
    last_check: float = 0.0
    failure_count: int = 0
    recovery_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "state": self.state.value,
            "metrics": dict(self.metrics),
            "history_len": len(self.history),
            "last_check": self.last_check,
            "failure_count": self.failure_count,
            "recovery_count": self.recovery_count,
        }


@dataclass
class MigrationPlan:
    plan_id: str
    source_provider: str
    target_provider: str
    reason: str
    state_snapshot: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    executed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "source_provider": self.source_provider,
            "target_provider": self.target_provider,
            "reason": self.reason,
            "state_snapshot": self.state_snapshot,
            "created_at": self.created_at,
            "executed": self.executed,
        }


@dataclass
class ChaosExperiment:
    experiment_id: str
    target_provider: str
    fault_type: str
    duration_seconds: float
    severity: float = 0.5
    active: bool = False
    results: Dict[str, Any] = field(default_factory=dict)
    _start_time: float = field(default=0.0, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "target_provider": self.target_provider,
            "fault_type": self.fault_type,
            "duration_seconds": self.duration_seconds,
            "severity": self.severity,
            "active": self.active,
            "results": self.results,
        }


class SelfHealingOrchestrator:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._health_records: Dict[str, ProviderHealth] = {}
        self._migration_plans: List[MigrationPlan] = []
        self._chaos_experiments: Dict[str, ChaosExperiment] = {}
        self._rebalance_strategies: Dict[str, Any] = {}
        self._event_log: deque = deque(maxlen=5000)
        self._lock = threading.RLock()
        self._monitoring_active = False
        self._check_interval_seconds = 30.0
        self._monitor_thread: Optional[threading.Thread] = None

    def _log_event(self, event_type: str, detail: str) -> None:
        self._event_log.append({
            "timestamp": time.time(),
            "type": event_type,
            "detail": detail,
        })

    def _generate_id(self, prefix: str) -> str:
        raw = f"{prefix}_{time.time()}_{random.random()}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _ensure_provider(self, provider_name: str) -> ProviderHealth:
        if provider_name not in self._health_records:
            self._health_records[provider_name] = ProviderHealth(
                provider_name=provider_name, last_check=time.time()
            )
        return self._health_records[provider_name]

    def record_metric(self, provider_name: str, metric_name: str, value: float) -> None:
        with self._lock:
            health = self._ensure_provider(provider_name)
            health.metrics[metric_name] = value
            health.history.append({"timestamp": time.time(), "metric": metric_name, "value": value})
            health.last_check = time.time()
            old_state = health.state
            health.state = self._evaluate_health_state(provider_name)
            if old_state != health.state:
                self._log_event(
                    "state_change",
                    f"{provider_name}: {old_state.value} -> {health.state.value}",
                )
                if health.state == HealthState.FAILED:
                    health.failure_count += 1
                elif old_state in (HealthState.CRITICAL, HealthState.FAILED) and health.state == HealthState.HEALTHY:
                    health.recovery_count += 1

    def _evaluate_health_state(self, provider_name: str) -> HealthState:
        health = self._health_records.get(provider_name)
        if not health or not health.history:
            return HealthState.HEALTHY
        cutoff = time.time() - 300
        recent_errors = []
        recent_latencies = []
        for entry in health.history:
            if entry["timestamp"] < cutoff:
                continue
            if entry["metric"] == "error_rate":
                recent_errors.append(entry["value"])
            elif entry["metric"] == "latency":
                recent_latencies.append(entry["value"])
        avg_error = sum(recent_errors) / len(recent_errors) if recent_errors else 0.0
        avg_latency = sum(recent_latencies) / len(recent_latencies) if recent_latencies else 0.0
        if avg_error > 50:
            return HealthState.FAILED
        if avg_latency < 200 and avg_error < 5:
            return HealthState.HEALTHY
        if avg_latency < 500 and avg_error < 15:
            return HealthState.DEGRADED
        return HealthState.CRITICAL

    def get_provider_health(self, provider_name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            health = self._health_records.get(provider_name)
            return health.to_dict() if health else None

    def create_migration_plan(self, source: str, target: str, reason: str) -> MigrationPlan:
        with self._lock:
            plan = MigrationPlan(
                plan_id=self._generate_id("mig"),
                source_provider=source,
                target_provider=target,
                reason=reason,
                state_snapshot={},
                created_at=time.time(),
            )
            self._migration_plans.append(plan)
            self._log_event("migration_plan_created", plan.to_dict())
            return plan

    def execute_migration(self, plan_id: str) -> bool:
        with self._lock:
            for plan in self._migration_plans:
                if plan.plan_id == plan_id and not plan.executed:
                    plan.executed = True
                    self._log_event("migration_executed", plan.to_dict())
                    return True
            return False

    def start_chaos_experiment(
        self, target: str, fault_type: str, duration: float, severity: float
    ) -> ChaosExperiment:
        with self._lock:
            exp = ChaosExperiment(
                experiment_id=self._generate_id("chaos"),
                target_provider=target,
                fault_type=fault_type,
                duration_seconds=duration,
                severity=max(0.0, min(1.0, severity)),
                active=True,
                _start_time=time.time(),
            )
            self._chaos_experiments[exp.experiment_id] = exp
            self._log_event("chaos_started", exp.to_dict())
            return exp

    def stop_chaos_experiment(self, experiment_id: str) -> bool:
        with self._lock:
            exp = self._chaos_experiments.get(experiment_id)
            if exp and exp.active:
                exp.active = False
                exp.results["stopped_at"] = time.time()
                self._log_event("chaos_stopped", exp.to_dict())
                return True
            return False

    def _should_inject_fault(self, experiment: ChaosExperiment) -> bool:
        if not experiment.active:
            return False
        elapsed = time.time() - experiment._start_time
        return elapsed < experiment.duration_seconds

    def inject_fault(self, provider_name: str, original_fn: Callable, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            for exp in self._chaos_experiments.values():
                if exp.target_provider == provider_name and self._should_inject_fault(exp):
                    self._apply_fault(exp)
                    if exp.fault_type == "error_injection":
                        raise RuntimeError(f"Chaos fault: {exp.fault_type} on {provider_name}")
                    if exp.fault_type == "latency_injection":
                        time.sleep(exp.severity * 0.5)
                    elif exp.fault_type == "resource_exhaustion":
                        _ = [0] * int(exp.severity * 1_000_000)
        return original_fn(*args, **kwargs)

    def _apply_fault(self, experiment: ChaosExperiment) -> None:
        experiment.results.setdefault("injection_count", 0)
        experiment.results["injection_count"] += 1

    def rebalance(self, provider_names: List[str]) -> str:
        with self._lock:
            scores = self.get_health_scores()
            eligible = [p for p in provider_names if scores.get(p, 0) > 0.0]
            if not eligible:
                return provider_names[0] if provider_names else ""
            weights = [scores.get(p, 0.5) for p in eligible]
            return random.choices(eligible, weights=weights, k=1)[0]

    def get_health_scores(self) -> Dict[str, float]:
        with self._lock:
            scores: Dict[str, float] = {}
            for name, health in self._health_records.items():
                score = 1.0
                history = list(health.history)
                recent = [e for e in history if e["timestamp"] > time.time() - 300]
                errors = [e["value"] for e in recent if e["metric"] == "error_rate"]
                latencies = [e["value"] for e in recent if e["metric"] == "latency"]
                if errors:
                    avg_err = sum(errors) / len(errors)
                    score -= min(0.4, avg_err / 100)
                if latencies:
                    avg_lat = sum(latencies) / len(latencies)
                    score -= min(0.3, avg_lat / 2000)
                if health.state == HealthState.CRITICAL:
                    score -= 0.2
                elif health.state == HealthState.FAILED:
                    score = 0.0
                scores[name] = max(0.0, min(1.0, score))
            return scores

    def predict_failure(self, provider_name: str) -> Dict[str, Any]:
        with self._lock:
            health = self._health_records.get(provider_name)
            if not health:
                return {"provider": provider_name, "risk": "unknown", "imminent": False}
            history = [e for e in health.history if e["metric"] in ("error_rate", "latency")]
            if len(history) < 5:
                return {"provider": provider_name, "risk": "insufficient_data", "imminent": False}
            errors = [e["value"] for e in history if e["metric"] == "error_rate"][-20:]
            latencies = [e["value"] for e in history if e["metric"] == "latency"][-20:]
            imminent = False
            risk = "low"
            if len(errors) >= 3:
                trend = errors[-1] - errors[0]
                if trend > 20 and errors[-1] > 30:
                    imminent = True
                    risk = "high"
                elif trend > 10:
                    risk = "medium"
            if len(latencies) >= 3:
                trend = latencies[-1] - latencies[0]
                if trend > 300 and latencies[-1] > 500:
                    imminent = True
                    risk = "high"
            return {
                "provider": provider_name,
                "risk": risk,
                "imminent": imminent,
                "current_state": health.state.value,
                "error_trend": errors[-1] if errors else 0,
                "latency_trend": latencies[-1] if latencies else 0,
            }

    def start_monitoring(self, check_fn: Callable, interval: float) -> None:
        with self._lock:
            if self._monitoring_active:
                return
            self._monitoring_active = True
            self._check_interval_seconds = interval

            def _monitor_loop() -> None:
                while self._monitoring_active:
                    try:
                        check_fn()
                    except Exception as exc:
                        self._log_event("monitor_error", str(exc))
                    time.sleep(self._check_interval_seconds)

            self._monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
            self._monitor_thread.start()
            self._log_event("monitoring_started", f"interval={interval}s")

    def stop_monitoring(self) -> None:
        with self._lock:
            self._monitoring_active = False
            self._log_event("monitoring_stopped", "monitoring halted")

    def get_orchestrator_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "total_providers_tracked": len(self._health_records),
                "active_experiments": sum(1 for e in self._chaos_experiments.values() if e.active),
                "total_experiments": len(self._chaos_experiments),
                "migration_plans": len(self._migration_plans),
                "executed_migrations": sum(1 for p in self._migration_plans if p.executed),
                "event_count": len(self._event_log),
                "monitoring_active": self._monitoring_active,
            }
