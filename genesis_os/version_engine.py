from __future__ import annotations

import os
import hashlib
import json
import time
import threading
import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


class VersionDiffType:
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    FORMATTING_CHANGE = "formatting_change"


@dataclass
class VersionDiff:
    diff_id: str
    diff_type: str
    section: str
    old_content: Optional[str]
    new_content: Optional[str]
    line_number: Optional[int]
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diff_id": self.diff_id,
            "diff_type": self.diff_type,
            "section": self.section,
            "old_content": self.old_content,
            "new_content": self.new_content,
            "line_number": self.line_number,
            "confidence": self.confidence,
        }


@dataclass
class DocumentVersion:
    version_id: str
    doc_id: str
    version_number: int
    file_path: str
    content_hash: str
    timestamp: float
    author: str
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_version_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "doc_id": self.doc_id,
            "version_number": self.version_number,
            "file_path": self.file_path,
            "content_hash": self.content_hash,
            "timestamp": self.timestamp,
            "author": self.author,
            "description": self.description,
            "metadata": self.metadata,
            "parent_version_id": self.parent_version_id,
        }


@dataclass
class SemanticDiff:
    diff_id: str
    source_version_id: str
    target_version_id: str
    diffs: List[VersionDiff]
    summary: str
    additions: int
    deletions: int
    modifications: int
    similarity_score: float
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diff_id": self.diff_id,
            "source_version_id": self.source_version_id,
            "target_version_id": self.target_version_id,
            "diffs": [d.to_dict() for d in self.diffs],
            "summary": self.summary,
            "additions": self.additions,
            "deletions": self.deletions,
            "modifications": self.modifications,
            "similarity_score": self.similarity_score,
            "timestamp": self.timestamp,
        }


@dataclass
class VersionTimeline:
    doc_id: str
    versions: List[DocumentVersion]
    total_versions: int
    first_version: Optional[str]
    latest_version: Optional[str]
    contributors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "versions": [v.to_dict() for v in self.versions],
            "total_versions": self.total_versions,
            "first_version": self.first_version,
            "latest_version": self.latest_version,
            "contributors": self.contributors,
        }


