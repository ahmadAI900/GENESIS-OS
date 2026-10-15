from __future__ import annotations

import os
import hashlib
import json
import time
import threading
import uuid
import dataclasses
import enum
from typing import Any, Dict, List, Optional


class TransformationType(str, enum.Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    COPY = "copy"
    MOVE = "move"
    CONVERT = "convert"
    FILTER = "filter"
    SORT = "sort"
    MERGE = "merge"
    SPLIT = "split"
    CALCULATE = "calculate"
    IMPORT = "import"
    EXPORT = "export"


@dataclasses.dataclass
class LineageEntry:
    entry_id: str
    file_path: str
    transformation: TransformationType
    description: str
    input_hash: Optional[str]
    output_hash: Optional[str]
    timestamp: float
    actor: str
    parent_entry_id: Optional[str]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "file_path": self.file_path,
            "transformation": self.transformation.value,
            "description": self.description,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "parent_entry_id": self.parent_entry_id,
            "metadata": self.metadata,
        }


@dataclasses.dataclass
class ProvenanceChain:
    chain_id: str
    target_file: str
    entries: List[LineageEntry]
    origin_file: Optional[str]
    total_transformations: int
    chain_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "target_file": self.target_file,
            "entries": [e.to_dict() for e in self.entries],
            "origin_file": self.origin_file,
            "total_transformations": self.total_transformations,
            "chain_hash": self.chain_hash,
        }


@dataclasses.dataclass
class ImpactAnalysis:
    analysis_id: str
    source_file: str
    affected_files: List[str]
    affected_count: int
    risk_level: str
    impact_description: str
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "source_file": self.source_file,
            "affected_files": self.affected_files,
            "affected_count": self.affected_count,
            "risk_level": self.risk_level,
            "impact_description": self.impact_description,
            "timestamp": self.timestamp,
        }


@dataclasses.dataclass
class AuditEntry:
    audit_id: str
    timestamp: float
    action: str
    file_path: str
    actor: str
    details: Dict[str, Any]
    compliance_tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "file_path": self.file_path,
            "actor": self.actor,
            "details": self.details,
            "compliance_tags": self.compliance_tags,
        }


