import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("controlled_kpi_run", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_override_fail_fast_missing_file(tmp_path):
    module = _load_module()
    missing = (tmp_path / "missing_source.db").resolve().as_posix()

    with pytest.raises(SystemExit, match="BOOTSTRAP_SOURCE_DB_MISSING"):
        module._validate_alpha_bootstrap_source_override(
            source_db_url=f"sqlite:///{missing}",
            source_db_glob="",
        )


def test_source_override_fail_fast_empty_file(tmp_path):
    module = _load_module()
    empty_db = tmp_path / "empty_source.db"
    empty_db.parent.mkdir(parents=True, exist_ok=True)
    empty_db.write_bytes(b"")

    with pytest.raises(SystemExit, match="BOOTSTRAP_SOURCE_DB_EMPTY"):
        module._validate_alpha_bootstrap_source_override(
            source_db_url=f"sqlite:///{empty_db.resolve().as_posix()}",
            source_db_glob="",
        )


def test_source_override_fail_fast_glob_empty(tmp_path):
    module = _load_module()
    pattern = (tmp_path / "glob_missing_*.db").as_posix()

    with pytest.raises(SystemExit, match="BOOTSTRAP_SOURCE_DB_GLOB_EMPTY"):
        module._validate_alpha_bootstrap_source_override(
            source_db_url="",
            source_db_glob=pattern,
        )


def test_source_override_validation_accepts_nonempty_file(tmp_path):
    module = _load_module()
    ok_db = tmp_path / "ok_source.db"
    ok_db.parent.mkdir(parents=True, exist_ok=True)
    ok_db.write_bytes(b"sqlite")

    module._validate_alpha_bootstrap_source_override(
        source_db_url=f"sqlite:///{ok_db.resolve().as_posix()}",
        source_db_glob="",
    )
