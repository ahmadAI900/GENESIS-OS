from __future__ import annotations

import os
import re
import json
import time
import threading
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple


class TemplateType(str, Enum):
    CONTRACT = "contract"
    INVOICE = "invoice"
    REPORT = "report"
    LETTER = "letter"
    MEMO = "memo"
    RESUME = "resume"
    PRESENTATION = "presentation"
    CUSTOM = "custom"


@dataclass
class TemplateVariable:
    name: str
    var_type: str
    description: str
    required: bool = True
    default_value: Optional[str] = None
    validation_pattern: Optional[str] = None
    example_value: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "var_type": self.var_type,
            "description": self.description,
            "required": self.required,
            "default_value": self.default_value,
            "validation_pattern": self.validation_pattern,
            "example_value": self.example_value,
        }


@dataclass
class TemplateSection:
    section_id: str
    name: str
    condition: Optional[str]
    content: str
    variables: List[str] = field(default_factory=list)
    subsections: List['TemplateSection'] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "name": self.name,
            "condition": self.condition,
            "content": self.content,
            "variables": self.variables,
            "subsections": [s.to_dict() for s in self.subsections],
        }


@dataclass
class Template:
    template_id: str
    name: str
    template_type: TemplateType
    source_path: Optional[str]
    content: str
    variables: List[TemplateVariable] = field(default_factory=list)
    sections: List[TemplateSection] = field(default_factory=list)
    placeholders: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "template_type": self.template_type.value,
            "source_path": self.source_path,
            "content": self.content,
            "variables": [v.to_dict() for v in self.variables],
            "sections": [s.to_dict() for s in self.sections],
            "placeholders": self.placeholders,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class FillResult:
    result_id: str
    template_id: str
    filled_content: str
    variables_used: Dict[str, Any]
    sections_included: List[str]
    sections_excluded: List[str]
    warnings: List[str]
    output_path: Optional[str]
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "template_id": self.template_id,
            "filled_content": self.filled_content,
            "variables_used": self.variables_used,
            "sections_included": self.sections_included,
            "sections_excluded": self.sections_excluded,
            "warnings": self.warnings,
            "output_path": self.output_path,
            "timestamp": self.timestamp,
        }


