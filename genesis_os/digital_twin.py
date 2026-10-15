from __future__ import annotations

import time
import threading
import json
import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse


class ObservationType(str, Enum):
    NAVIGATION = "navigation"
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    TAB_SWITCH = "tab_switch"
    TAB_OPEN = "tab_open"
    TAB_CLOSE = "tab_close"
    FORM_SUBMIT = "form_submit"
    NETWORK_REQUEST = "network_request"
    DOM_MUTATION = "dom_mutation"
    CONSOLE_LOG = "console_log"


@dataclass
class BrowserObservation:
    observation_id: str
    observation_type: ObservationType
    timestamp: float
    page_url: str
    page_title: str
    element_selector: Optional[str] = None
    element_text: Optional[str] = None
    tab_id: Optional[str] = None
    network_url: Optional[str] = None
    network_status: Optional[int] = None
    dom_snapshot: Optional[Dict[str, Any]] = None
    console_level: Optional[str] = None
    console_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "observation_type": self.observation_type.value,
            "timestamp": self.timestamp,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "element_selector": self.element_selector,
            "element_text": self.element_text,
            "tab_id": self.tab_id,
            "network_url": self.network_url,
            "network_status": self.network_status,
            "dom_snapshot": self.dom_snapshot,
            "console_level": self.console_level,
            "console_message": self.console_message,
            "metadata": self.metadata,
        }


@dataclass
class SessionReplay:
    session_id: str
    observations: List[BrowserObservation]
    start_time: float
    end_time: float
    final_url: str
    final_title: str
    total_tabs: int
    total_interactions: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "observations": [o.to_dict() for o in self.observations],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "final_url": self.final_url,
            "final_title": self.final_title,
            "total_tabs": self.total_tabs,
            "total_interactions": self.total_interactions,
        }


@dataclass
class CrossTabCorrelation:
    correlation_id: str
    tab_pairs: List[Tuple[str, str]]
    shared_data: List[str]
    correlation_type: str
    confidence: float
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "tab_pairs": self.tab_pairs,
            "shared_data": self.shared_data,
            "correlation_type": self.correlation_type,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


@dataclass
class NetworkEntry:
    request_id: str
    url: str
    method: str
    status: Optional[int]
    duration_ms: float
    size_bytes: int
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "url": self.url,
            "method": self.method,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "size_bytes": self.size_bytes,
            "timestamp": self.timestamp,
        }


