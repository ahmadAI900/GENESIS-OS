from __future__ import annotations

import hashlib
import json
import math
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class PatternType(str, Enum):
    SEQUENTIAL = "sequential"
    TEMPORAL = "temporal"
    SPATIAL = "spatial"
    PREFERENCE = "preference"
    ERROR_RECOVERY = "error_recovery"


@dataclass
class CapabilityUsageRecord:
    record_id: str
    capability_id: str
    agent_id: str
    timestamp: float
    success: bool
    duration_ms: float
    context: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "capability_id": self.capability_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "success": self.success,
            "duration_ms": self.duration_ms,
        }


@dataclass
class UsagePattern:
    pattern_id: str
    pattern_type: PatternType
    capabilities: List[str]
    frequency: int
    avg_success_rate: float
    avg_duration_ms: float
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type.value,
            "capabilities": self.capabilities,
            "frequency": self.frequency,
            "avg_success_rate": self.avg_success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "confidence": self.confidence,
        }


@dataclass
class AgentContribution:
    contribution_id: str
    agent_id: str
    pattern_id: str
    weight_vector: Dict[str, float]
    sample_count: int
    local_loss: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contribution_id": self.contribution_id,
            "agent_id": self.agent_id,
            "pattern_id": self.pattern_id,
            "sample_count": self.sample_count,
            "local_loss": self.local_loss,
        }


@dataclass
class GlobalModel:
    model_id: str
    version: int
    weights: Dict[str, float]
    accuracy: float
    total_contributions: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "accuracy": self.accuracy,
            "total_contributions": self.total_contributions,
            "weights_count": len(self.weights),
        }


@dataclass
class PreWarmRequest:
    request_id: str
    capability_id: str
    priority: float
    predicted_next_use: float
    confidence: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "capability_id": self.capability_id,
            "priority": self.priority,
            "predicted_next_use": self.predicted_next_use,
            "confidence": self.confidence,
        }


