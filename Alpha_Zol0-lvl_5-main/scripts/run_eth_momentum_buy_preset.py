import argparse
import importlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_gate = importlib.import_module("scripts.run_paper_readiness_gate")
ETH_MOMENTUM_BUY_AFTER_ENV_PRESET = _gate.ETH_MOMENTUM_BUY_AFTER_ENV_PRESET
_build_gate_after_env_args = _gate._build_gate_after_env_args
_paper_env = _gate._paper_env
_parse_report_json_path = _gate._parse_report_json_path
_resolve_repo_path = _gate._resolve_repo_path
_safe_float = _gate._safe_float


WORKDIR = ROOT
DIAGNOSTICS_DIR = WORKDIR / "artifacts" / "diagnostics"
CONTROLLED_KPI_SCRIPT = WORKDIR / "scripts" / "controlled_kpi_run.py"


def _eth_momentum_buy_after_env_overrides() -> dict[str, str]:
    missing_source_path = (
        WORKDIR / "tmp" / "alpha_bootstrap_missing_eth_momentum_buy_gate.db"
    ).resolve()
    missing_source_posix = missing_source_path.as_posix()
    return {
        "ALPHA_BOOTSTRAP_SOURCE_DB_URL": f"sqlite:///{missing_source_posix}",
        "ALPHA_BOOTSTRAP_SOURCE_DB_GLOB": missing_source_posix,
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST": "ETHUSDTM:MOMENTUM:buy",
        "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST": "ETHUSDTM:TRENDFOLLOWING:buy",
        "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST": "1",
        "ALPHA_WHITELIST_ENABLE": "0",
        "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
        "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
        "ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS": "0",
    }


def _safe_int(value, default=0):
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _profit_factor_value(value):
    numeric = _safe_float(value, None)
    if numeric is None:
        return str(value) if value not in (None, "") else None
    if math.isinf(numeric):
        return "inf"
    return numeric


def _run_command(
    *,
    after_min: int,
    paper_auto_close_sec: int,
    equity_snapshot_sec: int,
    market_type: str,
    timeframe: int,
    symbols: str,
) -> list[str]:
    cmd = [
        sys.executable,
        str(CONTROLLED_KPI_SCRIPT.resolve()),
        "--variant-only",
        "after",
        "--symbols",
        symbols,
        "--after-min",
        str(int(after_min)),
        "--paper-auto-open",
        "--paper-auto-close-sec",
        str(int(paper_auto_close_sec)),
        "--equity-snapshot-sec",
        str(int(equity_snapshot_sec)),
        "--market-type",
        str(market_type),
        "--timeframe",
        str(int(timeframe)),
        "--quality-profile",
        "--no-alpha-bootstrap-auto-refresh",
    ]
    cmd.extend(
        _build_gate_after_env_args(_eth_momentum_buy_after_env_overrides())
    )
    return cmd


def _completed_run_record(
    *,
    run_index: int,
    report_json: Path,
    stdout_log: Path,
    stderr_log: Path,
) -> dict:
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    after = payload.get("after") or {}
    fallback_run_id = report_json.stem.replace("controlled_kpi_", "")
    run_id = str(payload.get("run_id") or fallback_run_id)
    return {
        "run_index": int(run_index),
        "run_id": run_id,
        "trade_count": _safe_int(after.get("trade_count"), 0),
        "net_pnl": _safe_float(after.get("net_pnl"), 0.0),
        "winrate": _safe_float(after.get("winrate"), 0.0),
        "profit_factor": _profit_factor_value(after.get("profit_factor")),
        "report_json": str(report_json),
        "db_path": str(_resolve_repo_path(after.get("db_path") or "")),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }


def _error_run_record(
    *,
    run_index: int,
    returncode: int,
    stdout_log: Path,
    stderr_log: Path,
    error_code: str,
    error_message: str,
    report_json: Path | None = None,
) -> dict:
    row = {
        "run_index": int(run_index),
        "returncode": int(returncode),
        "error_code": str(error_code),
        "error_message": str(error_message),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }
    if report_json is not None:
        row["report_json"] = str(report_json)
    return row


