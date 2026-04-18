import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
WF_TUNER = WORKDIR / "scripts" / "wf_entry_tuner.py"


def _majority_count(total_windows: int, ratio: float) -> int:
    total = max(1, int(total_windows))
    r = min(1.0, max(0.0, float(ratio)))
    return max(1, int(math.ceil(total * r)))


def _parse_env_overrides(items):
    out = {}
    for raw in items or []:
        txt = str(raw or "").strip()
        if not txt:
            continue
        if "=" not in txt:
            raise SystemExit(f"Invalid override '{txt}', expected KEY=VALUE")
        key, value = txt.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SystemExit(f"Invalid override key: {txt}")
        out[key] = value
    return out


def _extract_report_path(stdout_text: str) -> Path | None:
    marker = "WF_TUNER_REPORT_JSON="
    for line in (stdout_text or "").splitlines():
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = (WORKDIR / path).resolve()
        return path
    return None


def _run_tuner(
    *,
    label: str,
    windows: int,
    window_min: int,
    max_candidates: int,
    symbols: str,
    market_type: str,
    timeframe: str,
    quality_profile: bool,
    alpha_bootstrap_source_db_url: str,
    alpha_bootstrap_source_db_glob: str,
    majority_ratio: float,
    min_total_trades: int,
    compare_before: bool,
    min_worst_delta_net_pnl: float,
    min_mean_net_pnl: float,
    min_median_profit_factor: float,
    min_worst_window_net_pnl: float,
    base_before_overrides: dict | None = None,
    base_after_overrides: dict | None = None,
) -> dict:
    majority_windows = _majority_count(windows, majority_ratio)
    max_loss_windows = max(0, int(windows) - int(majority_windows))
    max_zero_windows = max(0, int(windows) - int(majority_windows))
    cmd = [
        sys.executable,
        str(WF_TUNER),
        "--windows",
        str(int(windows)),
        "--window-min",
        str(int(window_min)),
        "--max-candidates",
        str(int(max_candidates)),
        "--symbols",
        str(symbols),
        "--market-type",
        str(market_type),
        "--timeframe",
        str(timeframe),
        "--alpha-bootstrap-source-db-url",
        str(alpha_bootstrap_source_db_url),
        "--alpha-bootstrap-source-db-glob",
        str(alpha_bootstrap_source_db_glob),
        "--min-windows-ok",
        str(int(windows)),
        "--min-total-trades",
        str(max(1, int(min_total_trades))),
        "--max-zero-trade-windows",
        str(int(max_zero_windows)),
        "--max-loss-windows",
        str(int(max_loss_windows)),
        "--min-non-negative-windows",
        str(int(majority_windows)),
        "--min-positive-after-windows",
        str(int(majority_windows)),
        "--min-median-profit-factor",
        str(float(min_median_profit_factor)),
        "--min-profit-factor-windows",
        str(int(majority_windows)),
        "--profit-factor-window-threshold",
        "1.0",
        "--min-mean-net-pnl",
        str(float(min_mean_net_pnl)),
        "--min-worst-window-net-pnl",
        str(float(min_worst_window_net_pnl)),
    ]
    if compare_before:
        cmd.extend(
            [
                "--compare-before",
                "--min-positive-delta-windows",
                str(int(majority_windows)),
                "--min-mean-delta-net-pnl",
                "0.0",
                "--min-median-delta-net-pnl",
                "0.0",
                "--min-worst-delta-net-pnl",
                str(float(min_worst_delta_net_pnl)),
            ]
        )
    cmd.append("--quality-profile" if quality_profile else "--no-quality-profile")
    for key, value in sorted((base_before_overrides or {}).items()):
        cmd.extend(["--base-before-env", f"{key}={value}"])
    for key, value in sorted((base_after_overrides or {}).items()):
        cmd.extend(["--base-after-env", f"{key}={value}"])

    started_at = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(
        cmd,
        cwd=str(WORKDIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ended_at = datetime.now(timezone.utc).isoformat()
    report_path = _extract_report_path(proc.stdout)
    report_obj = None
    if report_path is not None and report_path.exists():
        try:
            report_obj = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            report_obj = None
    return {
        "label": label,
        "cmd": cmd,
        "returncode": int(proc.returncode),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "stdout_tail": (proc.stdout or "")[-6000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
        "report_path": str(report_path) if report_path else None,
        "report": report_obj,
        "majority_windows": int(majority_windows),
    }


def _write_env_file(path: Path, overrides: dict) -> None:
    lines = [f"{k}={v}" for k, v in sorted((overrides or {}).items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default="ETHUSDTM,BTCUSDTM,SOLUSDTM,XRPUSDTM")
    parser.add_argument("--market-type", type=str, default="futures")
    parser.add_argument("--timeframe", type=str, default="1")
    parser.add_argument("--quality-profile", dest="quality_profile", action="store_true")
    parser.add_argument("--no-quality-profile", dest="quality_profile", action="store_false")
    parser.set_defaults(quality_profile=False)
    parser.add_argument(
        "--alpha-bootstrap-source-db-url",
        type=str,
        default="sqlite:///tmp/alpha_history_auto_recent.db",
    )
    parser.add_argument(
        "--alpha-bootstrap-source-db-glob",
        type=str,
        default="tmp/alpha_history_auto_recent.db",
    )
    parser.add_argument("--phase1-windows", type=int, default=3)
    parser.add_argument("--phase1-window-min", type=int, default=12)
    parser.add_argument("--phase1-max-candidates", type=int, default=2)
    parser.add_argument("--phase1-min-total-trades", type=int, default=3)
    parser.add_argument("--confirm-windows", type=int, default=6)
    parser.add_argument("--confirm-window-min", type=int, default=16)
    parser.add_argument("--confirm-max-candidates", type=int, default=1)
    parser.add_argument("--confirm-min-total-trades", type=int, default=6)
    parser.add_argument("--majority-ratio", type=float, default=0.67)
    parser.add_argument(
        "--compare-before",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Score windows in AFTER-vs-BEFORE mode and require positive deltas.",
    )
    parser.add_argument(
        "--min-mean-net-pnl",
        type=float,
        default=0.0,
    )
    parser.add_argument(
        "--min-median-profit-factor",
        type=float,
        default=1.0,
    )
    parser.add_argument(
        "--min-worst-window-net-pnl",
        type=float,
        default=-1.2,
    )
    parser.add_argument(
        "--min-worst-delta-net-pnl",
        type=float,
        default=-0.8,
    )
    parser.add_argument(
        "--base-before-env",
        action="append",
        default=[],
        help="Fixed BEFORE env override (KEY=VALUE), repeatable",
    )
    parser.add_argument(
        "--base-after-env",
        action="append",
        default=[],
        help="Fixed AFTER env override (KEY=VALUE), repeatable",
    )
    parser.add_argument(
        "--status-json",
        type=str,
        default="tmp/wf_tuner_pipeline_status.json",
    )
    parser.add_argument(
        "--freeze-json",
        type=str,
        default="tmp/wf_tuner_pipeline_frozen_after_env.json",
    )
    parser.add_argument(
        "--freeze-env",
        type=str,
        default="tmp/wf_tuner_pipeline_frozen_after.env",
    )
    args = parser.parse_args()

    status_path = (WORKDIR / str(args.status_json)).resolve()
    freeze_json_path = (WORKDIR / str(args.freeze_json)).resolve()
    freeze_env_path = (WORKDIR / str(args.freeze_env)).resolve()
    base_before_overrides = _parse_env_overrides(args.base_before_env)
    base_after_overrides = _parse_env_overrides(args.base_after_env)

    phase1 = _run_tuner(
        label="phase1_screen",
        windows=args.phase1_windows,
        window_min=args.phase1_window_min,
        max_candidates=args.phase1_max_candidates,
        symbols=args.symbols,
        market_type=args.market_type,
        timeframe=args.timeframe,
        quality_profile=bool(args.quality_profile),
        alpha_bootstrap_source_db_url=args.alpha_bootstrap_source_db_url,
        alpha_bootstrap_source_db_glob=args.alpha_bootstrap_source_db_glob,
        majority_ratio=args.majority_ratio,
        min_total_trades=args.phase1_min_total_trades,
        compare_before=bool(args.compare_before),
        min_worst_delta_net_pnl=float(args.min_worst_delta_net_pnl),
        min_mean_net_pnl=float(args.min_mean_net_pnl),
        min_median_profit_factor=float(args.min_median_profit_factor),
        min_worst_window_net_pnl=float(args.min_worst_window_net_pnl),
        base_before_overrides=base_before_overrides,
        base_after_overrides=base_after_overrides,
    )

    phase1_report = phase1.get("report") or {}
    phase1_selected = dict((phase1_report.get("selected") or {}))
    phase1_passed = bool(phase1_selected.get("passed"))
    phase1_overrides = dict(phase1_selected.get("overrides") or {})
    phase1_effective_overrides = dict(base_after_overrides)
    phase1_effective_overrides.update(phase1_overrides)

    confirm = None
    confirm_passed = False
    frozen_written = False

    if phase1_passed:
        confirm = _run_tuner(
            label="phase2_confirm",
            windows=args.confirm_windows,
            window_min=args.confirm_window_min,
            max_candidates=args.confirm_max_candidates,
            symbols=args.symbols,
            market_type=args.market_type,
            timeframe=args.timeframe,
            quality_profile=bool(args.quality_profile),
            alpha_bootstrap_source_db_url=args.alpha_bootstrap_source_db_url,
            alpha_bootstrap_source_db_glob=args.alpha_bootstrap_source_db_glob,
            majority_ratio=args.majority_ratio,
            min_total_trades=args.confirm_min_total_trades,
            compare_before=bool(args.compare_before),
            min_worst_delta_net_pnl=float(args.min_worst_delta_net_pnl),
            min_mean_net_pnl=float(args.min_mean_net_pnl),
            min_median_profit_factor=float(args.min_median_profit_factor),
            min_worst_window_net_pnl=float(args.min_worst_window_net_pnl),
            base_before_overrides=base_before_overrides,
            base_after_overrides=phase1_effective_overrides,
        )
        confirm_report = confirm.get("report") or {}
        confirm_selected = dict((confirm_report.get("selected") or {}))
        confirm_passed = bool(confirm_selected.get("passed"))
        if confirm_passed:
            payload = {
                "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                "phase1_report": phase1.get("report_path"),
                "phase2_report": confirm.get("report_path"),
                "overrides": phase1_effective_overrides,
            }
            freeze_json_path.parent.mkdir(parents=True, exist_ok=True)
            freeze_json_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
            )
            freeze_env_path.parent.mkdir(parents=True, exist_ok=True)
            _write_env_file(freeze_env_path, phase1_effective_overrides)
            frozen_written = True

    if not frozen_written:
        try:
            if freeze_json_path.exists():
                freeze_json_path.unlink()
        except Exception:
            pass
        try:
            if freeze_env_path.exists():
                freeze_env_path.unlink()
        except Exception:
            pass

    status = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase1_report_path": phase1.get("report_path"),
        "phase1_returncode": phase1.get("returncode"),
        "phase1_passed": bool(phase1_passed),
        "phase1_selected_id": phase1_selected.get("id"),
        "phase1_selected_overrides": phase1_overrides,
        "phase1_effective_overrides": phase1_effective_overrides,
        "compare_before": bool(args.compare_before),
        "base_before_overrides": base_before_overrides,
        "base_after_overrides": base_after_overrides,
        "confirm_ran": bool(confirm is not None),
        "confirm_report_path": (confirm or {}).get("report_path") if confirm else None,
        "confirm_returncode": (confirm or {}).get("returncode") if confirm else None,
        "confirm_passed": bool(confirm_passed),
        "frozen_written": bool(frozen_written),
        "freeze_json": str(freeze_json_path),
        "freeze_env": str(freeze_env_path),
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, indent=2, ensure_ascii=True), encoding="utf-8")

    print("WF_PIPELINE_DONE")
    print(f"WF_PIPELINE_STATUS_JSON={status_path}")
    print(
        "WF_PIPELINE_RESULT "
        f"phase1_passed={int(bool(phase1_passed))} "
        f"confirm_passed={int(bool(confirm_passed))} "
        f"frozen_written={int(bool(frozen_written))}"
    )
    if phase1.get("report_path"):
        print(f"WF_PIPELINE_PHASE1_REPORT={phase1.get('report_path')}")
    if confirm and confirm.get("report_path"):
        print(f"WF_PIPELINE_PHASE2_REPORT={confirm.get('report_path')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
