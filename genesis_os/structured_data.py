from __future__ import annotations

import os
import json
import csv
import time
import threading
import hashlib
import re
import io
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class DataFormat(str, Enum):
    CSV = "csv"
    JSON = "json"
    JSONL = "jsonl"
    XML = "xml"
    EXCEL = "excel"
    TSV = "tsv"


@dataclass
class SchemaField:
    name: str
    data_type: str
    nullable: bool
    unique: bool
    description: str = ""
    sample_values: List[Any] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "data_type": self.data_type, "nullable": self.nullable,
            "unique": self.unique, "description": self.description,
            "sample_values": self.sample_values, "constraints": self.constraints,
        }


@dataclass
class DataSchema:
    schema_id: str
    format: DataFormat
    fields: List[SchemaField]
    record_count: int
    total_size_bytes: int
    encoding: str
    delimiter: Optional[str]
    nested_depth: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_id": self.schema_id, "format": self.format.value,
            "fields": [f.to_dict() for f in self.fields],
            "record_count": self.record_count, "total_size_bytes": self.total_size_bytes,
            "encoding": self.encoding, "delimiter": self.delimiter,
            "nested_depth": self.nested_depth, "metadata": self.metadata,
        }


@dataclass
class DataJoin:
    join_id: str
    left_source: str
    right_source: str
    join_key: str
    join_type: str
    result_count: int
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "join_id": self.join_id, "left_source": self.left_source,
            "right_source": self.right_source, "join_key": self.join_key,
            "join_type": self.join_type, "result_count": self.result_count,
            "timestamp": self.timestamp,
        }


@dataclass
class DataValidationRule:
    rule_id: str
    field_name: str
    rule_type: str
    parameters: Dict[str, Any]
    error_message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id, "field_name": self.field_name,
            "rule_type": self.rule_type, "parameters": self.parameters,
            "error_message": self.error_message,
        }


@dataclass
class ValidationResult:
    validation_id: str
    rule: DataValidationRule
    passed: bool
    violations: int
    sample_violations: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_id": self.validation_id, "rule": self.rule.to_dict(),
            "passed": self.passed, "violations": self.violations,
            "sample_violations": self.sample_violations,
        }