def _summarize_runs(
    *,
    series_dir: Path,
    args: argparse.Namespace,
    completed_runs: list[dict],
    failed_runs: list[dict],
) -> dict:
    total_net_pnl = sum(
        _safe_float(row.get("net_pnl"), 0.0) or 0.0
        for row in completed_runs
    )
    profitable_runs = sum(
        1
        for row in completed_runs
        if (_safe_float(row.get("net_pnl"), 0.0) or 0.0) > 0.0
    )
    total_trade_count = sum(
        _safe_int(row.get("trade_count"), 0)
        for row in completed_runs
    )
    summary = {
        "preset": ETH_MOMENTUM_BUY_AFTER_ENV_PRESET,
        "series_dir": str(series_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_runs": int(args.runs),
        "completed_run_count": len(completed_runs),
        "failed_run_count": len(failed_runs),
        "profitable_runs": profitable_runs,
        "profitable_run_rate": (
            profitable_runs / len(completed_runs) if completed_runs else 0.0
        ),
        "total_trade_count": total_trade_count,
        "avg_trade_count": (
            total_trade_count / len(completed_runs) if completed_runs else 0.0
        ),
        "total_net_pnl": total_net_pnl,
        "avg_net_pnl": total_net_pnl / len(completed_runs) if completed_runs else 0.0,
        "config": {
            "symbols": args.symbols,
            "after_min": int(args.after_min),
            "paper_auto_close_sec": int(args.paper_auto_close_sec),
            "equity_snapshot_sec": int(args.equity_snapshot_sec),
            "market_type": args.market_type,
            "timeframe": int(args.timeframe),
        },
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
    }
    return summary


def run_series(args: argparse.Namespace) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    series_dir = (
        _resolve_repo_path(args.series_dir)
        if args.series_dir
        else (DIAGNOSTICS_DIR / f"eth_momentum_buy_series_{timestamp}").resolve()
    )
    series_dir.mkdir(parents=True, exist_ok=True)

    completed_runs = []
    failed_runs = []

    for run_index in range(1, int(args.runs) + 1):
        stdout_log = series_dir / f"run_{run_index}.stdout.log"
        stderr_log = series_dir / f"run_{run_index}.stderr.log"
        cmd = _run_command(
            after_min=args.after_min,
            paper_auto_close_sec=args.paper_auto_close_sec,
            equity_snapshot_sec=args.equity_snapshot_sec,
            market_type=args.market_type,
            timeframe=args.timeframe,
            symbols=args.symbols,
        )
        proc = subprocess.run(
            cmd,
            cwd=str(WORKDIR),
            env=_paper_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        stdout_log.write_text(proc.stdout or "", encoding="utf-8")
        stderr_log.write_text(proc.stderr or "", encoding="utf-8")

        if proc.returncode != 0:
            failed_runs.append(
                _error_run_record(
                    run_index=run_index,
                    returncode=proc.returncode,
                    stdout_log=stdout_log,
                    stderr_log=stderr_log,
                    error_code="CONTROLLED_KPI_RUN_FAILED",
                    error_message=f"controlled_kpi_run failed rc={proc.returncode}",
                )
            )
            continue

        try:
            report_json = _parse_report_json_path(proc.stdout or "")
        except Exception as exc:
            failed_runs.append(
                _error_run_record(
                    run_index=run_index,
                    returncode=proc.returncode,
                    stdout_log=stdout_log,
                    stderr_log=stderr_log,
                    error_code="REPORT_JSON_MISSING",
                    error_message=str(exc),
                )
            )
            continue

        if not report_json.exists():
            failed_runs.append(
                _error_run_record(
                    run_index=run_index,
                    returncode=proc.returncode,
                    stdout_log=stdout_log,
                    stderr_log=stderr_log,
                    error_code="REPORT_JSON_NOT_FOUND",
                    error_message=f"report json missing: {report_json}",
                    report_json=report_json,
                )
            )
            continue

        completed_runs.append(
            _completed_run_record(
                run_index=run_index,
                report_json=report_json,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
            )
        )

    summary = _summarize_runs(
        series_dir=series_dir,
        args=args,
        completed_runs=completed_runs,
        failed_runs=failed_runs,
    )
    summary_path = series_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    summary["summary_json"] = str(summary_path)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--symbols", default="ETHUSDTM")
    parser.add_argument("--after-min", type=int, default=16)
    parser.add_argument("--paper-auto-close-sec", type=int, default=20)
    parser.add_argument("--equity-snapshot-sec", type=int, default=10)
    parser.add_argument("--market-type", default="futures")
    parser.add_argument("--timeframe", type=int, default=1)
    parser.add_argument("--series-dir", default="")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if int(args.runs) <= 0:
        raise SystemExit("--runs must be >= 1")
    summary = run_series(args)
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0 if summary.get("completed_run_count", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
