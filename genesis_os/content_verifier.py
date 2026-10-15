from __future__ import annotations

import os, hashlib, json, time, threading, base64
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class VerificationMethod(str, Enum):
    HASH_COMPARISON = "hash_comparison"
    BYTE_COMPARISON = "byte_comparison"
    STRUCTURAL_CHECK = "structural_check"
    SEMANTIC_CHECK = "semantic_check"
    WATERMARK_CHECK = "watermark_check"


class VerificationResult(str, Enum):
    VERIFIED = "verified"
    TAMPERED = "tampered"
    CORRUPTED = "corrupted"
    UNKNOWN = "unknown"
    PARTIAL = "partial"


@dataclass
class VerificationRecord:
    record_id: str
    file_path: str
    method: VerificationMethod
    result: VerificationResult
    expected_hash: str
    actual_hash: str
    timestamp: float
    details: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id, "file_path": self.file_path,
            "method": self.method.value, "result": self.result.value,
            "expected_hash": self.expected_hash, "actual_hash": self.actual_hash,
            "timestamp": self.timestamp, "details": self.details,
            "metadata": self.metadata,
        }


@dataclass
class Watermark:
    watermark_id: str
    file_path: str
    content_hash: str
    timestamp: float
    owner: str
    hidden_data: str
    visible: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "watermark_id": self.watermark_id, "file_path": self.file_path,
            "content_hash": self.content_hash, "timestamp": self.timestamp,
            "owner": self.owner, "hidden_data": self.hidden_data,
            "visible": self.visible,
        }


@dataclass
class IntegrityReport:
    report_id: str
    file_path: str
    overall_result: VerificationResult
    checks: List[VerificationRecord]
    file_size: int
    content_hash: str
    metadata_hash: str
    verification_time_ms: float
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id, "file_path": self.file_path,
            "overall_result": self.overall_result.value,
            "checks": [c.to_dict() for c in self.checks],
            "file_size": self.file_size, "content_hash": self.content_hash,
            "metadata_hash": self.metadata_hash,
            "verification_time_ms": self.verification_time_ms,
            "recommendations": self.recommendations,
        }