class StructuredDataEngine:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._loaded_data: Dict[str, List[Dict]] = {}
        self._schemas: Dict[str, DataSchema] = {}
        self._join_history: List[DataJoin] = []
        self._lock = threading.RLock()

    def _detect_format(self, file_path: str) -> DataFormat:
        ext = os.path.splitext(file_path)[1].lower()
        mapping = {
            ".csv": DataFormat.CSV, ".json": DataFormat.JSON, ".jsonl": DataFormat.JSONL,
            ".xlsx": DataFormat.EXCEL, ".xls": DataFormat.EXCEL, ".tsv": DataFormat.TSV,
        }
        return mapping.get(ext, DataFormat.JSON)

    def _infer_field_type(self, values: List[Any]) -> str:
        non_null = [v for v in values if v is not None]
        if not non_null:
            return "null"
        types_found: set = set()
        for v in non_null:
            if isinstance(v, bool):
                types_found.add("boolean")
            elif isinstance(v, int):
                types_found.add("integer")
            elif isinstance(v, float):
                types_found.add("float")
            elif isinstance(v, str):
                try:
                    json.loads(v)
                    types_found.add("object")
                except (json.JSONDecodeError, TypeError):
                    types_found.add("string")
            elif isinstance(v, list):
                types_found.add("array")
            elif isinstance(v, dict):
                types_found.add("object")
            else:
                types_found.add("string")
        if "boolean" in types_found:
            return "boolean"
        if types_found - {"integer", "float"}:
            return "string" if len(types_found) > 1 and "string" in types_found else list(types_found)[0]
        return "integer" if types_found == {"integer"} else "float"

    def _collect_keys(self, records: List[Dict]) -> List[str]:
        seen, keys = set(), []
        for r in records:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        return keys

    def _infer_schema(self, source_name: str, records: List[Dict], file_size: int = 0) -> DataSchema:
        all_keys = self._collect_keys(records)
        fields: List[SchemaField] = []
        for key in all_keys:
            values = [r.get(key) for r in records]
            non_null = [v for v in values if v is not None]
            unique_vals = set(str(v) for v in non_null)
            fields.append(SchemaField(
                name=key, data_type=self._infer_field_type(values),
                nullable=any(v is None for v in values),
                unique=len(unique_vals) == len(non_null) if non_null else False,
                sample_values=[v for v in values[:5] if v is not None],
            ))
        schema_id = hashlib.md5(source_name.encode()).hexdigest()[:12]
        return DataSchema(
            schema_id=schema_id, format=DataFormat.CSV, fields=fields,
            record_count=len(records), total_size_bytes=file_size,
            encoding="utf-8", delimiter=",", metadata={"source_name": source_name},
        )

    def _read_file_text(self, file_path: str) -> str:
        for enc in ["utf-8", "utf-8-sig", "latin-1", "cp1252"]:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError(f"Cannot decode file {file_path}")

    def _load_csv(self, file_path: str) -> Tuple[List[Dict], DataSchema]:
        data = self._read_file_text(file_path)
        try:
            dialect = csv.Sniffer().sniff(data[:4096])
        except csv.Error:
            dialect = csv.excel
        records = [dict(row) for row in csv.DictReader(io.StringIO(data), dialect=dialect)]
        schema = self._infer_schema(file_path, records, os.path.getsize(file_path))
        schema.format = DataFormat.CSV
        schema.delimiter = getattr(dialect, "delimiter", ",")
        return records, schema

    def _load_json(self, file_path: str) -> Tuple[List[Dict], DataSchema]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        records = data if isinstance(data, list) else [data] if isinstance(data, dict) else [{"value": data}]
        schema = self._infer_schema(file_path, records, os.path.getsize(file_path))
        schema.format = DataFormat.JSON
        return records, schema

    def _load_jsonl(self, file_path: str) -> Tuple[List[Dict], DataSchema]:
        records: List[Dict] = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    records.append({"_raw": line, "_parse_error": True, "_line": line_no})
        schema = self._infer_schema(file_path, records, os.path.getsize(file_path))
        schema.format = DataFormat.JSONL
        return records, schema

    def _load_excel(self, file_path: str) -> Tuple[List[Dict], DataSchema]:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            rows = list(wb.active.iter_rows(values_only=True))
            wb.close()
        except ImportError:
            raise ImportError("openpyxl required: pip install openpyxl")
        if not rows:
            return [], self._infer_schema(file_path, [], os.path.getsize(file_path))
        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
        records = [{headers[i]: v for i, v in enumerate(row) if i < len(headers)} for row in rows[1:]]
        schema = self._infer_schema(file_path, records, os.path.getsize(file_path))
        schema.format = DataFormat.EXCEL
        return records, schema

    def load(self, file_path: str, name: Optional[str] = None, format: Optional[DataFormat] = None) -> DataSchema:
        with self._lock:
            source_name = name or os.path.basename(file_path)
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            detected = format or self._detect_format(file_path)
            loaders = {
                DataFormat.CSV: self._load_csv, DataFormat.JSON: self._load_json,
                DataFormat.JSONL: self._load_jsonl, DataFormat.TSV: self._load_csv,
                DataFormat.EXCEL: self._load_excel,
            }
            records, schema = loaders.get(detected, self._load_json)(file_path)
            self._loaded_data[source_name] = records
            self._schemas[source_name] = schema
            schema.metadata["source_name"] = source_name
            schema.metadata["load_time"] = time.time()
            return schema

    def _inner_join(self, left: List[Dict], right: List[Dict], key: str) -> List[Dict]:
        right_map: Dict[str, List[Dict]] = {}
        for r in right:
            right_map.setdefault(str(r.get(key, "")), []).append(r)
        result: List[Dict] = []
        for l in left:
            for r in right_map.get(str(l.get(key, "")), []):
                merged = {**l}
                for rk, rv in r.items():
                    merged[f"right_{rk}"] = rv
                result.append(merged)
        return result

    def _left_join(self, left: List[Dict], right: List[Dict], key: str) -> List[Dict]:
        right_map: Dict[str, List[Dict]] = {}
        for r in right:
            right_map.setdefault(str(r.get(key, "")), []).append(r)
        right_keys = list(right_map.keys()) if right_map else []
        nulls = {f"right_{k}": None for k in (right_map[right_keys[0]][0].keys() if right_keys else [])}
        result: List[Dict] = []
        for l in left:
            matches = right_map.get(str(l.get(key, "")), [])
            if matches:
                for r in matches:
                    merged = {**l}
                    for rk, rv in r.items():
                        merged[f"right_{rk}"] = rv
                    result.append(merged)
            else:
                result.append({**l, **nulls})
        return result

    def join(self, source_left: str, source_right: str, join_key: str, join_type: str = "inner") -> DataJoin:
        with self._lock:
            if source_left not in self._loaded_data:
                raise KeyError(f"Source not found: {source_left}")
            if source_right not in self._loaded_data:
                raise KeyError(f"Source not found: {source_right}")
            left, right = self._loaded_data[source_left], self._loaded_data[source_right]
            if join_type == "inner":
                result = self._inner_join(left, right, join_key)
            elif join_type == "left":
                result = self._left_join(left, right, join_key)
            elif join_type == "right":
                result = self._left_join(right, left, join_key)
            elif join_type == "outer":
                result = self._left_join(left, right, join_key)
                right_map: Dict[str, List[Dict]] = {}
                for r in right:
                    right_map.setdefault(str(r.get(join_key, "")), []).append(r)
                left_keys = {str(l.get(join_key, "")) for l in left}
                for rk, matches in right_map.items():
                    if rk not in left_keys:
                        for r in matches:
                            result.append({f"right_{k}": v for k, v in r.items()} | {join_key: rk})
            else:
                raise ValueError(f"Unsupported join type: {join_type}")
            jid = hashlib.md5(f"{source_left}_{source_right}_{join_key}_{time.time()}".encode()).hexdigest()[:12]
            dj = DataJoin(join_id=jid, left_source=source_left, right_source=source_right,
                          join_key=join_key, join_type=join_type, result_count=len(result), timestamp=time.time())
            self._join_history.append(dj)
            self._loaded_data[f"join_{jid}"] = result
            self._schemas[f"join_{jid}"] = self._infer_schema(f"join_{jid}", result)
            return dj

    def filter_data(self, source: str, conditions: List[Dict]) -> List[Dict]:
        with self._lock:
            if source not in self._loaded_data:
                raise KeyError(f"Source not found: {source}")
            ops = {
                "eq": lambda v, c: v == c, "ne": lambda v, c: v != c,
                "gt": lambda v, c: v is not None and v > c, "gte": lambda v, c: v is not None and v >= c,
                "lt": lambda v, c: v is not None and v < c, "lte": lambda v, c: v is not None and v <= c,
                "contains": lambda v, c: c in str(v or ""),
                "startswith": lambda v, c: str(v or "").startswith(str(c)),
                "endswith": lambda v, c: str(v or "").endswith(str(c)),
                "in": lambda v, c: v in (c or []),
                "null": lambda v, c: v is None, "notnull": lambda v, c: v is not None,
            }
            result: List[Dict] = []
            for record in self._loaded_data[source]:
                if all(ops.get(c.get("op", "eq"), lambda v, c: True)(record.get(c.get("field", "")), c.get("value")) for c in conditions):
                    result.append(record)
            return result

    def aggregate(self, source: str, group_by: List[str], aggregations: List[Dict]) -> List[Dict]:
        with self._lock:
            if source not in self._loaded_data:
                raise KeyError(f"Source not found: {source}")
            groups: Dict[str, List[Dict]] = {}
            for record in self._loaded_data[source]:
                key_str = "|".join(str(record.get(g, "")) for g in group_by)
                groups.setdefault(key_str, []).append(record)
            result: List[Dict] = []
            for key_str, grp in groups.items():
                row: Dict[str, Any] = {}
                for i, g in enumerate(group_by):
                    row[g] = key_str.split("|")[i]
                for agg in aggregations:
                    af, func, alias = agg.get("field", ""), agg.get("func", "count").upper(), agg.get("alias", "")
                    vals = [r.get(af) for r in grp if r.get(af) is not None]
                    nums = [v for v in vals if isinstance(v, (int, float))]
                    alias = alias or f"{func}_{af}"
                    if func == "COUNT":
                        row[alias] = len(grp)
                    elif func == "SUM":
                        row[alias] = sum(nums) if nums else 0
                    elif func == "AVG":
                        row[alias] = sum(nums) / len(nums) if nums else 0
                    elif func == "MIN":
                        row[alias] = min(nums) if nums else 0
                    elif func == "MAX":
                        row[alias] = max(nums) if nums else 0
                    else:
                        row[alias] = len(grp)
                result.append(row)
            return result

    def sort_data(self, source: str, sort_field: str, ascending: bool = True) -> List[Dict]:
        with self._lock:
            if source not in self._loaded_data:
                raise KeyError(f"Source not found: {source}")
            records = list(self._loaded_data[source])
            records.sort(key=lambda r: (1, "") if r.get(sort_field) is None else (0, r.get(sort_field) if isinstance(r.get(sort_field), (int, float)) else str(r.get(sort_field))), reverse=not ascending)
            return records

    def validate(self, source: str, rules: List[DataValidationRule]) -> List[ValidationResult]:
        with self._lock:
            if source not in self._loaded_data:
                raise KeyError(f"Source not found: {source}")
            records = self._loaded_data[source]
            type_map = {"string": str, "integer": int, "float": float, "boolean": bool}
            results: List[ValidationResult] = []
            for rule in rules:
                violations, samples = 0, []
                for i, record in enumerate(records):
                    val = record.get(rule.field_name)
                    ok = True
                    rt = rule.rule_type
                    if rt == "required" and val is None:
                        ok = False
                    elif rt == "type" and val is not None and not isinstance(val, type_map.get(rule.parameters.get("type", "string"), str)):
                        ok = False
                    elif rt == "range" and val is not None and isinstance(val, (int, float)):
                        mn, mx = rule.parameters.get("min"), rule.parameters.get("max")
                        if (mn is not None and val < mn) or (mx is not None and val > mx):
                            ok = False
                    elif rt == "pattern" and val is not None and not re.search(rule.parameters.get("pattern", ""), str(val)):
                        ok = False
                    elif rt == "unique":
                        seen = {}
                        for r in records:
                            rv = str(r.get(rule.field_name, ""))
                            if rv in seen:
                                ok = False
                            seen[rv] = True
                    elif rt == "custom":
                        func = rule.parameters.get("function")
                        if func and callable(func):
                            try:
                                ok = func(val, record)
                            except Exception:
                                ok = False
                    if not ok:
                        violations += 1
                        if len(samples) < 5:
                            samples.append({"row": i, "value": val, "rule": rt})
                vid = hashlib.md5(f"{rule.rule_id}_{time.time()}".encode()).hexdigest()[:12]
                results.append(ValidationResult(validation_id=vid, rule=rule, passed=(violations == 0), violations=violations, sample_violations=samples))
            return results

    def _export_csv(self, data: List[Dict], output_path: str) -> None:
        if not data:
            return
        all_keys = self._collect_keys(data)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys)
            writer.writeheader()
            writer.writerows(data)

    def _export_json(self, data: List[Dict], output_path: str) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _export_jsonl(self, data: List[Dict], output_path: str) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            for record in data:
                f.write(json.dumps(record, default=str) + "\n")

    def export(self, source: str, output_path: str, format: DataFormat = DataFormat.CSV) -> bool:
        with self._lock:
            if source not in self._loaded_data:
                return False
            exporters = {
                DataFormat.CSV: self._export_csv, DataFormat.TSV: self._export_csv,
                DataFormat.JSON: self._export_json, DataFormat.JSONL: self._export_jsonl,
            }
            try:
                exporters.get(format, self._export_csv)(self._loaded_data[source], output_path)
                return True
            except Exception:
                return False

    def compute_statistics(self, source: str) -> Dict:
        with self._lock:
            if source not in self._loaded_data:
                raise KeyError(f"Source not found: {source}")
            records = self._loaded_data[source]
            schema = self._schemas.get(source)
            stats: Dict[str, Any] = {
                "source": source, "total_records": len(records),
                "total_columns": len(schema.fields) if schema else 0, "columns": {},
            }
            if not records:
                return stats
            for key in self._collect_keys(records):
                values = [r.get(key) for r in records]
                non_null = [v for v in values if v is not None]
                nums = [v for v in non_null if isinstance(v, (int, float))]
                col: Dict[str, Any] = {
                    "total_count": len(values), "null_count": len(values) - len(non_null),
                    "unique_count": len(set(str(v) for v in non_null)),
                }
                if nums:
                    col.update(type="numeric", min=min(nums), max=max(nums), mean=sum(nums) / len(nums), sum=sum(nums))
                else:
                    str_vals = [str(v) for v in non_null]
                    if str_vals:
                        lens = [len(s) for s in str_vals]
                        col.update(type="text", min_length=min(lens), max_length=max(lens), avg_length=sum(lens) / len(lens))
                    else:
                        col["type"] = "text"
                stats["columns"][key] = col
            return stats

    def search_across_sources(self, query: str) -> List[Dict]:
        with self._lock:
            results: List[Dict] = []
            q = query.lower()
            for src, records in self._loaded_data.items():
                for i, rec in enumerate(records):
                    if any(v is not None and q in str(v).lower() for v in rec.values()):
                        results.append({"source": src, "row_index": i, "record": rec})
            return results

    def get_engine_summary(self) -> Dict:
        with self._lock:
            return {
                "version": self.VERSION, "loaded_sources": len(self._loaded_data),
                "source_names": list(self._loaded_data.keys()),
                "total_records": sum(len(r) for r in self._loaded_data.values()),
                "schemas": {k: v.to_dict() for k, v in self._schemas.items()},
                "join_history_count": len(self._join_history),
                "recent_joins": [j.to_dict() for j in self._join_history[-5:]],
            }
