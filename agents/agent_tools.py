"""
Genesis OS — Level 2.5
Agent Tooling.

Real tools that let Level 2 agents ACT, not just talk:

    - artifact saving with readback verification
      (code, documents, designs, study decks, plans, reports)
    - code block extraction + Python syntax verification
    - genuine CSV / numeric-series statistics
    - deterministic password strength analysis
    - deterministic SVG design generation

Every artifact write is VERIFIED by reading the file back.
Agents never claim an action happened without evidence.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import math
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =========================================================
# ARTIFACT WORKSPACE
# =========================================================


class AgentWorkspace:

    VERSION = "2.5.0"

    KINDS = (
        "Code",
        "Documents",
        "Designs",
        "Study",
        "Plans",
        "Reports",
        "Data",
    )

    def __init__(self, base_root=None):
        self.base_root = (
            Path(base_root)
            if base_root is not None
            else Path.home() / "Documents" / "Genesis Studio"
        )

    # ---------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------

    def save_text_artifact(
        self,
        kind: str,
        base_name: str,
        content: str,
        extension: str,
    ) -> Dict[str, Any]:
        """
        Save one text artifact under the workspace kind folder
        and verify by reading it back.
        """

        kind_clean = str(kind).strip().capitalize()

        if kind_clean not in self.KINDS:
            return {
                "success": False,
                "operation": "artifact.save",
                "error": f"Unknown artifact kind '{kind}'.",
                "executed": False,
                "verified": False,
            }

        content_text = "" if content is None else str(content)

        if not content_text.strip():
            return {
                "success": False,
                "operation": "artifact.save",
                "error": "There is no content to save.",
                "executed": False,
                "verified": False,
            }

        slug = _slugify(base_name) or "artifact"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        directory = self.base_root / kind_clean
        target = directory / f"{stamp}_{slug}{extension}"

        try:
            directory.mkdir(parents=True, exist_ok=True)
            target.write_text(content_text, encoding="utf-8")
            readback = target.read_text(encoding="utf-8")
        except OSError as error:
            return {
                "success": False,
                "operation": "artifact.save",
                "path": str(target),
                "error": str(error),
                "executed": True,
                "verified": False,
            }

        verified = readback == content_text

        return {
            "success": bool(verified),
            "operation": "artifact.save",
            "path": str(target),
            "bytes": len(content_text.encode("utf-8")),
            "sha256_16": hashlib.sha256(
                content_text.encode("utf-8")
            ).hexdigest()[:16],
            "executed": True,
            "verified": bool(verified),
            "verification_type": "file_readback",
        }


def _slugify(value: str, max_length: int = 40) -> str:
    slug = "".join(
        ch if ch.isalnum() else "-"
        for ch in str(value).strip().lower()
    )
    parts = [p for p in slug.split("-") if p]
    return "-".join(parts)[:max_length]


# =========================================================
# CODE TOOLS
# =========================================================

_CODE_BLOCK_RE = re.compile(
    r"```([a-zA-Z0-9_+#]*)\s*\n(.*?)```",
    re.DOTALL,
)

_LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "java": ".java",
    "csharp": ".cs",
    "c#": ".cs",
    "cpp": ".cpp",
    "c++": ".cpp",
    "c": ".c",
    "html": ".html",
    "css": ".css",
    "sql": ".sql",
    "bash": ".sh",
    "shell": ".sh",
    "json": ".json",
    "yaml": ".yaml",
    "yml": ".yml",
}


def extract_code_blocks(ai_response: str) -> List[Tuple[str, str]]:
    """
    Extract fenced code blocks as (language_hint_lower, code).
    """

    if not isinstance(ai_response, str):
        return []

    blocks = []

    for match in _CODE_BLOCK_RE.finditer(ai_response):
        language = (match.group(1) or "").strip().lower()
        code = match.group(2)

        if code.strip():
            blocks.append((language, code.rstrip()))

    return blocks


def choose_extension(language_hints: List[str], task: str) -> str:
    for hint in language_hints:
        if hint in _LANGUAGE_EXTENSIONS:
            return _LANGUAGE_EXTENSIONS[hint]

    lowered = str(task or "").lower()

    for name, extension in _LANGUAGE_EXTENSIONS.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return extension

    return ".txt"


def syntax_check_python(code: str) -> Dict[str, Any]:
    """
    Verify that Python source actually PARSES. This is real,
    deterministic evidence — not an opinion.
    """

    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "error": "No code provided."}

    try:
        ast.parse(code)
        return {"ok": True, "error": None}
    except SyntaxError as error:
        return {
            "ok": False,
            "error": (
                f"SyntaxError line {error.lineno}: {error.msg}"
            ),
        }


# =========================================================
# DATA TOOLS
# =========================================================


def find_csv_path(task: str) -> Optional[str]:
    r"""
    Find a plausible CSV file path inside a task string.

    Splits the task on whitespace and, for every token that
    ends in ``.csv`` (with optional trailing punctuation),
    tests ``Path(token).is_file()`` directly. Returns the
    LAST token that resolves to a real file, or ``None``.

    The previous single-regex approach (matching
    ``r"[\w\- ./\\]+\.csv"``) was greedy and matched entire
    phrases including leading words (``"analyze /tmp/x/sales.csv
    for trends"`` captured ``"analyze /tmp/x/sales.csv"``),
    which then failed ``Path(...).is_file()`` and silently
    dropped real file content.
    """
    if not isinstance(task, str):
        return None

    last_real: Optional[str] = None
    for raw in re.split(r"\s+", task):
        if not raw:
            continue
        # Strip surrounding quotes and trailing punctuation
        # that legitimately appear at the end of a sentence
        # token (commas, periods, exclamation marks, quotes,
        # closing brackets).
        token = raw.strip().strip("\"'()[]{}<>.,!?;:")
        if not token.lower().endswith(".csv"):
            continue
        path = Path(token).expanduser()
        if path.is_file():
            last_real = str(path)
    return last_real


def find_data_path(task: str) -> Optional[str]:
    if not isinstance(task, str):
        return None
    found = None
    for raw in re.split(r"\s+", task):
        token = raw.strip().strip("\"'()[]{}<>.,!?;:")
        if not token.lower().endswith((".csv", ".xlsx", ".xlsm")):
            continue
        path = Path(token).expanduser()
        if path.is_file():
            found = str(path)
    return found


def data_column_statistics(path: str, max_columns: int = 6) -> Dict[str, Any]:
    if Path(path).suffix.lower() == ".csv":
        return csv_column_statistics(path, max_columns=max_columns)
    result = {"success": False, "columns": {}, "row_count": 0}
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows = sheet.iter_rows(values_only=True)
            headers = [str(value).strip() if value is not None else "" for value in next(rows)]
            columns = {header: [] for header in headers if header}
            row_count = 0
            for row in rows:
                row_count += 1
                for index, header in enumerate(headers[:max_columns]):
                    if not header or index >= len(row) or row[index] is None:
                        continue
                    try:
                        columns[header].append(float(row[index]))
                    except (TypeError, ValueError):
                        continue
            result["row_count"] = row_count
            for name, values in columns.items():
                if len(values) < 2:
                    continue
                entry = {
                    "count": len(values),
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                    "mean": round(statistics.mean(values), 4),
                    "median": round(statistics.median(values), 4),
                }
                if len(values) >= 3:
                    try:
                        entry["stdev"] = round(statistics.stdev(values), 4)
                    except statistics.StatisticsError:
                        pass
                result["columns"][name] = entry
            result["success"] = True
            return result
        finally:
            workbook.close()
    except Exception as error:
        result["error"] = str(error)
        return result


def csv_column_statistics(path: str, max_columns: int = 6) -> Dict[str, Any]:
    """
    Genuine descriptive statistics for every numeric column of
    a CSV file, computed with the standard library.

    No AI involved: these are real numbers from the real file.
    """

    result: Dict[str, Any] = {
        "success": False,
        "columns": {},
        "row_count": 0,
    }

    try:
        path_obj = Path(path).expanduser()
        if not path_obj.is_file():
            result["error"] = f"File not found: {path}"
            return result

        with path_obj.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
            sample = handle.read(1 << 20)

        dialect = sniff_dialect(sample)

        with path_obj.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
            reader = csv.DictReader(handle, dialect=dialect)

            if not reader.fieldnames:
                result["error"] = "The CSV has no header row."
                return result

            columns: Dict[str, List[float]] = {
                name.strip(): []
                for name in reader.fieldnames
                if name
            }

            row_count = 0

            for row in reader:
                row_count += 1

                for name in list(columns.keys())[:max_columns]:
                    raw = row.get(name)
                    if raw is None:
                        continue
                    try:
                        columns[name].append(float(raw.strip()))
                    except ValueError:
                        continue

        result["row_count"] = row_count

        for name, values in columns.items():
            if len(values) < 2:
                continue

            entry = {
                "count": len(values),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "mean": round(statistics.mean(values), 4),
                "median": round(statistics.median(values), 4),
            }

            if len(values) >= 3:
                try:
                    entry["stdev"] = round(statistics.stdev(values), 4)
                except statistics.StatisticsError:
                    pass

            if len(values) >= 3:
                first_half = values[: len(values) // 2]
                second_half = values[len(values) // 2 :]
                first_mean = statistics.mean(first_half)
                second_mean = statistics.mean(second_half)

                if first_mean != 0:
                    change = (second_mean - first_mean) / abs(first_mean) * 100
                    entry["trend_percent"] = round(change, 2)

            result["columns"][name] = entry

        result["success"] = bool(result["columns"])

        if not result["columns"]:
            result["error"] = "No numeric columns were found."

        return result

    except Exception as error:
        result["error"] = str(error)
        return result


def sniff_dialect(sample: str):
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def inline_number_series(task: str) -> List[float]:
    """
    Extract a plain number series from the task text, e.g.
    "analyze sales 12 15 14 22 19 30".
    """

    if not isinstance(task, str):
        return []

    numbers = [
        float(token)
        for token in re.findall(r"(?<![\w.])(-?\d+(?:\.\d+)?)(?![\w.%])", task)
    ]

    return numbers if len(numbers) >= 3 else []


def series_statistics(values: List[float]) -> Dict[str, Any]:
    if len(values) < 2:
        return {"success": False, "error": "At least two numbers are required."}

    entry = {
        "success": True,
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(statistics.mean(values), 4),
        "median": round(statistics.median(values), 4),
    }

    if len(values) >= 3:
        try:
            entry["stdev"] = round(statistics.stdev(values), 4)
        except statistics.StatisticsError:
            pass

    return entry


# =========================================================
# SECURITY TOOLS
# =========================================================

_COMMON_PASSWORD_FRAGMENTS = (
    "password", "123456", "qwerty", "letmein", "admin",
    "welcome", "iloveyou", "monkey", "dragon", "abc123",
)


def password_strength(password: str) -> Dict[str, Any]:
    """
    Deterministic password analysis: charset entropy plus
    pattern penalties. Pure computation — no AI, no network.
    """

    if not isinstance(password, str) or not password:
        return {
            "success": False,
            "operation": "security.password_check",
            "error": "A password is required.",
        }

    length = len(password)

    charset_size = 0
    checks = {
        "lowercase": any(ch.islower() for ch in password),
        "uppercase": any(ch.isupper() for ch in password),
        "digits": any(ch.isdigit() for ch in password),
        "symbols": any(not ch.isalnum() for ch in password),
    }

    if checks["lowercase"]:
        charset_size += 26
    if checks["uppercase"]:
        charset_size += 26
    if checks["digits"]:
        charset_size += 10
    if checks["symbols"]:
        charset_size += 33

    entropy_bits = round(length * math.log2(charset_size), 1) if charset_size else 0.0

    issues = []

    lowered = password.lower()

    if length < 12:
        issues.append("Shorter than 12 characters")

    for fragment in _COMMON_PASSWORD_FRAGMENTS:
        if fragment in lowered:
            issues.append(f"Contains the common fragment '{fragment}'")

    if re.search(r"(.)\1\1", password):
        issues.append("Contains three identical characters in a row")

    sequential = "".join(map(str, range(10)))
    if sequential in password or "abcdefgh" in lowered:
        issues.append("Contains a sequential run")

    if not checks["symbols"]:
        issues.append("No special symbols")
    if not checks["digits"]:
        issues.append("No digits")
    if not checks["uppercase"]:
        issues.append("No uppercase letters")

    score = max(0, min(100, int(entropy_bits)))

    penalties = min(40, 10 * len(issues))
    score = max(0, score - penalties)

    if score >= 80:
        verdict = "Strong"
    elif score >= 55:
        verdict = "Moderate"
    else:
        verdict = "Weak"

    return {
        "success": True,
        "operation": "security.password_check",
        "length": length,
        "charset_entropy_bits": entropy_bits,
        "score": score,
        "verdict": verdict,
        "issues": issues,
        "has_lowercase": checks["lowercase"],
        "has_uppercase": checks["uppercase"],
        "has_digits": checks["digits"],
        "has_symbols": checks["symbols"],
        "message": (
            f"Password verdict: {verdict} ({score}/100, "
            f"{entropy_bits} bits of charset entropy)."
        ),
    }


# =========================================================
# DESIGN TOOLS
# =========================================================

_DESIGN_THEMES = {
    "ocean": ["#0B3954", "#087E8B", "#BFD7EA", "#FF5A5F", "#C81D25"],
    "sunset": ["#355070", "#6D597A", "#B56576", "#E56B6F", "#EAAC8B"],
    "forest": ["#132A13", "#31572C", "#4F772D", "#90A955", "#ECF39E"],
    "neon": ["#0D0221", "#FF006E", "#FB5607", "#FFBE0B", "#8338EC"],
    "mono": ["#212529", "#495057", "#868E96", "#CED4DA", "#F8F9FA"],
}


def palette_svg(theme: str = "ocean", title: str = "Genesis Design") -> Dict[str, Any]:
    """
    Generate a real, openable SVG color-palette board from a
    named theme. Deterministic and instant.
    """

    theme_key = str(theme or "ocean").strip().lower()

    colors = _DESIGN_THEMES.get(theme_key)

    if colors is None:
        known = ", ".join(sorted(_DESIGN_THEMES))
        return {
            "success": False,
            "operation": "design.palette_svg",
            "error": (
                f"Unknown theme '{theme}'. Available themes: {known}."
            ),
        }

    width, height = 800, 300
    swatch_width = width // len(colors)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f"<rect width='100%' height='100%' fill='#FFFFFF'/>",
        f'<text x="20" y="40" font-family="Segoe UI, Arial" '
        f'font-size="24" fill="#333333">{title} — theme: {theme_key}</text>',
    ]

    for index, color in enumerate(colors):
        x = index * swatch_width
        parts.append(
            f'<rect x="{x}" y="80" width="{swatch_width}" height="160" '
            f'fill="{color}" stroke="#DDDDDD"/>'
        )
        parts.append(
            f'<text x="{x + 10}" y="270" font-family="Consolas, monospace" '
            f'font-size="16" fill="#333333">{color}</text>'
        )

    parts.append("</svg>")

    svg = "\n".join(parts)

    verified = svg.rstrip().endswith("</svg>") and svg.count("<rect") == len(colors) + 1
    return {
        "success": verified,
        "operation": "design.palette_svg",
        "theme": theme_key,
        "colors": colors,
        "svg": svg,
        "verified": verified,
        "verification_type": "structure_check",
    }
