from __future__ import annotations
import math
import time
import threading
import json
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class VerificationMode(str, Enum):
    VISUAL = "visual"
    VOICE = "voice"
    GESTURE = "gesture"
    EYE_TRACKING = "eye_tracking"
    SPATIAL_FIDUCIAL = "spatial_fiducial"
    MULTIMODAL_FUSION = "multimodal_fusion"


class VerificationSignal(str, Enum):
    CONFIRMED = "confirmed"
    DENIED = "denied"
    AMBIGUOUS = "ambiguous"
    TIMEOUT = "timeout"
    NOT_SUPPORTED = "not_supported"


@dataclass
class SpatialRegion:
    region_id: str
    name: str
    x: int
    y: int
    width: int
    height: int
    region_type: str
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id, "name": self.name,
            "x": self.x, "y": self.y, "width": self.width, "height": self.height,
            "region_type": self.region_type, "confidence": self.confidence,
            "metadata": self.metadata,
        }


@dataclass
class VoiceCommand:
    command_id: str
    phrase: str
    language: str = "en-US"
    confidence: float = 0.0
    alternatives: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id, "phrase": self.phrase,
            "language": self.language, "confidence": self.confidence,
            "alternatives": self.alternatives, "timestamp": self.timestamp,
            "verified": self.verified,
        }


@dataclass
class GestureEvent:
    gesture_id: str
    gesture_type: str
    direction: Optional[str] = None
    magnitude: float = 0.0
    start_point: Tuple[int, int] = (0, 0)
    end_point: Tuple[int, int] = (0, 0)
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gesture_id": self.gesture_id, "gesture_type": self.gesture_type,
            "direction": self.direction, "magnitude": self.magnitude,
            "start_point": list(self.start_point), "end_point": list(self.end_point),
            "timestamp": self.timestamp, "confidence": self.confidence,
        }


@dataclass
class EyeTrackingEvent:
    event_id: str
    gaze_point: Tuple[int, int]
    fixation_duration_ms: float = 0.0
    pupil_diameter_mm: float = 0.0
    blink_detected: bool = False
    attention_score: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id, "gaze_point": list(self.gaze_point),
            "fixation_duration_ms": self.fixation_duration_ms,
            "pupil_diameter_mm": self.pupil_diameter_mm,
            "blink_detected": self.blink_detected,
            "attention_score": self.attention_score, "timestamp": self.timestamp,
        }


def _levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            curr_row.append(min(
                prev_row[j + 1] + 1, curr_row[j] + 1,
                prev_row[j] + (c1 != c2)
            ))
        prev_row = curr_row
    return prev_row[-1]


def _string_similarity(s1: str, s2: str) -> float:
    s1_lower, s2_lower = s1.lower().strip(), s2.lower().strip()
    if s1_lower == s2_lower:
        return 1.0
    max_len = max(len(s1_lower), len(s2_lower))
    if max_len == 0:
        return 1.0
    return 1.0 - (_levenshtein_distance(s1_lower, s2_lower) / max_len)