class BrowserDigitalTwin:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._observations: Dict[str, deque] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._active_sessions: set = set()
        self._network_logs: Dict[str, List[NetworkEntry]] = defaultdict(list)
        self._tab_states: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self._cross_tab_correlations: List[CrossTabCorrelation] = []
        self._lock = threading.RLock()

    def start_session(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            if session_id in self._active_sessions:
                return {"status": "already_active", "session_id": session_id}
            self._observations[session_id] = deque(maxlen=5000)
            self._sessions[session_id] = {
                "session_id": session_id,
                "start_time": time.time(),
                "status": "active",
            }
            self._active_sessions.add(session_id)
            self._network_logs[session_id] = []
            self._tab_states[session_id] = {}
            return {"status": "started", "session_id": session_id}

    def end_session(self, session_id: str) -> Optional[SessionReplay]:
        with self._lock:
            if session_id not in self._active_sessions:
                return None
            self._active_sessions.discard(session_id)
            observations = list(self._observations.get(session_id, []))
            obs_list = observations if observations else []
            start_time = self._sessions[session_id]["start_time"] if session_id in self._sessions else time.time()
            end_time = time.time()
            final_url = obs_list[-1].page_url if obs_list else ""
            final_title = obs_list[-1].page_title if obs_list else ""
            tab_ids = set()
            for obs in obs_list:
                if obs.tab_id:
                    tab_ids.add(obs.tab_id)
            total_tabs = max(len(tab_ids), 1) if tab_ids else 1
            total_interactions = len(obs_list)
            if session_id in self._sessions:
                self._sessions[session_id]["status"] = "ended"
                self._sessions[session_id]["end_time"] = end_time
            replay = SessionReplay(
                session_id=session_id,
                observations=obs_list,
                start_time=start_time,
                end_time=end_time,
                final_url=final_url,
                final_title=final_title,
                total_tabs=total_tabs,
                total_interactions=total_interactions,
            )
            return replay

    def record_observation(self, session_id: str, observation: BrowserObservation) -> None:
        with self._lock:
            if session_id not in self._active_sessions:
                return
            if session_id in self._observations:
                self._observations[session_id].append(observation)
            if observation.tab_id:
                tab_state = self._tab_states[session_id].get(observation.tab_id, {"url": observation.page_url, "title": observation.page_title, "element_count": 0, "form_data": {}})
                if observation.observation_type == ObservationType.NAVIGATION:
                    tab_state["url"] = observation.page_url
                    tab_state["title"] = observation.page_title
                elif observation.observation_type == ObservationType.CLICK:
                    tab_state["element_count"] = tab_state.get("element_count", 0) + 1
                self._tab_states[session_id][observation.tab_id] = tab_state

    def record_network(self, session_id: str, entry: NetworkEntry) -> None:
        with self._lock:
            if session_id not in self._active_sessions:
                return
            self._network_logs[session_id].append(entry)

    def get_tab_state(self, session_id: str, tab_id: str) -> Dict[str, Any]:
        with self._lock:
            tabs = self._tab_states.get(session_id, {})
            return tabs.get(tab_id, {"url": "", "title": "", "element_count": 0, "form_data": {}})

    def update_tab_state(self, session_id: str, tab_id: str, **kwargs: Any) -> None:
        with self._lock:
            if session_id not in self._active_sessions:
                return
            current = self._tab_states[session_id].get(tab_id, {"url": "", "title": "", "element_count": 0, "form_data": {}})
            current.update(kwargs)
            self._tab_states[session_id][tab_id] = current

    def correlate_tabs(self, session_id: str) -> List[CrossTabCorrelation]:
        with self._lock:
            tabs = self._tab_states.get(session_id, {})
            correlations: List[CrossTabCorrelation] = []
            tab_ids = list(tabs.keys())
            for i in range(len(tab_ids)):
                for j in range(i + 1, len(tab_ids)):
                    t1, t2 = tab_ids[i], tab_ids[j]
                    shared = self._find_shared_data(tabs[t1], tabs[t2])
                    if shared:
                        origin1 = tabs[t1].get("url", "")
                        origin2 = tabs[t2].get("url", "")
                        from urllib.parse import urlparse
                        o1 = urlparse(origin1).netloc
                        o2 = urlparse(origin2).netloc
                        corr_type = "same-origin" if o1 == o2 else "cross-origin"
                        if any("clipboard" in s.lower() for s in shared):
                            corr_type = "clipboard-share"
                        confidence = min(1.0, len(shared) * 0.3)
                        corr = CrossTabCorrelation(
                            correlation_id=hashlib.md5(f"{session_id}:{t1}:{t2}".encode()).hexdigest()[:16],
                            tab_pairs=[(t1, t2)],
                            shared_data=shared,
                            correlation_type=corr_type,
                            confidence=confidence,
                            timestamp=time.time(),
                        )
                        correlations.append(corr)
                        self._cross_tab_correlations.append(corr)
            return correlations

    def _find_shared_data(self, tab1_state: Dict[str, Any], tab2_state: Dict[str, Any]) -> List[str]:
        shared: List[str] = []
        url1 = tab1_state.get("url", "")
        url2 = tab2_state.get("url", "")
        if url1 and url2:
            parsed1 = urlparse(url1)
            parsed2 = urlparse(url2)
            if parsed1.netloc == parsed2.netloc and parsed1.path == parsed2.path and parsed1.query != parsed2.query:
                shared.append(f"same-path-diff-query: {parsed1.path}")
        form1 = tab1_state.get("form_data", {})
        form2 = tab2_state.get("form_data", {})
        for key in form1:
            if key in form2 and form1[key] == form2[key] and form1[key]:
                shared.append(f"form-data:{key}={form1[key]}")
        meta1 = tab1_state.get("metadata", {})
        meta2 = tab2_state.get("metadata", {})
        if meta1.get("cookies") and meta2.get("cookies"):
            if meta1["cookies"] == meta2["cookies"]:
                shared.append("shared-cookies")
        if meta1.get("clipboard") and meta2.get("clipboard"):
            if meta1["clipboard"] == meta2["clipboard"]:
                shared.append("clipboard-share")
        return shared

    def get_session_timeline(self, session_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            observations = list(self._observations.get(session_id, []))
            if not observations:
                return []
            sorted_obs = sorted(observations, key=lambda o: o.timestamp)
            timeline: List[Dict[str, Any]] = []
            prev_time = sorted_obs[0].timestamp
            for obs in sorted_obs:
                delta = obs.timestamp - prev_time
                timeline.append({
                    "observation": obs.to_dict(),
                    "time_delta_ms": round(delta * 1000, 2),
                    "cumulative_time_ms": round((obs.timestamp - sorted_obs[0].timestamp) * 1000, 2),
                })
                prev_time = obs.timestamp
            return timeline

    def get_network_summary(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            entries = self._network_logs.get(session_id, [])
            if not entries:
                return {"total_requests": 0, "avg_latency_ms": 0, "status_distribution": {}, "total_size_bytes": 0}
            total = len(entries)
            avg_latency = sum(e.duration_ms for e in entries) / total
            status_dist: Dict[int, int] = defaultdict(int)
            for e in entries:
                if e.status is not None:
                    status_dist[e.status] += 1
            total_size = sum(e.size_bytes for e in entries)
            return {
                "total_requests": total,
                "avg_latency_ms": round(avg_latency, 2),
                "status_distribution": dict(status_dist),
                "total_size_bytes": total_size,
            }

    def replay_session(self, session_id: str, observer_fn: Callable[[BrowserObservation], Any]) -> Dict[str, Any]:
        with self._lock:
            observations = list(self._observations.get(session_id, []))
            results: List[Any] = []
            for obs in observations:
                try:
                    result = observer_fn(obs)
                    results.append({"observation_id": obs.observation_id, "result": result, "success": True})
                except Exception as e:
                    results.append({"observation_id": obs.observation_id, "error": str(e), "success": False})
            return {
                "session_id": session_id,
                "total_observations": len(observations),
                "results": results,
                "success_count": sum(1 for r in results if r["success"]),
                "failure_count": sum(1 for r in results if not r["success"]),
            }

    def get_digital_twin_summary(self) -> Dict[str, Any]:
        with self._lock:
            total_obs = sum(len(d) for d in self._observations.values())
            total_network = sum(len(l) for l in self._network_logs.values())
            return {
                "version": self.VERSION,
                "total_sessions": len(self._sessions),
                "active_sessions": len(self._active_sessions),
                "total_observations": total_obs,
                "total_network_entries": total_network,
                "total_correlations": len(self._cross_tab_correlations),
            }

    def export_session(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            observations = list(self._observations.get(session_id, []))
            network = self._network_logs.get(session_id, [])
            tabs = self._tab_states.get(session_id, {})
            correlations = [
                c.to_dict() for c in self._cross_tab_correlations
                if any(
                    session_id in pair[0] or session_id in pair[1]
                    for pair in [tp for tp in c.tab_pairs]
                )
            ]
            return {
                "session_id": session_id,
                "session_info": self._sessions.get(session_id, {}),
                "observations": [o.to_dict() for o in observations],
                "network_logs": [n.to_dict() for n in network],
                "tab_states": {k: v for k, v in tabs.items()},
                "correlations": correlations,
                "summary": {
                    "total_observations": len(observations),
                    "total_network_entries": len(network),
                    "total_tabs": len(tabs),
                    "total_correlations": len(correlations),
                },
            }
