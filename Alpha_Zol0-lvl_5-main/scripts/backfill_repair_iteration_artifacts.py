import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
REPORTS_BASE_DIR = WORKDIR / "reports" / "paper_runtime_patch_validation"


def _load_repair_iteration_module():
    module_path = WORKDIR / "scripts" / "repair_plan_kpi_iteration.py"
    spec = importlib.util.spec_from_file_location(
        "repair_plan_kpi_iteration",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repair_iter = _load_repair_iteration_module()


def _minimal_backfill_summary(iteration_dir: Path) -> dict:
    rollout_gate_path = iteration_dir / "rollout_gate_hardening.json"
    recommendation = {
        "patch_id": "unknown",
        "action": "hold",
        "reason": "backfill_missing_summary",
    }
    if rollout_gate_path.exists():
        try:
            rollout_payload = json.loads(rollout_gate_path.read_text(encoding="utf-8"))
            rec = (
                (rollout_payload.get("rollout_gates") or {}).get("recommendation")
                or rollout_payload.get("recommendation")
                or {}
            )
            recommendation = {
                "patch_id": str(rec.get("patch_id") or "unknown"),
                "action": str(rec.get("action") or "hold"),
                "reason": str(rec.get("reason") or "backfill_from_rollout_gate"),
            }
        except Exception:
            pass
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "method_version": "kpi_iteration_backfill_v1",
            "source_iteration_dir": str(iteration_dir),
            "backfill_reason": "repair_iteration_summary_missing",
        },
        "patch_runs": [],
        "patch_isolation_matrix": {
            "baseline": {
                "patch_id": "baseline_locked",
                "profit_factor": 0.0,
                "net_pnl": 0.0,
                "trade_count": 0,
            },
            "rows": [],
            "rows_sorted_by_pf_delta": [],
            "patches_with_real_pf_gain": [],
            "min_trades_for_stat_evidence": repair_iter.MIN_TRADES_FOR_STAT_EVIDENCE,
        },
        "runtime_target_verification": {},
        "rollout_gates": {
            "definitions": {},
            "decisions": [],
            "recommendation": recommendation,
        },
    }


def _load_or_backfill_summary(iteration_dir: Path) -> dict:
    summary_path = iteration_dir / "repair_iteration_summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    summary = _minimal_backfill_summary(iteration_dir)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return summary


def _backfill_iteration_dir(iteration_dir: Path, force: bool = False) -> dict:
    summary = _load_or_backfill_summary(iteration_dir)
    writes = []
    mapping = {
        "repair_plan.md": repair_iter._render_repair_plan_md(summary),
        "repair_iteration.md": repair_iter._render_repair_iteration_md(summary),
        "repair_diff.md": repair_iter._render_repair_diff_md(summary),
    }
    for filename, content in mapping.items():
        path = iteration_dir / filename
        if force or not path.exists():
            path.write_text(content, encoding="utf-8")
            writes.append(filename)
    repair_iter._enforce_required_artifact_contract(iteration_dir)
    return {
        "dir": str(iteration_dir),
        "written_files": writes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill required repair_iteration artifact contract files."
    )
    parser.add_argument(
        "--reports-dir",
        default=str(REPORTS_BASE_DIR),
        help="Path to reports/paper_runtime_patch_validation",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite markdown contract files even if already present.",
    )
    args = parser.parse_args(argv)

    reports_dir = Path(args.reports_dir).resolve()
    rows = []
    for iteration_dir in sorted(reports_dir.glob("repair_iteration_*")):
        if not iteration_dir.is_dir():
            continue
        rows.append(_backfill_iteration_dir(iteration_dir, force=bool(args.force)))

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reports_dir": str(reports_dir),
        "processed_iterations": len(rows),
        "results": rows,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
