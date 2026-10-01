"""Principle 7: domain modules never import the orchestration framework or a provider SDK."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PKG = ROOT / "src" / "ai_backend"
DOMAIN = [PKG / d for d in ("bank", "tools", "policy", "handoff", "fx", "language", "files")] + [
    ROOT / "eval" / "metrics.py"
]
FORBIDDEN = ("langgraph", "langchain", "langchain_core", "anthropic", "openai")


def _domain_files() -> list[Path]:
    files: list[Path] = []
    for target in DOMAIN:
        if target.is_dir():
            files.extend(target.rglob("*.py"))
        elif target.exists():
            files.append(target)
    return files


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("path", _domain_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_domain_module_has_no_framework_imports(path: Path):
    assert not (_imports(path) & set(FORBIDDEN))