class FederatedLearningEngine:
    VERSION = "1.0.0"

    def __init__(
        self,
        aggregation_rounds: int = 10,
        min_contributions: int = 2,
        decay_factor: float = 0.95,
    ) -> None:
        self._lock = threading.RLock()
        self._aggregation_rounds = aggregation_rounds
        self._min_contributions = min_contributions
        self._decay_factor = decay_factor

        self._records: List[CapabilityUsageRecord] = []
        self._patterns: Dict[str, UsagePattern] = {}
        self._contributions: Dict[str, List[AgentContribution]] = defaultdict(list)
        self._global_model: Optional[GlobalModel] = None
        self._prewarm_queue: List[PreWarmRequest] = []
        self._agent_profiles: Dict[str, Dict[str, Any]] = {}
        self._max_records = 10000
        self._max_history = 500

    def record_usage(self, record: CapabilityUsageRecord) -> None:
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]

            agent_id = record.agent_id
            if agent_id not in self._agent_profiles:
                self._agent_profiles[agent_id] = {
                    "total_uses": 0,
                    "successes": 0,
                    "capabilities_used": set(),
                }
            profile = self._agent_profiles[agent_id]
            profile["total_uses"] += 1
            if record.success:
                profile["successes"] += 1
            profile["capabilities_used"].add(record.capability_id)

    def discover_patterns(
        self,
        min_frequency: int = 3,
        time_window_seconds: float = 3600.0,
    ) -> List[UsagePattern]:
        with self._lock:
            cutoff = time.time() - time_window_seconds
            recent = [r for r in self._records if r.timestamp >= cutoff]

            patterns = []

            seq_patterns = self._discover_sequential_patterns(recent, min_frequency)
            patterns.extend(seq_patterns)

            temp_patterns = self._discover_temporal_patterns(recent, min_frequency)
            patterns.extend(temp_patterns)

            pref_patterns = self._discover_preference_patterns(recent, min_frequency)
            patterns.extend(pref_patterns)

            err_patterns = self._discover_error_recovery_patterns(recent, min_frequency)
            patterns.extend(err_patterns)

            for p in patterns:
                self._patterns[p.pattern_id] = p

            return patterns

    def _discover_sequential_patterns(
        self, records: List[CapabilityUsageRecord], min_freq: int
    ) -> List[UsagePattern]:
        agent_seqs: Dict[str, List[str]] = defaultdict(list)
        for r in sorted(records, key=lambda x: (x.agent_id, x.timestamp)):
            agent_seqs[r.agent_id].append(r.capability_id)

        patterns = []
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        pair_success: Dict[Tuple[str, str], List[bool]] = defaultdict(list)
        pair_duration: Dict[Tuple[str, str], List[float]] = defaultdict(list)

        for agent_id, caps in agent_seqs.items():
            for i in range(len(caps) - 1):
                pair = (caps[i], caps[i + 1])
                pair_counts[pair] += 1
                records_for_pair = [
                    r for r in records
                    if r.agent_id == agent_id
                    and r.capability_id in pair
                ]
                for r in records_for_pair:
                    pair_success[pair].append(r.success)
                    pair_duration[pair].append(r.duration_ms)

        for pair, count in pair_counts.items():
            if count >= min_freq:
                successes = pair_success.get(pair, [])
                durations = pair_duration.get(pair, [])
                avg_success = sum(successes) / len(successes) if successes else 0.0
                avg_dur = sum(durations) / len(durations) if durations else 0.0

                patterns.append(UsagePattern(
                    pattern_id=f"seq-{hashlib.md5(str(pair).encode()).hexdigest()[:8]}",
                    pattern_type=PatternType.SEQUENTIAL,
                    capabilities=list(pair),
                    frequency=count,
                    avg_success_rate=avg_success,
                    avg_duration_ms=avg_dur,
                    confidence=min(count / 20.0, 1.0),
                ))

        return patterns

    def _discover_temporal_patterns(
        self, records: List[CapabilityUsageRecord], min_freq: int
    ) -> List[UsagePattern]:
        hour_caps: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in records:
            hour = int(r.timestamp % 86400 // 3600)
            hour_caps[hour][r.capability_id] += 1

        patterns = []
        for hour, caps in hour_caps.items():
            for cap, count in caps.items():
                if count >= min_freq:
                    patterns.append(UsagePattern(
                        pattern_id=f"temp-{hour}-{cap.replace('.', '-')}",
                        pattern_type=PatternType.TEMPORAL,
                        capabilities=[cap],
                        frequency=count,
                        avg_success_rate=1.0,
                        avg_duration_ms=0.0,
                        confidence=min(count / 15.0, 1.0),
                        metadata={"hour_of_day": hour},
                    ))

        return patterns

    def _discover_preference_patterns(
        self, records: List[CapabilityUsageRecord], min_freq: int
    ) -> List[UsagePattern]:
        agent_caps: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in records:
            agent_caps[r.agent_id][r.capability_id] += 1

        patterns = []
        for agent_id, caps in agent_caps.items():
            sorted_caps = sorted(caps.items(), key=lambda x: x[1], reverse=True)
            top_caps = [c[0] for c in sorted_caps[:5] if c[1] >= min_freq]
            if len(top_caps) >= 2:
                patterns.append(UsagePattern(
                    pattern_id=f"pref-{agent_id}",
                    pattern_type=PatternType.PREFERENCE,
                    capabilities=top_caps,
                    frequency=sum(c[1] for c in sorted_caps[:5]),
                    avg_success_rate=1.0,
                    avg_duration_ms=0.0,
                    confidence=min(sum(c[1] for c in sorted_caps[:5]) / 30.0, 1.0),
                    metadata={"agent_id": agent_id},
                ))

        return patterns

    def _discover_error_recovery_patterns(
        self, records: List[CapabilityUsageRecord], min_freq: int
    ) -> List[UsagePattern]:
        agent_records: Dict[str, List[CapabilityUsageRecord]] = defaultdict(list)
        for r in sorted(records, key=lambda x: (x.agent_id, x.timestamp)):
            agent_records[r.agent_id].append(r)

        recovery_pairs: Dict[Tuple[str, str], int] = defaultdict(int)
        for agent_id, recs in agent_records.items():
            for i in range(len(recs) - 1):
                if not recs[i].success and recs[i + 1].success:
                    pair = (recs[i].capability_id, recs[i + 1].capability_id)
                    recovery_pairs[pair] += 1

        patterns = []
        for pair, count in recovery_pairs.items():
            if count >= min_freq:
                patterns.append(UsagePattern(
                    pattern_id=f"err-{hashlib.md5(str(pair).encode()).hexdigest()[:8]}",
                    pattern_type=PatternType.ERROR_RECOVERY,
                    capabilities=list(pair),
                    frequency=count,
                    avg_success_rate=0.5,
                    avg_duration_ms=0.0,
                    confidence=min(count / 10.0, 1.0),
                ))

        return patterns

    def submit_contribution(self, contribution: AgentContribution) -> None:
        with self._lock:
            self._contributions[contribution.pattern_id].append(contribution)

            if (
                len(self._contributions[contribution.pattern_id])
                >= self._min_contributions
            ):
                self._aggregate(contribution.pattern_id)

    def _aggregate(self, pattern_id: str) -> GlobalModel:
        contribs = self._contributions.get(pattern_id, [])
        if not contribs:
            return self._global_model or GlobalModel(
                model_id="global", version=0, weights={}, accuracy=0.0, total_contributions=0
            )

        total_samples = sum(c.sample_count for c in contribs)
        merged_weights: Dict[str, float] = defaultdict(float)

        for c in contribs:
            weight = c.sample_count / total_samples if total_samples > 0 else 1.0 / len(contribs)
            for key, val in c.weight_vector.items():
                merged_weights[key] += val * weight

        version = (self._global_model.version + 1) if self._global_model else 1
        total_contribs = sum(
            self._total_contributions_for_pattern(pid)
            for pid in self._contributions
        )

        self._global_model = GlobalModel(
            model_id=f"global-v{version}",
            version=version,
            weights=dict(merged_weights),
            accuracy=self._estimate_accuracy(contribs),
            total_contributions=total_contribs,
        )

        return self._global_model

    def _total_contributions_for_pattern(self, pattern_id: str) -> int:
        return sum(c.sample_count for c in self._contributions.get(pattern_id, []))

    def _estimate_accuracy(self, contribs: List[AgentContribution]) -> float:
        if not contribs:
            return 0.0
        avg_loss = sum(c.local_loss for c in contribs) / len(contribs)
        return max(0.0, 1.0 - avg_loss)

    def predict_next_capability(
        self, recent_capabilities: List[str], top_k: int = 3
    ) -> List[Tuple[str, float]]:
        with self._lock:
            if not recent_capabilities:
                return []

            last_cap = recent_capabilities[-1]
            predictions: Dict[str, float] = defaultdict(float)

            for pattern in self._patterns.values():
                if pattern.pattern_type == PatternType.SEQUENTIAL:
                    caps = pattern.capabilities
                    for i in range(len(caps) - 1):
                        if caps[i] == last_cap:
                            next_cap = caps[i + 1]
                            predictions[next_cap] += pattern.confidence * pattern.frequency

            for pattern in self._patterns.values():
                if pattern.pattern_type == PatternType.TEMPORAL:
                    for cap in pattern.capabilities:
                        predictions[cap] += pattern.confidence * 0.5

            for cap in recent_capabilities:
                if cap in predictions:
                    predictions[cap] *= 1.2

            sorted_preds = sorted(predictions.items(), key=lambda x: x[1], reverse=True)
            total_score = sum(score for _, score in sorted_preds[:top_k])
            if total_score > 0:
                return [
                    (cap, score / total_score)
                    for cap, score in sorted_preds[:top_k]
                ]

            return [(cap, 1.0 / top_k) for cap, _ in sorted_preds[:top_k]]

    def request_prewarm(
        self, capability_id: str, predicted_next_use: float, confidence: float
    ) -> PreWarmRequest:
        with self._lock:
            request = PreWarmRequest(
                request_id=f"prewarm-{int(time.time() * 1000)}",
                capability_id=capability_id,
                priority=confidence,
                predicted_next_use=predicted_next_use,
                confidence=confidence,
            )
            self._prewarm_queue.append(request)
            self._prewarm_queue.sort(key=lambda r: r.priority, reverse=True)
            return request

    def get_prewarm_queue(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in self._prewarm_queue[:limit]]

    def get_agent_profile(self, agent_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            profile = self._agent_profiles.get(agent_id)
            if profile is None:
                return None
            return {
                "agent_id": agent_id,
                "total_uses": profile["total_uses"],
                "success_rate": (
                    profile["successes"] / profile["total_uses"]
                    if profile["total_uses"] > 0 else 0.0
                ),
                "capabilities_used": list(profile["capabilities_used"]),
            }

    def get_global_model(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._global_model.to_dict() if self._global_model else None

    def get_federated_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "total_records": len(self._records),
                "total_patterns": len(self._patterns),
                "total_contributions": sum(
                    len(cs) for cs in self._contributions.values()
                ),
                "total_agents": len(self._agent_profiles),
                "global_model_version": self._global_model.version if self._global_model else 0,
                "prewarm_queue_size": len(self._prewarm_queue),
                "pattern_types": {
                    pt.value: sum(
                        1 for p in self._patterns.values() if p.pattern_type == pt
                    )
                    for pt in PatternType
                },
            }
