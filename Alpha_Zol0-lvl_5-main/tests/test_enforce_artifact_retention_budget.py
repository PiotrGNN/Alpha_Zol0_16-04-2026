import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "enforce_artifact_retention_budget.py"
    )
    spec = importlib.util.spec_from_file_location("retention_budget", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_file_limit_dry_run_and_apply(tmp_path):
    module = _load_module()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    target = logs_dir / "bot.log"
    target.write_bytes(b"X" * 4096)

    policy = {
        "file_limits": [
            {
                "path": "logs/bot.log",
                "max_bytes": 1024,
                "tail_bytes": 256,
            }
        ],
        "directory_retention": [],
        "hot_directory_budgets": [],
    }

    report_dry = module.enforce_policy(root=tmp_path, policy=policy, apply=False)
    assert report_dry["actions_count"] == 1
    assert target.stat().st_size == 4096

    report_apply = module.enforce_policy(root=tmp_path, policy=policy, apply=True)
    assert report_apply["actions_count"] == 1
    assert target.stat().st_size <= 256


def test_directory_retention_keep_latest(tmp_path):
    module = _load_module()
    base = tmp_path / "reports" / "paper_runtime_patch_validation"
    base.mkdir(parents=True, exist_ok=True)

    d1 = base / "repair_iteration_1"
    d2 = base / "repair_iteration_2"
    d3 = base / "repair_iteration_3"
    d1.mkdir()
    d2.mkdir()
    d3.mkdir()

    # Ensure deterministic ordering by mtime.
    d1_file = d1 / "a.txt"
    d2_file = d2 / "a.txt"
    d3_file = d3 / "a.txt"
    d1_file.write_text("1", encoding="utf-8")
    d2_file.write_text("2", encoding="utf-8")
    d3_file.write_text("3", encoding="utf-8")

    policy = {
        "file_limits": [],
        "directory_retention": [
            {
                "path": "reports/paper_runtime_patch_validation",
                "glob": "repair_iteration_*",
                "keep_latest": 2,
            }
        ],
        "hot_directory_budgets": [],
    }

    report = module.enforce_policy(root=tmp_path, policy=policy, apply=True)
    assert report["actions_count"] == 1
    remaining = sorted(p.name for p in base.glob("repair_iteration_*") if p.is_dir())
    assert len(remaining) == 2


def test_file_retention_keep_latest(tmp_path):
    module = _load_module()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    f1 = tmp_dir / "controlled_kpi_1.log"
    f2 = tmp_dir / "controlled_kpi_2.log"
    f3 = tmp_dir / "controlled_kpi_3.log"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")
    f3.write_text("3", encoding="utf-8")

    policy = {
        "file_limits": [],
        "directory_retention": [],
        "file_retention": [
            {
                "path": "tmp",
                "glob": "controlled_kpi_*",
                "keep_latest": 2,
            }
        ],
        "hot_directory_budgets": [],
    }

    report = module.enforce_policy(root=tmp_path, policy=policy, apply=True)
    assert report["actions_count"] == 1
    remaining = sorted(p.name for p in tmp_dir.glob("controlled_kpi_*.log"))
    assert len(remaining) == 2
