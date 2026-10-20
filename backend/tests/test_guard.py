"""The runtime must never read recorded fixtures or import test code (fixtures are test-only)."""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_app_never_imports_tests_or_fixtures():
    offenders = []
    for py in APP.rglob("*.py"):
        src = py.read_text()
        for node in ast.walk(ast.parse(src)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            offenders += [f"{py.name}: {m}" for m in mods if m == "tests" or m.startswith("tests.")]
        if "tests/fixtures" in src or "fixtures/sessions" in src:
            offenders.append(f"{py.name}: references fixture path")
    assert offenders == []
