import pytest
from pathlib import Path


def test_no_eval_in_code():
    # Locate main.py in repo root (search up the tree)
    current = Path(__file__).resolve()
    main_path = None
    for p in current.parents:
        candidate = p / "main.py"
        if candidate.exists():
            main_path = candidate
            break
    if not main_path:
        pytest.skip("main.py not found in repository")
    with open(main_path) as f:
        code = f.read()
    assert "eval(" not in code