class SpatialVerificationEngine:
    VERSION = "1.0.0"

    def __init__(self, max_history: int = 1000):
        self._regions: Dict[str, SpatialRegion] = {}
        self._voice_commands: List[VoiceCommand] = []
        self._gestures: List[GestureEvent] = []
        self._eye_events: List[EyeTrackingEvent] = []
        self._verification_results: List[Dict[str, Any]] = []
        self._custom_handlers: Dict[VerificationMode, Callable] = {}
        self._lock = threading.RLock()
        self._max_history = max_history

    def register_region(self, region: SpatialRegion) -> None:
        with self._lock:
            self._regions[region.region_id] = region

    def unregister_region(self, region_id: str) -> bool:
        with self._lock:
            if region_id in self._regions:
                del self._regions[region_id]
                return True
            return False

    def register_voice_command(self, command: VoiceCommand) -> None:
        with self._lock:
            self._voice_commands.append(command)
            if len(self._voice_commands) > self._max_history:
                self._voice_commands = self._voice_commands[-self._max_history:]

    def register_gesture(self, gesture: GestureEvent) -> None:
        with self._lock:
            self._gestures.append(gesture)
            if len(self._gestures) > self._max_history:
                self._gestures = self._gestures[-self._max_history:]

    def register_eye_event(self, event: EyeTrackingEvent) -> None:
        with self._lock:
            self._eye_events.append(event)
            if len(self._eye_events) > self._max_history:
                self._eye_events = self._eye_events[-self._max_history:]

    def verify_spatial(
        self, target_region_id: str,
        current_gaze_or_point: Tuple[int, int],
        mode: VerificationMode,
    ) -> Dict[str, Any]:
        with self._lock:
            if mode in self._custom_handlers:
                return self._custom_handlers[mode](target_region_id, current_gaze_or_point)

            region = self._regions.get(target_region_id)
            if not region:
                result = {"verified": False, "confidence": 0.0, "mode": mode.value, "error": "region_not_found"}
                self._record_result(result)
                return result

            px, py = current_gaze_or_point
            in_bounds = (region.x <= px <= region.x + region.width and
                         region.y <= py <= region.y + region.height)

            if in_bounds:
                cx, cy = region.x + region.width / 2, region.y + region.height / 2
                dist = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
                max_dist = math.sqrt((region.width / 2) ** 2 + (region.height / 2) ** 2)
                proximity = max(0.0, 1.0 - (dist / max_dist)) if max_dist > 0 else 1.0
                confidence = round(min(region.confidence, proximity), 4)
            else:
                confidence = 0.0

            result = {"verified": in_bounds, "confidence": confidence, "mode": mode.value}
            self._record_result(result)
            return result

    def verify_voice(self, expected_phrase: str, actual_command: VoiceCommand) -> Dict[str, Any]:
        with self._lock:
            similarity = _string_similarity(expected_phrase, actual_command.phrase)
            for alt in actual_command.alternatives:
                similarity = max(similarity, _string_similarity(expected_phrase, alt))

            verified = similarity >= 0.7 and actual_command.confidence >= 0.5
            actual_command.verified = verified

            result = {
                "verified": verified, "confidence": actual_command.confidence,
                "similarity": round(similarity, 4), "mode": VerificationMode.VOICE.value,
            }
            self._record_result(result)
            return result

    def verify_gesture(self, expected_gesture: str, actual: GestureEvent) -> Dict[str, Any]:
        with self._lock:
            exp = expected_gesture.lower().strip()
            type_match = actual.gesture_type.lower() == exp
            direction_match = True

            if ":" in exp:
                expected_type, expected_dir = exp.split(":", 1)
                type_match = actual.gesture_type.lower() == expected_type
                direction_match = (actual.direction is not None and
                                   actual.direction.lower() == expected_dir)

            verified = type_match and direction_match and actual.confidence >= 0.5
            result = {
                "verified": verified, "confidence": actual.confidence,
                "mode": VerificationMode.GESTURE.value,
                "type_match": type_match, "direction_match": direction_match,
            }
            self._record_result(result)
            return result

    def verify_eye_attention(
        self, region: SpatialRegion, eye_events: List[EyeTrackingEvent],
        window_ms: float = 2000.0,
    ) -> Dict[str, Any]:
        with self._lock:
            empty = {"attention_ratio": 0.0, "verified": False, "sample_count": 0,
                     "mode": VerificationMode.EYE_TRACKING.value}
            if not eye_events:
                self._record_result(empty)
                return empty

            cutoff = max(e.timestamp for e in eye_events) - (window_ms / 1000.0)
            in_window = [e for e in eye_events if e.timestamp >= cutoff]
            if not in_window:
                self._record_result(empty)
                return empty

            count = sum(
                1 for e in in_window
                if region.x <= e.gaze_point[0] <= region.x + region.width
                and region.y <= e.gaze_point[1] <= region.y + region.height
            )
            ratio = count / len(in_window)
            result = {
                "attention_ratio": round(ratio, 4), "verified": ratio >= 0.6,
                "sample_count": len(in_window), "mode": VerificationMode.EYE_TRACKING.value,
            }
            self._record_result(result)
            return result

    def fuse_signals(self, signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            if not signals:
                return {"verified": False, "confidence": 0.0, "vote_count": 0, "breakdown": []}

            verified_count = 0
            total_confidence = 0.0
            breakdown = []
            for sig in signals:
                v, c = sig.get("verified", False), sig.get("confidence", 0.0)
                if v:
                    verified_count += 1
                total_confidence += c
                breakdown.append({"mode": sig.get("mode", "unknown"), "verified": v, "confidence": c})

            vote_count = len(signals)
            result = {
                "verified": verified_count > (vote_count / 2),
                "confidence": round(total_confidence / vote_count, 4),
                "vote_count": vote_count, "breakdown": breakdown,
            }
            self._record_result(result)
            return result

    def register_custom_handler(self, mode: VerificationMode, handler: Callable) -> None:
        with self._lock:
            self._custom_handlers[mode] = handler

    def get_verification_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._verification_results[-limit:])

    def get_engine_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "regions_registered": len(self._regions),
                "voice_commands_tracked": len(self._voice_commands),
                "gestures_tracked": len(self._gestures),
                "eye_events_tracked": len(self._eye_events),
                "verifications_performed": len(self._verification_results),
                "custom_handlers_registered": list(m.value for m in self._custom_handlers),
                "max_history": self._max_history,
            }

    def _record_result(self, result: Dict[str, Any]) -> None:
        self._verification_results.append({**result, "timestamp": time.time()})
        if len(self._verification_results) > self._max_history:
            self._verification_results = self._verification_results[-self._max_history:]
