import json
import sys
from pathlib import Path

import pytest

from scripts import run_eth_momentum_buy_preset as runner


def _write_report(path: Path, *, run_id: str, net_pnl: float, trade_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "after": {
                    "trade_count": trade_count,
                    "net_pnl": net_pnl,
                    "winrate": 1.0 if net_pnl > 0 else 0.0,
                    "profit_factor": float("inf") if net_pnl > 0 else 0.0,
                    "db_path": str(path.with_suffix(".db")),
                },
            }
        ),
        encoding="utf-8",
    )
    path.with_suffix(".db").write_text("db", encoding="utf-8")


class _Proc:
    def __init__(self, *, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_command_uses_eth_preset_after_env_args(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "WORKDIR", tmp_path)
    monkeypatch.setattr(
        runner,
        "CONTROLLED_KPI_SCRIPT",
        tmp_path / "scripts" / "controlled_kpi_run.py",
    )

    cmd = runner._run_command(
        after_min=16,
        paper_auto_close_sec=10,
        equity_snapshot_sec=10,
        market_type="futures",
        timeframe=1,
        symbols="ETHUSDTM",
    )

    after_env_values = [
        cmd[idx + 1]
        for idx, token in enumerate(cmd)
        if token == "--after-env" and idx + 1 < len(cmd)
    ]
    missing_source_posix = (
        tmp_path / "tmp" / "alpha_bootstrap_missing_eth_momentum_buy_gate.db"
    ).resolve().as_posix()

    assert cmd[:4] == [
        sys.executable,
        str((tmp_path / "scripts" / "controlled_kpi_run.py").resolve()),
        "--variant-only",
        "after",
    ]
    assert (
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST=ETHUSDTM:MOMENTUM:buy"
        in after_env_values
    )
    assert (
        "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST=ETHUSDTM:TRENDFOLLOWING:buy"
        in after_env_values
    )
    assert "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST=1" in after_env_values
    assert (
        f"ALPHA_BOOTSTRAP_SOURCE_DB_URL=sqlite:///{missing_source_posix}"
        in after_env_values
    )


def test_run_series_writes_summary_for_completed_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "WORKDIR", tmp_path)
    monkeypatch.setattr(
        runner,
        "DIAGNOSTICS_DIR",
        tmp_path / "artifacts" / "diagnostics",
    )
    monkeypatch.setattr(
        runner,
        "CONTROLLED_KPI_SCRIPT",
        tmp_path / "scripts" / "controlled_kpi_run.py",
    )

    report_one = tmp_path / "results" / "controlled_kpi_20260419_150001.json"
    report_two = tmp_path / "results" / "controlled_kpi_20260419_150002.json"
    _write_report(report_one, run_id="20260419_150001", net_pnl=0.5, trade_count=1)
    _write_report(report_two, run_id="20260419_150002", net_pnl=-0.1, trade_count=2)

    responses = iter(
        [
            _Proc(stdout=f"REPORT_JSON={report_one}\n"),
            _Proc(stdout=f"REPORT_JSON={report_two}\n"),
        ]
    )

    def fake_run(cmd, cwd, env, capture_output, text, check):
        return next(responses)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    summary = runner.run_series(
        runner.build_parser().parse_args(
            ["--runs", "2", "--series-dir", str(tmp_path / "series")]
        )
    )

    assert summary["completed_run_count"] == 2
    assert summary["failed_run_count"] == 0
    assert summary["profitable_runs"] == 1
    assert summary["total_trade_count"] == 3
    assert summary["total_net_pnl"] == pytest.approx(0.4)
    assert Path(summary["summary_json"]).exists()
    payload = json.loads(Path(summary["summary_json"]).read_text(encoding="utf-8"))
    assert payload["completed_runs"][0]["profit_factor"] == "inf"
    assert payload["completed_runs"][1]["trade_count"] == 2


def test_run_series_records_failures_without_report_json(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "WORKDIR", tmp_path)
    monkeypatch.setattr(
        runner,
        "DIAGNOSTICS_DIR",
        tmp_path / "artifacts" / "diagnostics",
    )
    monkeypatch.setattr(
        runner,
        "CONTROLLED_KPI_SCRIPT",
        tmp_path / "scripts" / "controlled_kpi_run.py",
    )

    responses = iter(
        [
            _Proc(returncode=2, stdout="", stderr="boom"),
            _Proc(returncode=0, stdout="no report marker\n", stderr=""),
        ]
    )

    def fake_run(cmd, cwd, env, capture_output, text, check):
        return next(responses)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    summary = runner.run_series(
        runner.build_parser().parse_args(
            ["--runs", "2", "--series-dir", str(tmp_path / "series_fail")]
        )
    )

    assert summary["completed_run_count"] == 0
    assert summary["failed_run_count"] == 2
    assert summary["failed_runs"][0]["error_code"] == "CONTROLLED_KPI_RUN_FAILED"
    assert summary["failed_runs"][1]["error_code"] == "REPORT_JSON_MISSING"
