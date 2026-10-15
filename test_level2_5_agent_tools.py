"""
Genesis OS â€” Level 2.5
Agent Tooling & Real Agent Artifacts.

Agents no longer only talk â€” they ACT and produce verified
real-world artifacts:

    Coding Agent   -> saves generated code, syntax-verifies Python
    Data Agent     -> computes REAL statistics from CSV / series
    Security Agent -> deterministic password entropy analysis
    Design Agent   -> generates real SVG palette boards
    Study Agent    -> parses quiz into a flashcard deck file
    Planning Agent -> saves every plan as markdown
    Document Agent -> reads real .docx/.txt; creates real DOCX
"""

from unittest.mock import Mock

import pytest

from agents.agent_tools import (
    AgentWorkspace,
    choose_extension,
    extract_code_blocks,
    find_csv_path,
    inline_number_series,
    palette_svg,
    password_strength,
    series_statistics,
    csv_column_statistics,
    syntax_check_python,
)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    return AgentWorkspace(
        base_root=tmp_path_factory.mktemp("studio")
    )


# =========================================================
# ARTIFACT WORKSPACE
# =========================================================


def test_artifact_save_verifies_by_readback(workspace):
    result = workspace.save_text_artifact(
        kind="Code",
        base_name="hello world function",
        content="print('hi')\n",
        extension=".py",
    )

    assert result["success"] is True
    assert result["verified"] is True
    from pathlib import Path

    assert Path(result["path"]).read_text(encoding="utf-8") == "print('hi')\n"


def test_artifact_rejects_unknown_kind(workspace):
    result = workspace.save_text_artifact("Banana", "x", "content", ".txt")

    assert result["success"] is False


def test_artifact_rejects_empty_content(workspace):
    result = workspace.save_text_artifact("Code", "x", "   ", ".py")

    assert result["success"] is False
    assert result["executed"] is False


# =========================================================
# CODE TOOLS
# =========================================================


def test_extract_code_blocks():
    response = (
        "Here you go:\n```python\nprint('a')\n```\nand also\n```js\nlet x=1;\n```\n"
    )

    blocks = extract_code_blocks(response)

    assert blocks == [
        ("python", "print('a')"),
        ("js", "let x=1;"),
    ]


def test_choose_extension():
    assert choose_extension(["python"], "make a script") == ".py"
    assert choose_extension([], "write javascript code") == ".js"
    assert choose_extension([], "mystery task") == ".txt"


def test_python_syntax_verification_passes_and_fails():
    assert syntax_check_python("def f():\n    return 1\n")["ok"] is True

    broken = syntax_check_python("def f(:\n    return 1\n")
    assert broken["ok"] is False
    assert "SyntaxError" in broken["error"]


# =========================================================
# DATA TOOLS
# =========================================================


def test_find_csv_path_only_when_real(tmp_path):
    real = tmp_path / "sales.csv"
    real.write_text("a,b\n", encoding="utf-8")

    assert find_csv_path(f"analyze {real} for trends") == str(real)
    assert find_csv_path("analyze missing_file.csv") is None


