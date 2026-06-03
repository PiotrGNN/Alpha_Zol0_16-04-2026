from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


def _tuple_assignment_values(name: str) -> set[str]:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if not isinstance(node.value, ast.Tuple):
            return set()
        return {
            item.value
            for item in node.value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
    return set()


def test_effective_env_values_include_entry_min_net_guards():
    keys = _tuple_assignment_values("EFFECTIVE_ENV_VALUE_KEYS")

    assert "ENTRY_MIN_NET_USDT" in keys
    assert "ENTRY_MIN_NET_TO_STOP_RATIO" in keys
