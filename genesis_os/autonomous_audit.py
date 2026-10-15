from __future__ import annotations

import hashlib
import json
import time
import threading
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class DriftSeverity(str, Enum):
    NOMINAL = "nominal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SystemSnapshot:
    snapshot_id: str
    timestamp: float
    state_hash: str
    components: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "state_hash": self.state_hash,
            "components": self.components,
            "metadata": self.metadata,
        }


@dataclass
class DriftReport:
    report_id: str
    baseline_snapshot_id: str
    current_snapshot_id: str
    severity: DriftSeverity
    drift_score: float
    drifted_components: List[str]
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "baseline_snapshot_id": self.baseline_snapshot_id,
            "current_snapshot_id": self.current_snapshot_id,
            "severity": self.severity.value,
            "drift_score": self.drift_score,
            "drifted_components": self.drifted_components,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass
class CausalNode:
    node_id: str
    event_type: str
    component: str
    description: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_ids: List[str] = field(default_factory=list)


@dataclass
class CausalChain:
    chain_id: str
    root_cause: CausalNode
    nodes: List[CausalNode]
    chain_hash: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "root_cause": {
                "node_id": self.root_cause.node_id,
                "event_type": self.root_cause.event_type,
                "component": self.root_cause.component,
                "description": self.root_cause.description,
            },
            "nodes_count": len(self.nodes),
            "chain_hash": self.chain_hash,
            "timestamp": self.timestamp,
        }


@dataclass
class RollbackAction:
    action_id: str
    component: str
    operation: str
    snapshot_before: SystemSnapshot
    restore_fn: Optional[Callable] = None
    timestamp: float = field(default_factory=time.time)
    executed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "component": self.component,
            "operation": self.operation,
            "executed": self.executed,
            "timestamp": self.timestamp,
        }


