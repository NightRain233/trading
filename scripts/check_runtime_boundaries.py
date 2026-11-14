#!/usr/bin/env python3
"""Fail if the trading runtime imports the sibling xquant package."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / "backend", ROOT / "scripts")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def main() -> int:
    violations: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if any(
                part in {"tests", "trading_research", ".venv", "__pycache__", "data", "backtest_results"}
                for part in path.parts
            ):
                continue
            if any(name == "xquant" or name.startswith("xquant.") for name in _imports(path)):
                violations.append(str(path.relative_to(ROOT)))
    if violations:
        print("Runtime files must not import xquant:")
        print("\n".join(sorted(violations)))
        return 1
    print("Runtime boundary check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