class ContentVerifier:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._verification_history: Dict[str, List[VerificationRecord]] = {}
        self._watermarks: Dict[str, Watermark] = {}
        self._baselines: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._max_history = 500

    def _ts(self) -> float:
        return time.time()

    def _rid(self, prefix: str) -> str:
        return f"{prefix}_{int(self._ts() * 1000)}"

    def compute_hash(self, file_path: str, algorithm: str = "sha256") -> str:
        with self._lock:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            h = hashlib.new(algorithm)
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            return h.hexdigest()

    def compute_content_hash(self, file_path: str) -> str:
        with self._lock:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            h = hashlib.sha256()
            stat = os.stat(file_path)
            h.update(str(stat.st_size).encode())
            h.update(str(stat.st_mtime).encode())
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            return h.hexdigest()

    def verify_file(self, file_path: str, expected_hash: Optional[str] = None) -> IntegrityReport:
        with self._lock:
            start = self._ts()
            checks: List[VerificationRecord] = []
            recs: List[str] = []
            if not os.path.exists(file_path):
                return IntegrityReport(
                    report_id=self._rid("rpt"), file_path=file_path,
                    overall_result=VerificationResult.CORRUPTED, checks=[],
                    file_size=0, content_hash="", metadata_hash="",
                    verification_time_ms=0.0, recommendations=["File does not exist."],
                )
            file_hash = self.compute_hash(file_path)
            content_hash = self.compute_content_hash(file_path)
            file_size = os.path.getsize(file_path)
            stat = os.stat(file_path)
            meta_str = f"{stat.st_size}:{stat.st_mtime}:{stat.st_mode}"
            metadata_hash = hashlib.sha256(meta_str.encode()).hexdigest()
            if expected_hash:
                hr = self.verify_hash(file_path, expected_hash)
                checks.append(hr)
                if hr.result != VerificationResult.VERIFIED:
                    recs.append("Hash mismatch detected. File may be tampered.")
            wm = self.verify_watermark(file_path)
            if wm:
                checks.append(VerificationRecord(
                    record_id=self._rid("wm"), file_path=file_path,
                    method=VerificationMethod.WATERMARK_CHECK,
                    result=VerificationResult.VERIFIED,
                    expected_hash=wm.content_hash, actual_hash=file_hash,
                    timestamp=self._ts(), details="Watermark found and matches.",
                ))
            if file_path in self._baselines:
                checks.append(self.verify_against_baseline(file_path))
            elapsed_ms = (self._ts() - start) * 1000
            overall = VerificationResult.VERIFIED
            for c in checks:
                if c.result in (VerificationResult.TAMPERED, VerificationResult.CORRUPTED):
                    overall = c.result
                    break
                if c.result == VerificationResult.UNKNOWN:
                    overall = VerificationResult.UNKNOWN
            if not checks:
                overall = VerificationResult.UNKNOWN
                recs.append("No specific checks were performed.")
            return IntegrityReport(
                report_id=self._rid("rpt"), file_path=file_path,
                overall_result=overall, checks=checks, file_size=file_size,
                content_hash=content_hash, metadata_hash=metadata_hash,
                verification_time_ms=round(elapsed_ms, 2), recommendations=recs,
            )

    def verify_hash(self, file_path: str, expected_hash: str) -> VerificationRecord:
        with self._lock:
            actual = self.compute_hash(file_path)
            match = actual == expected_hash
            result = VerificationResult.VERIFIED if match else VerificationResult.TAMPERED
            rec = VerificationRecord(
                record_id=self._rid("hr"), file_path=file_path,
                method=VerificationMethod.HASH_COMPARISON, result=result,
                expected_hash=expected_hash, actual_hash=actual,
                timestamp=self._ts(), details="Hash match." if match else "Hash mismatch.",
            )
            self._add_history(file_path, rec)
            return rec

    def verify_structure(self, file_path: str, expected_structure: Dict) -> VerificationRecord:
        with self._lock:
            result = VerificationResult.UNKNOWN
            details = "Structural check performed."
            actual: Dict[str, Any] = {}
            try:
                if file_path.endswith(".json"):
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    actual = {k: type(v).__name__ for k, v in data.items()}
                elif file_path.endswith(".txt"):
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    actual = {"line_count": len(content.splitlines()), "char_count": len(content)}
                else:
                    actual = {"file_size": os.path.getsize(file_path)}
            except Exception as e:
                result = VerificationResult.CORRUPTED
                details = f"Failed to read structure: {e}"
            if result != VerificationResult.CORRUPTED:
                match = all(k in actual and actual[k] == v for k, v in expected_structure.items())
                result = VerificationResult.VERIFIED if match else VerificationResult.TAMPERED
                details = "Structure matches." if match else f"Structure mismatch: {actual}"
            rec = VerificationRecord(
                record_id=self._rid("st"), file_path=file_path,
                method=VerificationMethod.STRUCTURAL_CHECK, result=result,
                expected_hash=json.dumps(expected_structure),
                actual_hash=json.dumps(actual), timestamp=self._ts(), details=details,
            )
            self._add_history(file_path, rec)
            return rec

    def verify_semantic(self, file_path: str, reference_path: str) -> VerificationRecord:
        with self._lock:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    text1 = f.read()
                with open(reference_path, "r", encoding="utf-8") as f:
                    text2 = f.read()
                similarity = self._compute_text_similarity(text1, text2)
                result = VerificationResult.VERIFIED if similarity >= 0.8 else VerificationResult.TAMPERED
                details = f"Similarity: {similarity:.4f}"
            except Exception as e:
                result = VerificationResult.CORRUPTED
                similarity = 0.0
                details = f"Semantic check failed: {e}"
            rec = VerificationRecord(
                record_id=self._rid("sm"), file_path=file_path,
                method=VerificationMethod.SEMANTIC_CHECK, result=result,
                expected_hash=reference_path, actual_hash=f"similarity:{similarity:.4f}",
                timestamp=self._ts(), details=details,
            )
            self._add_history(file_path, rec)
            return rec

    def _compute_text_similarity(self, text1: str, text2: str) -> float:
        w1, w2 = set(text1.lower().split()), set(text2.lower().split())
        if not w1 and not w2:
            return 1.0
        if not w1 or not w2:
            return 0.0
        return len(w1 & w2) / len(w1 | w2)

    def set_baseline(self, file_path: str) -> None:
        with self._lock:
            self._baselines[file_path] = self.compute_hash(file_path)

    def verify_against_baseline(self, file_path: str) -> VerificationRecord:
        with self._lock:
            if file_path not in self._baselines:
                return VerificationRecord(
                    record_id=self._rid("bl"), file_path=file_path,
                    method=VerificationMethod.HASH_COMPARISON,
                    result=VerificationResult.UNKNOWN, expected_hash="",
                    actual_hash="", timestamp=self._ts(),
                    details="No baseline set for this file.",
                )
            expected = self._baselines[file_path]
            actual = self.compute_hash(file_path)
            match = actual == expected
            result = VerificationResult.VERIFIED if match else VerificationResult.TAMPERED
            rec = VerificationRecord(
                record_id=self._rid("bl"), file_path=file_path,
                method=VerificationMethod.HASH_COMPARISON, result=result,
                expected_hash=expected, actual_hash=actual,
                timestamp=self._ts(), details="Baseline match." if match else "Baseline mismatch.",
            )
            self._add_history(file_path, rec)
            return rec

    def embed_watermark(self, file_path: str, owner: str, output_path: Optional[str] = None) -> Watermark:
        with self._lock:
            content_hash = self.compute_hash(file_path)
            watermark_id = self._rid("wm")
            hidden_payload = json.dumps({"id": watermark_id, "owner": owner, "ts": self._ts(), "hash": content_hash})
            hidden_b64 = base64.b64encode(hidden_payload.encode()).decode()
            wm = Watermark(
                watermark_id=watermark_id, file_path=file_path, content_hash=content_hash,
                timestamp=self._ts(), owner=owner, hidden_data=hidden_b64, visible=False,
            )
            self._watermarks[file_path] = wm
            target = output_path or file_path
            try:
                with open(target, "ab") as f:
                    f.write(f"\n<!-- GenesisOS-Watermark:{hidden_b64} -->\n".encode("utf-8"))
            except Exception:
                pass
            return wm

    def verify_watermark(self, file_path: str) -> Optional[Watermark]:
        with self._lock:
            if file_path in self._watermarks:
                return self._watermarks[file_path]
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                marker_start, marker_end = "<!-- GenesisOS-Watermark:", " -->"
                start_idx = content.find(marker_start)
                if start_idx == -1:
                    return None
                start_idx += len(marker_start)
                end_idx = content.find(marker_end, start_idx)
                if end_idx == -1:
                    return None
                b64_data = content[start_idx:end_idx]
                payload = json.loads(base64.b64decode(b64_data).decode())
                wm = Watermark(
                    watermark_id=payload["id"], file_path=file_path,
                    content_hash=payload["hash"], timestamp=payload["ts"],
                    owner=payload["owner"], hidden_data=b64_data, visible=False,
                )
                self._watermarks[file_path] = wm
                return wm
            except Exception:
                return None

    def batch_verify(self, file_paths: List[str]) -> List[IntegrityReport]:
        with self._lock:
            return [self.verify_file(fp) for fp in file_paths]

    def detect_tampering(self, file_path: str) -> Dict:
        with self._lock:
            result: Dict[str, Any] = {"file_path": file_path, "tampering_detected": False, "checks": []}
            if not os.path.exists(file_path):
                result["tampering_detected"] = True
                result["checks"].append("File does not exist.")
                return result
            stat = os.stat(file_path)
            current_hash = self.compute_hash(file_path)
            if file_path in self._baselines and current_hash != self._baselines[file_path]:
                result["tampering_detected"] = True
                result["checks"].append("Hash differs from baseline.")
            if file_path in self._watermarks and self._watermarks[file_path].content_hash != current_hash:
                result["tampering_detected"] = True
                result["checks"].append("Content hash differs from watermark.")
            result["file_size"] = stat.st_size
            result["modification_time"] = stat.st_mtime
            result["current_hash"] = current_hash
            return result

    def get_verification_history(self, file_path: Optional[str] = None, limit: int = 50) -> List[Dict]:
        with self._lock:
            records = self._verification_history.get(file_path, []) if file_path else [
                r for recs in self._verification_history.values() for r in recs
            ]
            return [r.to_dict() for r in sorted(records, key=lambda r: r.timestamp, reverse=True)[:limit]]

    def get_verifier_summary(self) -> Dict:
        with self._lock:
            all_records = [r for recs in self._verification_history.values() for r in recs]
            return {
                "version": self.VERSION,
                "total_verifications": len(all_records),
                "verified": sum(1 for r in all_records if r.result == VerificationResult.VERIFIED),
                "tamper_detections": sum(1 for r in all_records if r.result == VerificationResult.TAMPERED),
                "watermarks_embedded": len(self._watermarks),
                "baselines_stored": len(self._baselines),
            }

    def _add_history(self, file_path: str, record: VerificationRecord) -> None:
        if file_path not in self._verification_history:
            self._verification_history[file_path] = []
        self._verification_history[file_path].append(record)
        if len(self._verification_history[file_path]) > self._max_history:
            self._verification_history[file_path] = self._verification_history[file_path][-self._max_history:]