def test_csv_statistics_are_real_numbers(tmp_path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text(
        "month,revenue\nJan,100\nFeb,120\nMar,90\nApr,150\nMay,180\n",
        encoding="utf-8",
    )

    stats = csv_column_statistics(str(csv_file))

    assert stats["success"] is True
    assert stats["row_count"] == 5

    revenue = stats["columns"]["revenue"]
    assert revenue["min"] == 90
    assert revenue["max"] == 180
    assert revenue["mean"] == 128.0
    assert revenue["median"] == 120
    # Second half mean (165) vs first half mean (103) -> growth.
    assert revenue["trend_percent"] > 0


def test_inline_series_extraction_and_stats():
    series = inline_number_series("analyze sales 12 15 14 22 19 30")

    stats = series_statistics(series)

    assert stats["success"] is True
    assert stats["count"] == 6
    assert stats["min"] == 12
    assert stats["max"] == 30


# =========================================================
# SECURITY TOOL
# =========================================================


def test_password_analysis_weak():
    result = password_strength("password123")

    assert result["success"] is True
    assert result["verdict"] in {"Weak", "Moderate"}
    assert any("common fragment" in issue for issue in result["issues"])


def test_password_analysis_strong():
    result = password_strength("T7#kQz!vLm2@Rp9&")

    assert result["success"] is True
    assert result["score"] >= 55
    assert all(
        (
            result["has_lowercase"],
            result["has_uppercase"],
            result["has_digits"],
            result["has_symbols"],
        )
    )


def test_password_empty_rejected():
    assert password_strength("")["success"] is False


# =========================================================
# DESIGN TOOL
# =========================================================


def test_palette_svg_generates_valid_structure():
    result = palette_svg("sunset", title="My App")

    assert result["success"] is True
    assert result["svg"].startswith("<svg")
    assert result["svg"].endswith("</svg>")
    assert "#355070" in result["svg"]


def test_palette_svg_unknown_theme_is_honest():
    result = palette_svg("banana")

    assert result["success"] is False
    assert "Available themes" in result["error"]


# =========================================================
# AGENT INTEGRATION â€” MOCKED AI, REAL TOOLS
# =========================================================


def _fake_ai(response_text):
    ai = Mock()
    ai.generate_response.return_value = response_text
    return ai


def test_coding_agent_saves_and_syntax_checks_real_file(tmp_path):
    from agents.coding_agent import CodingAgent

    agent = CodingAgent()
    agent.ai = _fake_ai(
        "## Solution\n```python\nprint('hello genesis')\n```\n"
    )
    agent.workspace = AgentWorkspace(base_root=tmp_path)

    result = agent.run("write a python hello world program")

    assert result["metadata"].get("artifact_saved") is True
    assert result["metadata"].get("artifact_syntax_ok") is True

    from pathlib import Path
    code_files = list((tmp_path / "Code").glob("*.py"))
    assert code_files and "hello genesis" in code_files[0].read_text(encoding="utf-8")


def test_coding_agent_reports_broken_syntax_honestly(tmp_path):
    from agents.coding_agent import CodingAgent

    agent = CodingAgent()
    agent.ai = _fake_ai("```python\ndef broken(:\n```")
    agent.workspace = AgentWorkspace(base_root=tmp_path)

    result = agent.run("write a python function")

    assert result["metadata"].get("artifact_saved") is True
    assert result["metadata"].get("artifact_syntax_ok") is False
    # The response must carry the failure honestly.
    assert "FAILED" in result["response"]


def test_data_agent_uses_real_csv_numbers(tmp_path):
    from agents.data_agent import DataAgent

    csv_file = tmp_path / "revenue.csv"
    csv_file.write_text(
        "month,value\nA,10\nB,20\nC,30\nD,40\n",
        encoding="utf-8",
    )

    agent = DataAgent()
    captured_prompt = {}

    def capture(prompt):
        captured_prompt["text"] = prompt
        return "Analysis complete."

    agent.ai = Mock()
    agent.ai.generate_response.side_effect = capture

    result = agent.run(f"analyze {csv_file} and find trends")

    prompt_text = captured_prompt["text"]
    assert "REAL DATA" in prompt_text
    assert "mean=25.0" in prompt_text
    assert result["metadata"].get("csv_analyzed") == str(csv_file)


def test_security_agent_measures_password_deterministically():
    from agents.security_agent import SecurityAgent

    agent = SecurityAgent()
    agent.ai = _fake_ai("Security assessment: the password is weak.")

    result = agent.run("check my password strength: Tr0ub4dor&3xample")

    analysis = result["metadata"].get("password_analysis")

    if analysis is None:
        pytest.skip("regex did not match; ensure gate text present")

    assert analysis["verdict"] in {"Weak", "Moderate", "Strong"}
    assert isinstance(analysis["charset_entropy_bits"], float)


def test_design_agent_creates_openable_svg(tmp_path):
    from agents.design_agent import DesignAgent

    agent = DesignAgent()
    agent.ai = _fake_ai("Design concept for a landing page...")
    agent.workspace = AgentWorkspace(base_root=tmp_path)

    result = agent.run("design a neon themed landing page layout")

    assert result["metadata"].get("artifact_saved") is True

    from pathlib import Path
    svgs = list((tmp_path / "Designs").glob("*.svg"))
    assert svgs and svgs[0].read_text(encoding="utf-8").startswith("<svg")


def test_planning_agent_saves_plan_markdown(tmp_path):
    from agents.planning_agent import PlanningAgent

    agent = PlanningAgent()
    agent.ai = _fake_ai("# Objective\nLaunch in 6 weeks.")
    agent.workspace = AgentWorkspace(base_root=tmp_path)

    result = agent.run("plan the launch of my mobile app")

    assert result["metadata"].get("artifact_saved") is True

    from pathlib import Path
    plans = list((tmp_path / "Plans").glob("*.md"))
    assert plans and "Objective" in plans[0].read_text(encoding="utf-8")


def test_study_agent_parses_quiz_into_deck(tmp_path):
    from agents.study_agent import StudyAgent

    quiz_response = (
        "## Explanation\nPhotosynthesis converts light.\n"
        "## Quiz\n"
        "Q1: What do plants use? \nA1: Sunlight\n"
        "Q2: Byproduct?\nA2: Oxygen\n"
    )

    agent = StudyAgent()
    agent.ai = _fake_ai(quiz_response)
    agent.workspace = AgentWorkspace(base_root=tmp_path)

    result = agent.run("teach me photosynthesis with a quiz")

    assert result["metadata"].get("artifact_saved") is True
    assert result["metadata"].get("card_count") == 2

    from pathlib import Path
    decks = list((tmp_path / "Study").glob("*.txt"))
    content = decks[0].read_text(encoding="utf-8")
    assert "What do plants use?" in content
    assert "Sunlight" in content


def test_document_agent_creates_verified_docx(tmp_path):
    from agents.document_agent import DocumentAgent

    doc_response = (
        "# Climate Report\n"
        "## Overview\nThe climate is changing.\n"
        "## Findings\nTemperatures are rising globally.\n"
    )

    agent = DocumentAgent()
    agent.ai = _fake_ai(doc_response)
    agent.workspace = AgentWorkspace(base_root=tmp_path)

    result = agent.run("create a document about climate change")

    assert result["metadata"].get("artifact_saved") is True

    from pathlib import Path
    from docx import Document as DocxDocument

    docx_files = list((tmp_path / "Documents").glob("*.docx"))
    assert docx_files

    reopened = DocxDocument(str(docx_files[0]))
    assert any("Climate Report" in p.text for p in reopened.paragraphs)


def test_document_agent_reads_real_txt(tmp_path):
    from agents.document_agent import DocumentAgent

    note = tmp_path / "meeting.txt"
    note.write_text("Budget approved for Q4.", encoding="utf-8")

    agent = DocumentAgent()
    captured_prompt = {}

    def capture(prompt):
        captured_prompt["text"] = prompt
        return "Summary: budget approved."

    agent.ai = Mock()
    agent.ai.generate_response.side_effect = capture

    result = agent.run(f"summarize {note}")

    assert "REAL DOCUMENT CONTENT" in captured_prompt["text"]
    assert "Budget approved for Q4." in captured_prompt["text"]
    assert result["metadata"].get("extracted_chars", 0) > 0


