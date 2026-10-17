"""Gemini must never decide. The AI module may not touch commands, stores or state."""

import ast
from pathlib import Path

from loopcloser.ai.assist import AI_LABEL, summarize_case

AI_DIR = Path(__file__).resolve().parents[1] / "loopcloser" / "ai"
FORBIDDEN = ("domain", "store", "pathways", "imports", "commands")


def test_ai_module_imports_nothing_that_can_change_cases():
    for f in AI_DIR.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not any(x in mod.split(".") for x in FORBIDDEN), f"{f.name} imports {mod}"
                assert node.level == 0 or not mod, f"{f.name} uses a relative import: {mod}"
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert "loopcloser" not in a.name, f"{f.name} imports {a.name}"


def test_mock_summary_is_labeled_and_masks_input():
    d = summarize_case(
        {
            "id": "C-1",
            "state": "reviewed",
            "next_action": "x",
            "due_date": "2026-11-01",
            "masked_name": "Maria D.",
            "phone": "+639000000001",
        }
    )
    assert d.mock and d.label == AI_LABEL
    assert "Maria" not in d.text and "+639" not in d.text
