from __future__ import annotations

import time
import threading
import hashlib
import json
import math
import collections
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

try:
    from scipy.stats import zscore as _scipy_zscore

    def _zscore(values: List[float]) -> List[float]:
        if len(values) < 2:
            return [0.0] * len(values)
        return [float(z) for z in _scipy_zscore(values)]

except ImportError:
    def _zscore(values: List[float]) -> List[float]:
        if len(values) < 2:
            return [0.0] * len(values)
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance) if variance > 0 else 1e-10
        return [(v - mean) / std for v in values]


class AnomalyType(str, Enum):
    SPIKE = "spike"
    DROP = "drop"
    PATTERN_BREAK = "pattern_break"
    SEQUENCE_VIOLATION = "sequence_violation"
    THRESHOLD_BREACH = "threshold_breach"


@dataclass
class AnomalyEvent:
    event_id: str
    anomaly_type: AnomalyType
    component: str
    metric_name: str
    expected_value: float
    actual_value: float
    z_score: float
    severity: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "anomaly_type": self.anomaly_type.value,
            "component": self.component,
            "metric_name": self.metric_name,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "z_score": self.z_score,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class PreWarmCandidate:
    candidate_id: str
    resource_id: str
    resource_type: str
    predicted_next_use: float
    confidence: float
    estimated_benefit_ms: float
    status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FileSemanticEntry:
    file_path: str
    semantic_hash: str
    content_type: str
    topic_keywords: List[str]
    last_modified: float
    access_frequency: int = 0
    importance_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PredictiveIntelligenceEngine:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._metric_buffers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        self._metric_timestamps: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        self._anomalies: List[AnomalyEvent] = []
        self._prewarm_queue: List[PreWarmCandidate] = []
        self._file_semantics: Dict[str, FileSemanticEntry] = {}
        self._pattern_cache: Dict[str, Any] = {}
        self._alert_callbacks: List[Callable[[AnomalyEvent], None]] = []
        self._lock = threading.RLock()

    def record_metric(self, metric_name: str, value: float, timestamp: Optional[float] = None) -> List[Dict]:
        with self._lock:
            ts = timestamp if timestamp is not None else time.time()
            self._metric_buffers[metric_name].append(value)
            self._metric_timestamps[metric_name].append(ts)
            anomalies = self.detect_anomalies(metric_name)
            for event in anomalies:
                self._fire_alert(event)
            return [a.to_dict() for a in anomalies]

    def detect_anomalies(self, metric_name: str, window_size: int = 30, threshold: float = 2.0) -> List[AnomalyEvent]:
        with self._lock:
            buf = self._metric_buffers.get(metric_name)
            if buf is None or len(buf) < window_size:
                return []

            values = list(buf)
            recent = values[-window_size:]
            earlier = values[:-window_size] if len(values) > window_size else values[: len(values) // 2]
            if len(earlier) < 2:
                earlier = recent[: len(recent) // 2]
            if len(earlier) < 2:
                return []

            anomalies: List[AnomalyEvent] = []
            z_scores = _zscore(recent)

            mean_earlier = sum(earlier) / len(earlier)
            std_earlier = math.sqrt(sum((v - mean_earlier) ** 2 for v in earlier) / len(earlier)) if len(earlier) > 1 else 1e-10

            for i, (val, z_val) in enumerate(zip(recent, z_scores)):
                if abs(z_val) > threshold:
                    if val > mean_earlier:
                        atype = AnomalyType.SPIKE
                    else:
                        atype = AnomalyType.DROP
                    severity = min(1.0, abs(z_val) / (threshold * 3))
                    event = AnomalyEvent(
                        event_id=hashlib.sha256(f"{metric_name}:{val}:{time.time()}".encode()).hexdigest()[:16],
                        anomaly_type=atype,
                        component=metric_name,
                        metric_name=metric_name,
                        expected_value=mean_earlier,
                        actual_value=val,
                        z_score=round(z_val, 4),
                        severity=round(severity, 4),
                        timestamp=time.time(),
                        metadata={"window_index": i, "window_size": window_size},
                    )
                    anomalies.append(event)
                    self._anomalies.append(event)

            if len(recent) >= 10 and self._detect_pattern_break(recent):
                event = AnomalyEvent(
                    event_id=hashlib.sha256(f"{metric_name}:pat:{time.time()}".encode()).hexdigest()[:16],
                    anomaly_type=AnomalyType.PATTERN_BREAK,
                    component=metric_name,
                    metric_name=metric_name,
                    expected_value=mean_earlier,
                    actual_value=sum(recent[-5:]) / 5,
                    z_score=0.0,
                    severity=0.6,
                    timestamp=time.time(),
                    metadata={"type": "variance_ratio"},
                )
                anomalies.append(event)
                self._anomalies.append(event)

            return anomalies

    def _detect_pattern_break(self, values: deque) -> bool:
        n = len(values)
        if n < 10:
            return False
        half = n // 2
        first_half = list(values)[:half]
        second_half = list(values)[half:]
        var_first = sum((v - sum(first_half) / len(first_half)) ** 2 for v in first_half) / len(first_half)
        var_second = sum((v - sum(second_half) / len(second_half)) ** 2 for v in second_half) / len(second_half)
        if var_first < 1e-10:
            return var_second > 0.5
        ratio = var_second / var_first
        return ratio > 3.0 or ratio < 0.1

    def register_alert(self, callback: Callable[[AnomalyEvent], None]) -> None:
        with self._lock:
            self._alert_callbacks.append(callback)

    def _fire_alert(self, event: AnomalyEvent) -> None:
        for cb in self._alert_callbacks:
            try:
                cb(event)
            except Exception:
                pass

    def predict_next_use(self, resource_id: str, history_limit: int = 100) -> Dict[str, Any]:
        with self._lock:
            metric_name = f"use:{resource_id}"
            ts_buf = self._metric_timestamps.get(metric_name)
            if ts_buf is None or len(ts_buf) < 3:
                return {"resource_id": resource_id, "predicted_next_use": None, "confidence": 0.0, "method": "insufficient_data"}
            timestamps = list(ts_buf)[-history_limit:]
            inter_arrivals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
            if not inter_arrivals:
                return {"resource_id": resource_id, "predicted_next_use": None, "confidence": 0.0, "method": "no_intervals"}
            mean_interval = sum(inter_arrivals) / len(inter_arrivals)
            std_interval = math.sqrt(sum((x - mean_interval) ** 2 for x in inter_arrivals) / len(inter_arrivals)) if len(inter_arrivals) > 1 else mean_interval * 0.5
            predicted = timestamps[-1] + mean_interval
            confidence = max(0.0, min(1.0, 1.0 - (std_interval / mean_interval) if mean_interval > 0 else 0.0))
            lower = predicted - 1.96 * std_interval
            upper = predicted + 1.96 * std_interval
            return {
                "resource_id": resource_id,
                "predicted_next_use": round(predicted, 3),
                "confidence": round(confidence, 4),
                "mean_interval": round(mean_interval, 3),
                "std_interval": round(std_interval, 3),
                "interval_lower": round(lower, 3),
                "interval_upper": round(upper, 3),
                "method": "inter_arrival",
            }

    def request_prewarm(self, resource_id: str, resource_type: str, predicted_next_use: float, confidence: float) -> PreWarmCandidate:
        with self._lock:
            estimated_benefit = max(50.0, 5000.0 * confidence)
            candidate = PreWarmCandidate(
                candidate_id=hashlib.sha256(f"{resource_id}:{predicted_next_use}".encode()).hexdigest()[:12],
                resource_id=resource_id,
                resource_type=resource_type,
                predicted_next_use=predicted_next_use,
                confidence=confidence,
                estimated_benefit_ms=round(estimated_benefit, 1),
            )
            self._prewarm_queue.append(candidate)
            return candidate

    def get_prewarm_queue(self, status_filter: str = "pending", limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            filtered = [c for c in self._prewarm_queue if c.status == status_filter][:limit]
            return [c.to_dict() for c in filtered]

    def register_file(self, file_path: str, content_bytes: bytes, topic_keywords: Optional[List[str]] = None) -> FileSemanticEntry:
        with self._lock:
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            content_type = self.classify_content(file_path, content_bytes)
            entry = FileSemanticEntry(
                file_path=file_path,
                semantic_hash=content_hash,
                content_type=content_type,
                topic_keywords=topic_keywords or [],
                last_modified=time.time(),
                access_frequency=0,
                importance_score=0.0,
            )
            self._file_semantics[file_path] = entry
            return entry

    def classify_content(self, file_path: str, content_bytes: bytes) -> str:
        ext_map = {
            ".py": "code", ".js": "code", ".ts": "code", ".jsx": "code", ".tsx": "code",
            ".java": "code", ".c": "code", ".cpp": "code", ".h": "code", ".go": "code",
            ".rs": "code", ".rb": "code", ".php": "code", ".swift": "code",
            ".html": "code", ".css": "code", ".scss": "code",
            ".json": "config", ".yaml": "config", ".yml": "config", ".toml": "config",
            ".ini": "config", ".cfg": "config", ".conf": "config", ".env": "config",
            ".xml": "config",
            ".md": "document", ".txt": "document", ".rst": "document", ".doc": "document",
            ".csv": "data", ".tsv": "data", ".sql": "data", ".db": "data",
            ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
            ".bmp": "image", ".svg": "image", ".webp": "image",
            ".mp3": "audio", ".wav": "audio", ".flac": "audio",
            ".mp4": "video", ".avi": "video", ".mkv": "video",
            ".zip": "archive", ".tar": "archive", ".gz": "archive", ".7z": "archive",
            ".pdf": "document", ".docx": "document", ".xlsx": "data",
        }
        lower = file_path.lower()
        for ext, ctype in ext_map.items():
            if lower.endswith(ext):
                return ctype

        if len(content_bytes) >= 4:
            magic = content_bytes[:4]
            if magic[:3] == b"\x89PN":
                return "image"
            if magic[:4] == b"%PDF":
                return "document"
            if magic[:2] == b"PK":
                return "archive"
            if magic[:4] == b"\x89PNG":
                return "image"
        if content_bytes[:3] == b"\xff\xd8\xff":
            return "image"
        if content_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "image"

        try:
            content_bytes[:512].decode("utf-8")
            return "text"
        except (UnicodeDecodeError, ValueError):
            return "binary"

    def search_semantic(self, query_keywords: List[str], limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            query_set = set(kw.lower() for kw in query_keywords)
            results: List[Dict[str, Any]] = []
            for path, entry in self._file_semantics.items():
                entry_kw_set = set(kw.lower() for kw in entry.topic_keywords)
                overlap = len(query_set & entry_kw_set)
                score = overlap * entry.importance_score
                results.append({
                    "file_path": path,
                    "content_type": entry.content_type,
                    "overlap_count": overlap,
                    "importance_score": entry.importance_score,
                    "score": round(score, 4),
                    "topic_keywords": entry.topic_keywords,
                })
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]

    def update_file_access(self, file_path: str) -> None:
        with self._lock:
            entry = self._file_semantics.get(file_path)
            if entry is None:
                return
            entry.access_frequency += 1
            max_freq = max(
                (e.access_frequency for e in self._file_semantics.values()),
                default=1,
            )
            recency = 1.0 / (1.0 + (time.time() - entry.last_modified) / 86400.0)
            freq_score = entry.access_frequency / max(max_freq, 1)
            entry.importance_score = round(min(1.0, 0.4 * recency + 0.6 * freq_score), 4)

    def get_anomaly_history(self, metric_name: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            events = self._anomalies
            if metric_name:
                events = [e for e in events if e.metric_name == metric_name]
            return [e.to_dict() for e in events[-limit:]]

    def get_intelligence_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "metrics_tracked": len(self._metric_buffers),
                "total_anomalies": len(self._anomalies),
                "pending_prewarms": sum(1 for c in self._prewarm_queue if c.status == "pending"),
                "files_registered": len(self._file_semantics),
                "content_types": dict(
                    defaultdict(int, {
                        ct: sum(1 for e in self._file_semantics.values() if e.content_type == ct)
                        for ct in set(e.content_type for e in self._file_semantics.values())
                    })
                ),
                "recent_anomaly_types": dict(
                    defaultdict(int, {
                        e.anomaly_type.value: sum(1 for a in self._anomalies[-100:] if a.anomaly_type == e.anomaly_type)
                        for e in self._anomalies[-100:]
                    })
                ),
                "buffer_sizes": {k: len(v) for k, v in self._metric_buffers.items()},
            }