class VersionEngine:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._versions: Dict[str, List[DocumentVersion]] = {}
        self._snapshots: Dict[str, bytes] = {}
        self._lock = threading.RLock()
        self._max_versions_per_doc = 100

    def create_version(
        self, doc_id: str, file_path: str, author: str = "system", description: str = ""
    ) -> DocumentVersion:
        with self._lock:
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            with open(file_path, "rb") as f:
                content_bytes = f.read()

            content_hash = hashlib.sha256(content_bytes).hexdigest()
            existing = self._versions.get(doc_id, [])
            parent_id = existing[-1].version_id if existing else None
            version_number = len(existing) + 1

            version_id = f"{doc_id}_v{version_number}_{content_hash[:8]}"
            version = DocumentVersion(
                version_id=version_id,
                doc_id=doc_id,
                version_number=version_number,
                file_path=file_path,
                content_hash=content_hash,
                timestamp=time.time(),
                author=author,
                description=description,
                metadata={"file_size": len(content_bytes)},
                parent_version_id=parent_id,
            )

            if doc_id not in self._versions:
                self._versions[doc_id] = []
            self._versions[doc_id].append(version)
            self._snapshots[version_id] = content_bytes

            if len(self._versions[doc_id]) > self._max_versions_per_doc:
                old = self._versions[doc_id].pop(0)
                self._snapshots.pop(old.version_id, None)

            return version

    def get_version(self, doc_id: str, version_number: int) -> Optional[DocumentVersion]:
        with self._lock:
            versions = self._versions.get(doc_id, [])
            if 1 <= version_number <= len(versions):
                return versions[version_number - 1]
            return None

    def get_latest_version(self, doc_id: str) -> Optional[DocumentVersion]:
        with self._lock:
            versions = self._versions.get(doc_id, [])
            return versions[-1] if versions else None

    def get_timeline(self, doc_id: str) -> VersionTimeline:
        with self._lock:
            versions = self._versions.get(doc_id, [])
            contributors = list({v.author for v in versions})
            return VersionTimeline(
                doc_id=doc_id,
                versions=list(versions),
                total_versions=len(versions),
                first_version=versions[0].version_id if versions else None,
                latest_version=versions[-1].version_id if versions else None,
                contributors=contributors,
            )

    def compute_diff(self, doc_id: str, version_a: int, version_b: int) -> SemanticDiff:
        with self._lock:
            va = self.get_version(doc_id, version_a)
            vb = self.get_version(doc_id, version_b)
            if not va or not vb:
                raise ValueError("Invalid version numbers")

            text1 = self._snapshots.get(va.version_id, b"").decode("utf-8", errors="replace")
            text2 = self._snapshots.get(vb.version_id, b"").decode("utf-8", errors="replace")
            diffs = self._compute_text_diff(text1, text2)

            additions = sum(1 for d in diffs if d.diff_type == VersionDiffType.ADDED)
            deletions = sum(1 for d in diffs if d.diff_type == VersionDiffType.REMOVED)
            modifications = sum(1 for d in diffs if d.diff_type == VersionDiffType.MODIFIED)

            sm = difflib.SequenceMatcher(None, text1, text2)
            similarity = sm.ratio()

            summary = f"{additions} additions, {deletions} deletions, {modifications} modifications"
            return SemanticDiff(
                diff_id=f"diff_{va.version_id}_{vb.version_id}",
                source_version_id=va.version_id,
                target_version_id=vb.version_id,
                diffs=diffs,
                summary=summary,
                additions=additions,
                deletions=deletions,
                modifications=modifications,
                similarity_score=similarity,
                timestamp=time.time(),
            )

    def _compute_text_diff(self, text1: str, text2: str) -> List[VersionDiff]:
        diffs: List[VersionDiff] = []
        lines1 = text1.splitlines(keepends=True)
        lines2 = text2.splitlines(keepends=True)

        opcodes = difflib.SequenceMatcher(None, lines1, lines2).get_opcodes()
        for i, (tag, i1, i2, j1, j2) in enumerate(opcodes):
            old_text = "".join(lines1[i1:i2]) if i1 != i2 else None
            new_text = "".join(lines2[j1:j2]) if j1 != j2 else None

            if tag == "equal":
                continue
            elif tag == "insert":
                diff_type = VersionDiffType.ADDED
                old_text = None
            elif tag == "delete":
                diff_type = VersionDiffType.REMOVED
                new_text = None
            else:
                diff_type = self._classify_diff(tag)

            diffs.append(VersionDiff(
                diff_id=f"diff_{i}_{tag}",
                diff_type=diff_type,
                section=f"lines_{i1 + 1}_{i2}",
                old_content=old_text,
                new_content=new_text,
                line_number=i1 + 1,
                confidence=0.95 if tag != "replace" else 0.85,
            ))
        return diffs

    def _classify_diff(self, change_type: str) -> str:
        if change_type == "replace":
            return VersionDiffType.MODIFIED
        return VersionDiffType.UNCHANGED

    def get_diff_summary(self, doc_id: str, version_a: int, version_b: int) -> Dict:
        with self._lock:
            sd = self.compute_diff(doc_id, version_a, version_b)
            return {
                "doc_id": doc_id,
                "source_version": version_a,
                "target_version": version_b,
                "additions": sd.additions,
                "deletions": sd.deletions,
                "modifications": sd.modifications,
                "similarity_score": sd.similarity_score,
                "summary": sd.summary,
            }

    def get_version_count(self, doc_id: str) -> int:
        with self._lock:
            return len(self._versions.get(doc_id, []))

    def list_documents(self) -> List[str]:
        with self._lock:
            return list(self._versions.keys())

    def revert_to_version(self, doc_id: str, version_number: int, output_path: str) -> bool:
        with self._lock:
            version = self.get_version(doc_id, version_number)
            if not version:
                return False
            content = self._snapshots.get(version.version_id)
            if content is None:
                return False
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(content)
            return True

    def compare_versions_across_docs(self, doc_ids: List[str]) -> Dict:
        with self._lock:
            result: Dict[str, Any] = {}
            for doc_id in doc_ids:
                latest = self.get_latest_version(doc_id)
                result[doc_id] = latest.to_dict() if latest else None
            return result

    def get_version_content(self, doc_id: str, version_number: int) -> Optional[str]:
        with self._lock:
            version = self.get_version(doc_id, version_number)
            if not version:
                return None
            content = self._snapshots.get(version.version_id)
            if content is None:
                return None
            return content.decode("utf-8", errors="replace")

    def get_engine_summary(self) -> Dict:
        with self._lock:
            total_docs = len(self._versions)
            total_versions = sum(len(v) for v in self._versions.values())
            total_snapshots = len(self._snapshots)
            all_authors: set = set()
            for versions in self._versions.values():
                for v in versions:
                    all_authors.add(v.author)
            return {
                "engine_version": self.VERSION,
                "total_documents": total_docs,
                "total_versions": total_versions,
                "total_snapshots": total_snapshots,
                "unique_authors": len(all_authors),
                "max_versions_per_doc": self._max_versions_per_doc,
            }