class TemplateEngine:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._templates: Dict[str, Template] = {}
        self._fill_history: List[FillResult] = []
        self._lock = threading.RLock()

    def register_template(self, template: Template) -> None:
        with self._lock:
            self._templates[template.template_id] = template

    def create_from_file(self, file_path: str, name: str, template_type: TemplateType) -> Template:
        with self._lock:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            template = self._build_template(content, name, template_type, file_path)
            self._templates[template.template_id] = template
            return template

    def create_from_text(self, content: str, name: str, template_type: TemplateType) -> Template:
        with self._lock:
            template = self._build_template(content, name, template_type, None)
            self._templates[template.template_id] = template
            return template

    def _build_template(self, content: str, name: str, template_type: TemplateType, source_path: Optional[str]) -> Template:
        placeholders = self._extract_variables(content)
        sections = self._extract_sections(content)
        variables = [
            TemplateVariable(
                name=p,
                var_type="text",
                description=f"Variable {p}",
                required=True,
            )
            for p in placeholders
        ]
        template_id = hashlib.sha256(f"{name}:{content[:200]}".encode()).hexdigest()[:16]
        return Template(
            template_id=template_id,
            name=name,
            template_type=template_type,
            source_path=source_path,
            content=content,
            variables=variables,
            sections=sections,
            placeholders=placeholders,
            metadata={"source": "file" if source_path else "text"},
            created_at=time.time(),
        )

    def _extract_variables(self, content: str) -> List[str]:
        return list(dict.fromkeys(re.findall(r"\{\{(\w+)\}\}", content)))

    def _extract_sections(self, content: str) -> List[TemplateSection]:
        sections: List[TemplateSection] = []
        pattern = r"\{%\s*if\s+(.+?)\s*%\}(.*?)\{%\s*endif\s*%\}"
        for i, match in enumerate(re.finditer(pattern, content, re.DOTALL)):
            condition, body = match.group(1), match.group(2)
            variables = re.findall(r"\{\{(\w+)\}\}", body)
            sections.append(TemplateSection(
                section_id=f"section_{i}",
                name=f"Section {i}",
                condition=condition.strip(),
                content=body.strip(),
                variables=variables,
            ))
        return sections

    def fill_template(self, template_id: str, variables: Dict[str, Any], output_path: Optional[str] = None) -> FillResult:
        with self._lock:
            template = self._templates.get(template_id)
            if not template:
                raise ValueError(f"Template {template_id} not found")
            valid, warnings = self.validate_variables(template_id, variables)
            content = template.content
            content, inc, exc = self._process_conditionals(content, variables)
            content = self._process_loops(content, variables)
            content, subs = self._substitute_variables(content, variables)
            warnings.extend(subs)
            if output_path:
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(content)
            result = FillResult(
                result_id=hashlib.sha256(f"{template_id}:{time.time()}".encode()).hexdigest()[:16],
                template_id=template_id,
                filled_content=content,
                variables_used=variables,
                sections_included=inc,
                sections_excluded=exc,
                warnings=warnings,
                output_path=output_path,
                timestamp=time.time(),
            )
            self._fill_history.append(result)
            return result

    def _process_conditionals(self, content: str, variables: Dict[str, Any]) -> Tuple[str, List[str], List[str]]:
        included, excluded = [], []
        pattern = r"\{%\s*if\s+(.+?)\s*%\}(.*?)\{%\s*endif\s*%\}"

        def _replace(m: re.Match) -> str:
            condition, body = m.group(1).strip(), m.group(2)
            try:
                result = eval(condition, {"__builtins__": {}}, variables)
            except Exception:
                result = False
            if result:
                included.append(condition)
                return body
            else:
                excluded.append(condition)
                return ""

        return re.sub(pattern, _replace, content, flags=re.DOTALL), included, excluded

    def _process_loops(self, content: str, variables: Dict[str, Any]) -> str:
        pattern = r"\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}(.*?)\{%\s*endfor\s*%\}"

        def _replace(m: re.Match) -> str:
            item_var, list_var, body = m.group(1), m.group(2), m.group(3)
            items = variables.get(list_var, [])
            if not isinstance(items, list):
                return ""
            parts = []
            for item in items:
                rendered = re.sub(r"\{\{(.+?)\}\}", lambda vm: str(item.get(vm.group(1), "") if isinstance(item, dict) else item), body)
                parts.append(rendered)
            return "".join(parts)

        return re.sub(pattern, _replace, content, flags=re.DOTALL)

    def _substitute_variables(self, content: str, variables: Dict[str, Any]) -> Tuple[str, List[str]]:
        warnings: List[str] = []

        def _replace(m: re.Match) -> str:
            var = m.group(1)
            if var in variables:
                return str(variables[var])
            warnings.append(f"Missing variable: {var}")
            return m.group(0)

        return re.sub(r"\{\{(\w+)\}\}", _replace, content), warnings

    def validate_variables(self, template_id: str, variables: Dict[str, Any]) -> Tuple[bool, List[str]]:
        with self._lock:
            template = self._templates.get(template_id)
            if not template:
                return False, [f"Template {template_id} not found"]
            warnings = []
            for var in template.variables:
                if var.required and var.name not in variables:
                    warnings.append(f"Missing required variable: {var.name}")
            return len(warnings) == 0, warnings

    def list_templates(self) -> List[Dict]:
        with self._lock:
            return [t.to_dict() for t in self._templates.values()]

    def get_template(self, template_id: str) -> Optional[Template]:
        with self._lock:
            return self._templates.get(template_id)

    def preview_template(self, template_id: str, variables: Dict[str, Any]) -> str:
        with self._lock:
            template = self._templates.get(template_id)
            if not template:
                raise ValueError(f"Template {template_id} not found")
            content = template.content
            content, _, _ = self._process_conditionals(content, variables)
            content = self._process_loops(content, variables)
            content, _ = self._substitute_variables(content, variables)
            return content

    def get_fill_history(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return [r.to_dict() for r in self._fill_history[-limit:]]

    def get_engine_summary(self) -> Dict:
        with self._lock:
            type_counts = {}
            for t in self._templates.values():
                type_counts[t.template_type.value] = type_counts.get(t.template_type.value, 0) + 1
            return {
                "version": self.VERSION,
                "total_templates": len(self._templates),
                "templates_by_type": type_counts,
                "total_fills": len(self._fill_history),
            }