class AutonomousAuditor:
    VERSION = "1.0.0"

    def __init__(
        self,
        drift_threshold: float = 0.15,
        auto_rollback: bool = True,
        max_history: int = 1000,
    ):
        self._lock = threading.RLock()
        self._drift_threshold = drift_threshold
        self._auto_rollback = auto_rollback
        self._max_history = max_history

        self._snapshots: Dict[str, SystemSnapshot] = {}
        self._baseline: Optional[SystemSnapshot] = None
        self._drift_reports: List[DriftReport] = []
        self._causal_chains: List[CausalChain] = []
        self._rollback_actions: List[RollbackAction] = []
        self._component_collectors: Dict[str, Callable[[], Any]] = {}
        self._drift_callbacks: List[Callable[[DriftReport], None]] = []
        self._state_history: List[Dict[str, Any]] = []

    def register_component(
        self, name: str, collector: Callable[[], Any]
    ) -> None:
        with self._lock:
            self._component_collectors[name] = collector

    def register_drift_callback(
        self, callback: Callable[[DriftReport], None]
    ) -> None:
        with self._lock:
            self._drift_callbacks.append(callback)

    def take_snapshot(self, extra: Optional[Dict[str, Any]] = None) -> SystemSnapshot:
        with self._lock:
            components: Dict[str, Any] = {}
            for name, collector in self._component_collectors.items():
                try:
                    components[name] = collector()
                except Exception as exc:
                    components[name] = {"error": str(exc)}

            if extra:
                components["_extra"] = extra

            state_str = json.dumps(components, sort_keys=True, default=str)
            state_hash = hashlib.sha256(state_str.encode()).hexdigest()[:16]
            snap_id = f"snap-{int(time.time() * 1000)}-{state_hash[:8]}"

            snapshot = SystemSnapshot(
                snapshot_id=snap_id,
                timestamp=time.time(),
                state_hash=state_hash,
                components=components,
            )
            self._snapshots[snap_id] = snapshot

            if len(self._snapshots) > self._max_history:
                oldest = sorted(
                    self._snapshots, key=lambda k: self._snapshots[k].timestamp
                )[: len(self._snapshots) - self._max_history]
                for k in oldest:
                    del self._snapshots[k]

            return snapshot

    def set_baseline(self, snapshot: Optional[SystemSnapshot] = None) -> SystemSnapshot:
        with self._lock:
            if snapshot is None:
                snapshot = self.take_snapshot()
            self._baseline = snapshot
            return snapshot

    def compute_drift(
        self, baseline: Optional[SystemSnapshot] = None, current: Optional[SystemSnapshot] = None
    ) -> DriftReport:
        with self._lock:
            if baseline is None:
                baseline = self._baseline
            if baseline is None:
                baseline = self.take_snapshot()
                self._baseline = baseline
            if current is None:
                current = self.take_snapshot()

            drifted_components = []
            component_scores: Dict[str, float] = {}
            details: Dict[str, Any] = {}

            all_keys = set(baseline.components.keys()) | set(current.components.keys())

            for key in all_keys:
                base_val = baseline.components.get(key)
                curr_val = current.components.get(key)
                score = self._compare_component(base_val, curr_val)
                component_scores[key] = score
                if score > self._drift_threshold:
                    drifted_components.append(key)
                    details[key] = {
                        "drift_score": score,
                        "baseline": str(base_val)[:200],
                        "current": str(curr_val)[:200],
                    }

            if not drifted_components:
                severity = DriftSeverity.NOMINAL
            elif len(drifted_components) == 1:
                max_score = max(component_scores.values())
                severity = (
                    DriftSeverity.LOW if max_score < 0.3
                    else DriftSeverity.MEDIUM if max_score < 0.6
                    else DriftSeverity.HIGH
                )
            else:
                avg_score = sum(
                    component_scores[c] for c in drifted_components
                ) / len(drifted_components)
                severity = (
                    DriftSeverity.MEDIUM if avg_score < 0.3
                    else DriftSeverity.HIGH if avg_score < 0.6
                    else DriftSeverity.CRITICAL
                )

            overall_score = (
                sum(component_scores.values()) / len(component_scores)
                if component_scores else 0.0
            )

            report = DriftReport(
                report_id=f"drift-{int(time.time() * 1000)}",
                baseline_snapshot_id=baseline.snapshot_id,
                current_snapshot_id=current.snapshot_id,
                severity=severity,
                drift_score=overall_score,
                drifted_components=drifted_components,
                details=details,
            )

            self._drift_reports.append(report)
            if len(self._drift_reports) > self._max_history:
                self._drift_reports = self._drift_reports[-self._max_history:]

            for cb in self._drift_callbacks:
                try:
                    cb(report)
                except Exception:
                    pass

            if self._auto_rollback and severity in (DriftSeverity.HIGH, DriftSeverity.CRITICAL):
                self._trigger_rollback(drifted_components, baseline)

            return report

    def _compare_component(self, baseline: Any, current: Any) -> float:
        if baseline == current:
            return 0.0
        if baseline is None or current is None:
            return 1.0 if baseline != current else 0.0
        base_str = json.dumps(baseline, sort_keys=True, default=str)
        curr_str = json.dumps(current, sort_keys=True, default=str)
        if base_str == curr_str:
            return 0.0
        base_set = set(base_str)
        curr_set = set(curr_str)
        union = base_set | curr_set
        if not union:
            return 0.0
        intersection = base_set & curr_set
        return 1.0 - (len(intersection) / len(union))

    def _trigger_rollback(
        self, components: List[str], baseline: SystemSnapshot
    ) -> List[RollbackAction]:
        actions = []
        for comp_name in components:
            action = RollbackAction(
                action_id=f"rollback-{comp_name}-{int(time.time() * 1000)}",
                component=comp_name,
                operation="auto_rollback",
                snapshot_before=baseline,
                restore_fn=None,
            )
            actions.append(action)
            self._rollback_actions.append(action)

        for action in actions:
            action.executed = True

        return actions

    def build_causal_chain(
        self, failure_event: Dict[str, Any]
    ) -> CausalChain:
        with self._lock:
            root = CausalNode(
                node_id=f"node-{int(time.time() * 1000)}",
                event_type=failure_event.get("event_type", "unknown"),
                component=failure_event.get("component", "unknown"),
                description=failure_event.get("description", ""),
                timestamp=time.time(),
                metadata=failure_event.get("metadata", {}),
                parent_ids=failure_event.get("parent_ids", []),
            )

            nodes = [root]
            related_events = failure_event.get("related_events", [])
            for evt in related_events:
                node = CausalNode(
                    node_id=f"node-{int(time.time() * 1000)}-{len(nodes)}",
                    event_type=evt.get("event_type", "cascade"),
                    component=evt.get("component", "unknown"),
                    description=evt.get("description", ""),
                    timestamp=evt.get("timestamp", time.time()),
                    metadata=evt.get("metadata", {}),
                    parent_ids=[root.node_id],
                )
                nodes.append(node)

            chain_str = json.dumps(
                [{"component": n.component, "event_type": n.event_type} for n in nodes],
                sort_keys=True,
            )
            chain_hash = hashlib.sha256(chain_str.encode()).hexdigest()[:16]

            chain = CausalChain(
                chain_id=f"chain-{int(time.time() * 1000)}",
                root_cause=root,
                nodes=nodes,
                chain_hash=chain_hash,
            )

            self._causal_chains.append(chain)
            return chain

    def continuous_audit(
        self,
        interval_seconds: float = 60.0,
        callback: Optional[Callable[[DriftReport], None]] = None,
    ) -> Callable[[], None]:
        stop_event = threading.Event()

        def _audit_loop():
            while not stop_event.is_set():
                try:
                    report = self.compute_drift()
                    if callback:
                        callback(report)
                except Exception:
                    pass
                stop_event.wait(interval_seconds)

        thread = threading.Thread(target=_audit_loop, daemon=True, name="autonomous-audit")
        thread.start()

        def stop():
            stop_event.set()

        return stop

    def get_audit_summary(self) -> Dict[str, Any]:
        with self._lock:
            severity_counts = {}
            for report in self._drift_reports:
                sev = report.severity.value
                severity_counts[sev] = severity_counts.get(sev, 0) + 1

            return {
                "version": self.VERSION,
                "baseline_set": self._baseline is not None,
                "total_snapshots": len(self._snapshots),
                "total_drift_reports": len(self._drift_reports),
                "total_causal_chains": len(self._causal_chains),
                "total_rollback_actions": len(self._rollback_actions),
                "severity_distribution": severity_counts,
                "drift_threshold": self._drift_threshold,
                "auto_rollback_enabled": self._auto_rollback,
                "registered_components": list(self._component_collectors.keys()),
            }

    def get_drift_history(
        self, severity: Optional[DriftSeverity] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        with self._lock:
            reports = self._drift_reports
            if severity:
                reports = [r for r in reports if r.severity == severity]
            return [r.to_dict() for r in reports[-limit:]]

    def get_causal_chains(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [c.to_dict() for c in self._causal_chains[-limit:]]