class LineageTracker:
    VERSION = "1.0.0"

    def __init__(self, max_entries: int = 10000) -> None:
        self._entries: Dict[str, List[LineageEntry]] = {}
        self._all_entries: List[LineageEntry] = []
        self._audit_log: List[AuditEntry] = []
        self._lock = threading.RLock()
        self._max_entries = max_entries

    def record(self, entry: LineageEntry) -> None:
        with self._lock:
            if len(self._all_entries) >= self._max_entries:
                self._all_entries = self._all_entries[len(self._all_entries) // 2 :]
                self._entries = {}
                for e in self._all_entries:
                    self._entries.setdefault(e.file_path, []).append(e)
            self._entries.setdefault(entry.file_path, []).append(entry)
            self._all_entries.append(entry)

    def record_transformation(
        self,
        file_path: str,
        transformation: TransformationType,
        description: str,
        input_hash: Optional[str] = None,
        output_hash: Optional[str] = None,
        actor: str = "system",
        parent_id: Optional[str] = None,
    ) -> LineageEntry:
        entry = LineageEntry(
            entry_id=str(uuid.uuid4()),
            file_path=file_path,
            transformation=transformation,
            description=description,
            input_hash=input_hash,
            output_hash=output_hash,
            timestamp=time.time(),
            actor=actor,
            parent_entry_id=parent_id,
            metadata={},
        )
        self.record(entry)
        return entry

    def get_lineage(self, file_path: str) -> ProvenanceChain:
        with self._lock:
            chain_entries = self._build_chain(file_path)
            chain_entries.reverse()
            chain_id = hashlib.sha256(
                f"{file_path}:{len(chain_entries)}".encode()
            ).hexdigest()[:16]
            origin = self.get_origin(file_path)
            chain_hash = hashlib.sha256(
                "".join(e.entry_id for e in chain_entries).encode()
            ).hexdigest()
            return ProvenanceChain(
                chain_id=chain_id,
                target_file=file_path,
                entries=chain_entries,
                origin_file=origin,
                total_transformations=len(chain_entries),
                chain_hash=chain_hash,
            )

    def _build_chain(self, file_path: str) -> List[LineageEntry]:
        entries = list(self._entries.get(file_path, []))
        visited = set()
        queue = [e.parent_entry_id for e in entries if e.parent_entry_id]
        while queue:
            pid = queue.pop(0)
            if pid in visited:
                continue
            visited.add(pid)
            for e in self._all_entries:
                if e.entry_id == pid:
                    entries.append(e)
                    if e.parent_entry_id:
                        queue.append(e.parent_entry_id)
                    break
        return entries

    def get_origin(self, file_path: str) -> Optional[str]:
        with self._lock:
            chain = self._build_chain(file_path)
            if not chain:
                return None
            origin_entry = min(chain, key=lambda e: e.timestamp)
            return origin_entry.file_path

    def analyze_impact(self, file_path: str) -> ImpactAnalysis:
        with self._lock:
            affected = self._find_descendants(file_path)
            count = len(affected)
            if count == 0:
                risk = "low"
                desc = f"No downstream dependencies from {file_path}"
            elif count <= 5:
                risk = "medium"
                desc = f"{count} files depend on {file_path}"
            else:
                risk = "high"
                desc = f"Critical: {count} files depend on {file_path}"
            return ImpactAnalysis(
                analysis_id=str(uuid.uuid4()),
                source_file=file_path,
                affected_files=affected,
                affected_count=count,
                risk_level=risk,
                impact_description=desc,
                timestamp=time.time(),
            )

    def _find_descendants(self, file_path: str) -> List[str]:
        descendants = []
        for entry in self._all_entries:
            if entry.parent_entry_id:
                parent = next(
                    (e for e in self._all_entries if e.entry_id == entry.parent_entry_id),
                    None,
                )
                if parent and parent.file_path == file_path and entry.file_path not in descendants:
                    descendants.append(entry.file_path)
                    descendants.extend(
                        d for d in self._find_descendants(entry.file_path) if d not in descendants
                    )
        return descendants

    def compute_file_hash(self, file_path: str) -> str:
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    def verify_integrity(self, file_path: str, expected_hash: str) -> bool:
        return self.compute_file_hash(file_path) == expected_hash

    def record_audit(
        self,
        action: str,
        file_path: str,
        actor: str,
        details: Dict[str, Any],
        compliance_tags: Optional[List[str]] = None,
    ) -> None:
        entry = AuditEntry(
            audit_id=str(uuid.uuid4()),
            timestamp=time.time(),
            action=action,
            file_path=file_path,
            actor=actor,
            details=details,
            compliance_tags=compliance_tags or [],
        )
        with self._lock:
            self._audit_log.append(entry)

    def get_audit_log(
        self,
        file_path: Optional[str] = None,
        compliance_tag: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        with self._lock:
            results = self._audit_log
            if file_path:
                results = [e for e in results if e.file_path == file_path]
            if compliance_tag:
                results = [e for e in results if compliance_tag in e.compliance_tags]
            return [e.to_dict() for e in results[-limit:]]

    def get_lineage_summary(self) -> Dict:
        with self._lock:
            transformation_counts: Dict[str, int] = {}
            for entry in self._all_entries:
                key = entry.transformation.value
                transformation_counts[key] = transformation_counts.get(key, 0) + 1
            return {
                "version": self.VERSION,
                "total_entries": len(self._all_entries),
                "files_tracked": len(self._entries),
                "transformations_by_type": transformation_counts,
                "audit_entries": len(self._audit_log),
            }

    def export_lineage(self, file_path: str) -> Dict:
        chain = self.get_lineage(file_path)
        impact = self.analyze_impact(file_path)
        return {
            "provenance_chain": chain.to_dict(),
            "impact_analysis": impact.to_dict(),
            "exported_at": time.time(),
            "tracker_version": self.VERSION,
        }
