import argparse
import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
CONTROLLED_KPI_SCRIPT = WORKDIR / "scripts" / "controlled_kpi_run.py"
RESULTS_DIR = WORKDIR / "results"
ANALYSIS_DIR = WORKDIR / "analysis"
REPORTS_BASE_DIR = WORKDIR / "reports" / "paper_runtime_patch_validation"
REQUIRED_ITERATION_ARTIFACTS = (
    "repair_iteration_summary.json",
    "repair_plan.md",
    "repair_iteration.md",
    "repair_diff.md",
)


TARGET_PROFIT_FACTOR_MIN = 1.0
TARGET_NET_PNL_MIN = 0.0
TARGET_FEE_INVERSION_MAX_SHARE = 0.25
TARGET_GREEN_TO_RED_MAX_SHARE = 0.25
TARGET_REQUIRES_REVIEW_MAX_SHARE = 0.05
MIN_TRADES_FOR_STAT_EVIDENCE = 2


@dataclass
class PatchSpec:
    patch_id: str
    title: str
    rationale: str
    overrides: dict[str, str]


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_file(pattern: str, folder: Path) -> Path:
    matches = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not matches:
        raise FileNotFoundError(f"No files found: pattern={pattern} folder={folder}")
    return matches[-1]


def _latest_after_controlled_report() -> Path:
    candidates = []
    for path in RESULTS_DIR.glob("controlled_kpi_*.json"):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        after = payload.get("after")
        if isinstance(after, dict) and str(after.get("variant") or "") == "after":
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError("No controlled_kpi after reports found")
    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-1]


def _extract_base_overrides(seed_report: dict[str, Any]) -> dict[str, str]:
    params = seed_report.get("params") or {}
    raw = params.get("after_env_overrides") or {}
    if not isinstance(raw, dict):
        raw = {}
    keys = [
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST",
        "ENTRY_SYMBOL_STRATEGY_BLOCKLIST",
        "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST",
    ]
    out = {
        # Keep baseline deterministic and comparable across iterations.
        # Whitelist strictness is evaluated as an isolated patch, not as baseline drift.
        "ALPHA_WHITELIST_ENABLE": "0",
        "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
        "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
    }
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        txt = str(value).strip()
        if txt:
            out[key] = txt
    return out


def _patch_specs_from_scorecard(
    scorecard: dict[str, Any],
    base_overrides: dict[str, str],
) -> list[PatchSpec]:
    _ = scorecard
    positive_allowlist = str(
        base_overrides.get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST") or ""
    ).strip()
    alpha_overrides = {
        "ALPHA_WHITELIST_ENABLE": "1",
        "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
        "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
        "ALPHA_WHITELIST_MIN_EXPECTANCY": "0.0010",
        "ALPHA_WHITELIST_MIN_WINRATE": "0.45",
        "ALPHA_WHITELIST_MIN_TRADES": "10",
    }
    if positive_allowlist:
        alpha_overrides["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] = positive_allowlist

    return [
        PatchSpec(
            patch_id="baseline_locked",
            title="Baseline locked",
            rationale=(
                "Fixed baseline with locked alpha side-bucket controls from "
                "latest run."
            ),
            overrides={},
        ),
        PatchSpec(
            patch_id="cost_efficiency_tight",
            title="CostEfficiency thresholds",
            rationale=(
                "Tighten economic entry floor to reduce "
                "fee/slippage-dominated trades."
            ),
            overrides={
                "ENTRY_MIN_PROFIT_FEE_MULT": "1.35",
                "ENTRY_MIN_NET_USDT": "0.18",
                "ENTRY_MIN_EXPECTED_EDGE_AFTER_FEE": "0.0008",
                "TREND_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0003",
                "MOMENTUM_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0003",
            },
        ),
        PatchSpec(
            patch_id="economic_edge_churn_guard_v1",
            title="Economic edge + churn guard v1",
            rationale=(
                "Target top NO-GO drivers with a focused edge floor and "
                "decision-churn damping from a clean baseline."
            ),
            overrides={
                "ENTRY_MIN_PROFIT_FEE_MULT": "1.40",
                "ENTRY_MIN_NET_USDT": "0.20",
                "ENTRY_MIN_EXPECTED_EDGE_AFTER_FEE": "0.0010",
                "TREND_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0004",
                "MOMENTUM_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0004",
                "DECISION_HYSTERESIS_SCORE": "0.06",
                "ENTRY_MIN_VOTE_DOMINANCE": "0.55",
                "EXECUTION_COOLDOWN_SEC": "10",
                "LOSS_COOLDOWN_SEC": "12",
                "MAX_OPEN_POSITIONS": "1",
            },
        ),
        PatchSpec(
            patch_id="entry_funnel_relax_v2",
            title="EntryFunnel thresholds v2",
            rationale=(
                "Blend relaxed admission with cost guards and tighter "
                "close-drain reliability for promote-grade runtime evidence."
            ),
            overrides={
                "ENTRY_SIGNAL_SCORE_MIN": "0.20",
                "ENTRY_SIGNAL_SCORE_MIN_BUY": "0.23",
                "ENTRY_BUY_MIN_SIGNAL_SCORE": "0.23",
                "ENTRY_MIN_VOTE_DOMINANCE": "0.52",
                "DECISION_HYSTERESIS_SCORE": "0.05",
                "ENTRY_VOLATILITY_MIN": "0.012",
                "ENTRY_BUY_MIN_VOLATILITY": "0.012",
                "ENTRY_MIN_PROFIT_FEE_MULT": "1.35",
                "ENTRY_MIN_NET_USDT": "0.18",
                "ENTRY_MIN_EXPECTED_EDGE_AFTER_FEE": "0.0008",
                "TREND_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0003",
                "MOMENTUM_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0003",
                "MAX_OPEN_POSITIONS": "1",
                "POST_PROMOTION_OBSERVATION_ENABLED": "0",
                "ENTRY_CUTOFF_BEFORE_END_SEC": "90",
                "PAPER_AUTO_CLOSE_POLICY": "profit_or_hard",
                "PAPER_AUTO_CLOSE_SEC": "12",
                "PAPER_AUTO_CLOSE_HARD_SEC": "24",
                "LOSS_COOLDOWN_SEC": "10",
                "EXECUTION_COOLDOWN_SEC": "8",
            },
        ),
        PatchSpec(
            patch_id="alpha_selection_strict",
            title="AlphaSelection thresholds",
            rationale=(
                "Enforce stricter alpha quality gate to keep only "
                "high-confidence positive expectancy buckets."
            ),
            overrides=alpha_overrides,
        ),
        PatchSpec(
            patch_id="alpha_selection_balanced_v2",
            title="AlphaSelection balanced v2",
            rationale=(
                "Balance alpha quality with controlled throughput so trade count "
                "can rise without reopening high-cost weak-edge entries."
            ),
            overrides={
                "ALPHA_WHITELIST_ENABLE": "1",
                "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
                "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
                "ALPHA_WHITELIST_MIN_EXPECTANCY": "0.0006",
                "ALPHA_WHITELIST_MIN_WINRATE": "0.40",
                "ALPHA_WHITELIST_MIN_TRADES": "6",
                "ENTRY_SIGNAL_SCORE_MIN": "0.18",
                "ENTRY_SIGNAL_SCORE_MIN_BUY": "0.20",
                "ENTRY_BUY_MIN_SIGNAL_SCORE": "0.20",
                "ENTRY_MIN_VOTE_DOMINANCE": "0.51",
                "DECISION_HYSTERESIS_SCORE": "0.05",
                "ENTRY_MIN_PROFIT_FEE_MULT": "1.30",
                "ENTRY_MIN_NET_USDT": "0.16",
                "ENTRY_MIN_EXPECTED_EDGE_AFTER_FEE": "0.0007",
                "TREND_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0003",
                "MOMENTUM_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0003",
                "MAX_OPEN_POSITIONS": "1",
                "LOSS_COOLDOWN_SEC": "10",
                "EXECUTION_COOLDOWN_SEC": "8",
                "ENTRY_CUTOFF_BEFORE_END_SEC": "90",
            },
        ),
        PatchSpec(
            patch_id="alpha_selection_balanced_v3_mintrades4",
            title="AlphaSelection balanced v3 mintrades4",
            rationale=(
                "Minimal throughput unlock with unchanged cost and churn controls."
            ),
            overrides={
                "ALPHA_WHITELIST_ENABLE": "1",
                "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
                "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
                "ALPHA_WHITELIST_MIN_EXPECTANCY": "0.0006",
                "ALPHA_WHITELIST_MIN_WINRATE": "0.40",
                "ALPHA_WHITELIST_MIN_TRADES": "4",
                "ENTRY_SIGNAL_SCORE_MIN": "0.18",
                "ENTRY_SIGNAL_SCORE_MIN_BUY": "0.20",
                "ENTRY_BUY_MIN_SIGNAL_SCORE": "0.20",
                "ENTRY_MIN_VOTE_DOMINANCE": "0.51",
                "DECISION_HYSTERESIS_SCORE": "0.05",
                "ENTRY_MIN_PROFIT_FEE_MULT": "1.30",
                "ENTRY_MIN_NET_USDT": "0.16",
                "ENTRY_MIN_EXPECTED_EDGE_AFTER_FEE": "0.0007",
                "TREND_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0003",
                "MOMENTUM_MIXED_EDGE_SAFETY_MARGIN_USDT": "0.0003",
                "MAX_OPEN_POSITIONS": "1",
                "LOSS_COOLDOWN_SEC": "10",
                "EXECUTION_COOLDOWN_SEC": "8",
                "ENTRY_CUTOFF_BEFORE_END_SEC": "90",
            },
        ),
        PatchSpec(
            patch_id="close_shape_fast_exit_v1",
            title="Close shape fast exit v1",
            rationale=(
                "Single close-timing delta to reduce hold-shape degradation "
                "without changing cost or churn controls."
            ),
            overrides={
                "PAPER_AUTO_CLOSE_SEC": "14",
            },
        ),
    ]


def _parse_report_json_path(stdout_text: str) -> Path:
    for line in reversed(stdout_text.splitlines()):
        txt = str(line).strip()
        if txt.startswith("REPORT_JSON="):
            path_txt = txt.split("=", 1)[1].strip()
            path = Path(path_txt)
            if not path.is_absolute():
                path = (WORKDIR / path).resolve()
            return path
    raise RuntimeError("REPORT_JSON line not found in controlled_kpi_run output")


def _parse_entry_admission_contract_json_path(text: str) -> Path | None:
    for line in (text or "").splitlines():
        txt = str(line or "").strip()
        if "ENTRY_ADMISSION_CONTRACT_JSON=" in txt:
            raw = txt.split("ENTRY_ADMISSION_CONTRACT_JSON=", 1)[1].strip()
            if raw:
                path = Path(raw)
                if not path.is_absolute():
                    path = (WORKDIR / path).resolve()
                return path
        if "artifact=" in txt:
            raw = txt.split("artifact=", 1)[1].split()[0].strip()
            if raw:
                path = Path(raw)
                if not path.is_absolute():
                    path = (WORKDIR / path).resolve()
                return path
    return None


def _empty_after_metrics_for_failed_run(
    *,
    process_returncode: int,
    entry_admission_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "db_exists": False,
        "db_path": None,
        "trade_count": 0,
        "net_pnl": 0.0,
        "winrate": 0.0,
        "win_rate": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "expectancy": 0.0,
        "max_drawdown": 0.0,
        "profit_factor": 0.0,
        "gross_profit": 0.0,
        "gross_loss_abs": 0.0,
        "green_to_red_share": None,
        "fee_inversion_share": None,
        "share_ever_profitable": None,
        "exit_reason_distribution": {},
        "time_to_first_MFE": None,
        "time_from_peak_to_close": None,
        "decisions_count": 0,
        "equity_points": 0,
        "symbol_stats": {},
        "event_counts": {},
        "log_health": {"error_count": 0, "warning_count": 0, "sample_errors": []},
        "process_returncode": int(process_returncode),
        "process_returncode_raw": int(process_returncode),
        "shutdown_classification": "entry_admission_contract_fail_closed",
        "entry_admission_contract": entry_admission_contract or {},
    }


def _run_controlled_kpi(
    *,
    patch: PatchSpec,
    base_overrides: dict[str, str],
    symbols: str,
    market_type: str,
    timeframe: str,
    after_min: int,
    paper_auto_close_sec: int,
    equity_snapshot_sec: int,
    alpha_source_db_url: str,
    alpha_source_db_glob: str,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(CONTROLLED_KPI_SCRIPT),
        "--variant-only",
        "after",
        "--after-min",
        str(int(after_min)),
        "--symbols",
        symbols,
        "--market-type",
        market_type,
        "--timeframe",
        timeframe,
        "--paper-auto-open",
        "--paper-auto-close-sec",
        str(int(paper_auto_close_sec)),
        "--equity-snapshot-sec",
        str(int(equity_snapshot_sec)),
        "--quality-profile",
        "--no-alpha-bootstrap-auto-refresh",
        "--alpha-bootstrap-source-db-url",
        alpha_source_db_url,
        "--alpha-bootstrap-source-db-glob",
        alpha_source_db_glob,
    ]

    merged_overrides = dict(base_overrides)
    merged_overrides.update(dict(patch.overrides))
    for key, value in merged_overrides.items():
        cmd.extend(["--after-env", f"{key}={value}"])

    timeout_sec = max(420, int(after_min) * 60 + 300)
    proc = subprocess.run(
        cmd,
        cwd=str(WORKDIR),
        text=True,
        capture_output=True,
        timeout=timeout_sec,
    )
    try:
        report_json_path = _parse_report_json_path(proc.stdout)
    except Exception as exc:
        if proc.returncode != 0:
            contract_path = _parse_entry_admission_contract_json_path(
                f"{proc.stdout}\n{proc.stderr}"
            )
            if contract_path is not None and contract_path.exists():
                contract_payload = _load_json(contract_path)
                contract = contract_payload.get("contract")
                if not isinstance(contract, dict):
                    contract = contract_payload if isinstance(contract_payload, dict) else {}
                after = _empty_after_metrics_for_failed_run(
                    process_returncode=int(proc.returncode),
                    entry_admission_contract=contract,
                )
                report = {
                    "run_id": None,
                    "after": after,
                    "entry_admission_contract": contract,
                    "entry_admission_contract_path": str(contract_path),
                }
                return {
                    "patch_id": patch.patch_id,
                    "title": patch.title,
                    "rationale": patch.rationale,
                    "report_json_path": None,
                    "report": report,
                    "after": after,
                    "subprocess_returncode": int(proc.returncode),
                    "run_error": (
                        "controlled_kpi entry admission contract fail-closed; "
                        f"artifact={contract_path}"
                    ),
                    "stdout_tail": proc.stdout[-4000:],
                    "stderr_tail": proc.stderr[-4000:],
                    "overrides": merged_overrides,
                }
            raise RuntimeError(
                f"Patch run failed ({patch.patch_id}) rc={proc.returncode} "
                f"without REPORT_JSON marker ({type(exc).__name__}).\n"
                f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-4000:]}"
            ) from exc
        raise

    report = _load_json(report_json_path)
    after = report.get("after") or {}
    run_error = None
    if proc.returncode != 0:
        run_error = (
            f"controlled_kpi subprocess rc={proc.returncode}; "
            "using emitted report for evidence"
        )
    return {
        "patch_id": patch.patch_id,
        "title": patch.title,
        "rationale": patch.rationale,
        "report_json_path": str(report_json_path),
        "report": report,
        "after": after,
        "subprocess_returncode": int(proc.returncode),
        "run_error": run_error,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "overrides": merged_overrides,
    }


def _extract_position_close_rows(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists() or db_path.is_dir():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT details FROM logs WHERE event='position_close' ORDER BY rowid ASC"
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        raw = row["details"]
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            continue
        position_raw = payload.get("position")
        position = position_raw if isinstance(position_raw, dict) else {}
        pnl_decompose_raw = position.get("pnl_decompose")
        pnl_decompose = (
            pnl_decompose_raw if isinstance(pnl_decompose_raw, dict) else {}
        )

        realized_net = _safe_float(position.get("realized_net"))
        if realized_net is None:
            realized_net = _safe_float(position.get("realized_pnl"))
        if realized_net is None:
            realized_net = _safe_float(payload.get("realized_pnl"))
        if realized_net is None:
            realized_net = _safe_float(pnl_decompose.get("net_pnl"), 0.0)

        gross_fill_pnl_model = _safe_float(pnl_decompose.get("gross_fill_pnl_model"))
        mfe = _safe_float(position.get("mfe"))
        if mfe is None:
            mfe = _safe_float(position.get("max_unrealized_pnl"))

        lifecycle_state = str(position.get("lifecycle_ownership_state") or "").strip()
        lifecycle_det = position.get("lifecycle_ownership_deterministic")
        exit_reason = str(position.get("exit_reason") or "").strip()
        exit_owner = str(position.get("exit_owner") or "").strip()

        out.append(
            {
                "realized_net": float(realized_net or 0.0),
                "gross_fill_pnl_model": gross_fill_pnl_model,
                "mfe": mfe,
                "lifecycle_state": lifecycle_state,
                "lifecycle_deterministic": bool(lifecycle_det)
                if lifecycle_det is not None
                else None,
                "exit_reason": exit_reason,
                "exit_owner": exit_owner,
            }
        )
    return out


def _runtime_target_verification(after_report: dict[str, Any]) -> dict[str, Any]:
    trade_count = _safe_int(after_report.get("trade_count"), 0)
    profit_factor = _safe_float(after_report.get("profit_factor"), 0.0) or 0.0
    net_pnl = _safe_float(after_report.get("net_pnl"), 0.0) or 0.0

    db_path = Path(str(after_report.get("db_path") or ""))
    close_rows = _extract_position_close_rows(db_path)
    close_count = len(close_rows)

    fee_inversion_count = 0
    green_to_red_count = 0
    requires_review_count = 0
    unclassified_count = 0

    for row in close_rows:
        gross = row.get("gross_fill_pnl_model")
        realized = float(row.get("realized_net") or 0.0)
        mfe = row.get("mfe")
        lifecycle_state = str(row.get("lifecycle_state") or "")
        lifecycle_det = row.get("lifecycle_deterministic")
        exit_reason = str(row.get("exit_reason") or "")
        exit_owner = str(row.get("exit_owner") or "")

        if gross is not None and float(gross) > 0.0 and realized <= 0.0:
            fee_inversion_count += 1
        if mfe is not None and float(mfe) > 0.0 and realized <= 0.0:
            green_to_red_count += 1
        if lifecycle_state == "requires_review" or lifecycle_det is False:
            requires_review_count += 1
        if (
            exit_reason == "close_reason_unclassified"
            or exit_owner == "unclassified_exit_owner"
        ):
            unclassified_count += 1

    denom = float(close_count) if close_count > 0 else None
    fee_inversion_share = (fee_inversion_count / denom) if denom else None
    green_to_red_share = (green_to_red_count / denom) if denom else None
    requires_review_share = (requires_review_count / denom) if denom else None
    unclassified_share = (unclassified_count / denom) if denom else None

    profitability_floor_pass = bool(
        trade_count >= MIN_TRADES_FOR_STAT_EVIDENCE
        and profit_factor >= TARGET_PROFIT_FACTOR_MIN
        and net_pnl >= TARGET_NET_PNL_MIN
    )
    fee_inversion_pass = bool(
        fee_inversion_share is not None
        and fee_inversion_share <= TARGET_FEE_INVERSION_MAX_SHARE
    )
    green_to_red_pass = bool(
        green_to_red_share is not None
        and green_to_red_share <= TARGET_GREEN_TO_RED_MAX_SHARE
    )
    requires_review_pass = bool(
        requires_review_share is not None
        and requires_review_share <= TARGET_REQUIRES_REVIEW_MAX_SHARE
    )

    targets = {
        "profitability_floor": {
            "value": {
                "profit_factor": float(profit_factor),
                "net_pnl": float(net_pnl),
                "trade_count": int(trade_count),
            },
            "threshold": {
                "profit_factor_min": TARGET_PROFIT_FACTOR_MIN,
                "net_pnl_min": TARGET_NET_PNL_MIN,
                "trade_count_min": MIN_TRADES_FOR_STAT_EVIDENCE,
            },
            "pass": profitability_floor_pass,
        },
        "fee_inversion": {
            "value": {
                "count": int(fee_inversion_count),
                "share": fee_inversion_share,
                "close_count": int(close_count),
            },
            "threshold": {"share_max": TARGET_FEE_INVERSION_MAX_SHARE},
            "pass": fee_inversion_pass,
        },
        "green_to_red": {
            "value": {
                "count": int(green_to_red_count),
                "share": green_to_red_share,
                "close_count": int(close_count),
            },
            "threshold": {"share_max": TARGET_GREEN_TO_RED_MAX_SHARE},
            "pass": green_to_red_pass,
        },
        "ownership_requires_review": {
            "value": {
                "count": int(requires_review_count),
                "share": requires_review_share,
                "close_count": int(close_count),
                "unclassified_share": unclassified_share,
            },
            "threshold": {"share_max": TARGET_REQUIRES_REVIEW_MAX_SHARE},
            "pass": requires_review_pass,
        },
    }

    runtime_target_pass = all(bool(target["pass"]) for target in targets.values())
    return {
        "close_count": int(close_count),
        "targets": targets,
        "runtime_target_pass": bool(runtime_target_pass),
    }


def _build_delta_matrix(run_rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = next(
        (r for r in run_rows if r.get("patch_id") == "baseline_locked"),
        None,
    )
    if baseline is None:
        raise RuntimeError("Baseline row missing in patch matrix")

    baseline_after = baseline.get("after") or {}
    baseline_pf = _safe_float(baseline_after.get("profit_factor"), 0.0) or 0.0
    baseline_net = _safe_float(baseline_after.get("net_pnl"), 0.0) or 0.0
    baseline_trades = _safe_int(baseline_after.get("trade_count"), 0)

    rows = []
    for row in run_rows:
        after = row.get("after") or {}
        pf = _safe_float(after.get("profit_factor"), 0.0) or 0.0
        net = _safe_float(after.get("net_pnl"), 0.0) or 0.0
        trades = _safe_int(after.get("trade_count"), 0)
        delta_pf = pf - baseline_pf
        delta_net = net - baseline_net
        delta_trades = trades - baseline_trades
        real_pf_gain = bool(
            row.get("patch_id") != "baseline_locked"
            and delta_pf > 0.05
            and trades
            >= max(MIN_TRADES_FOR_STAT_EVIDENCE, int(baseline_trades * 0.5))
        )
        rows.append(
            {
                "patch_id": row.get("patch_id"),
                "title": row.get("title"),
                "profit_factor": pf,
                "net_pnl": net,
                "trade_count": trades,
                "delta_profit_factor_vs_baseline": delta_pf,
                "delta_net_pnl_vs_baseline": delta_net,
                "delta_trade_count_vs_baseline": delta_trades,
                "real_pf_gain": real_pf_gain,
            }
        )

    real_gain_patches = [r["patch_id"] for r in rows if r.get("real_pf_gain")]
    rows_sorted = sorted(
        rows,
        key=lambda r: float(r["delta_profit_factor_vs_baseline"]),
        reverse=True,
    )

    return {
        "baseline": {
            "patch_id": "baseline_locked",
            "profit_factor": baseline_pf,
            "net_pnl": baseline_net,
            "trade_count": baseline_trades,
        },
        "rows": rows,
        "rows_sorted_by_pf_delta": rows_sorted,
        "patches_with_real_pf_gain": real_gain_patches,
        "min_trades_for_stat_evidence": MIN_TRADES_FOR_STAT_EVIDENCE,
    }


def _rollout_decision(
    *,
    row: dict[str, Any],
    runtime_targets: dict[str, Any],
) -> dict[str, Any]:
    patch_id = str(row.get("patch_id") or "")
    pf_delta = _safe_float(row.get("delta_profit_factor_vs_baseline"), 0.0) or 0.0
    readiness_ok = bool(
        _safe_int((row.get("after") or {}).get("process_returncode"), 0) == 0
        and _safe_int(
            (((row.get("after") or {}).get("log_health") or {}).get("error_count")),
            0,
        )
        == 0
    )
    runtime_pass = bool(runtime_targets.get("runtime_target_pass"))
    real_pf_gain = bool(row.get("real_pf_gain"))

    targets_payload = runtime_targets.get("targets") or {}
    fee_payload = targets_payload.get("fee_inversion") or {}
    green_payload = targets_payload.get("green_to_red") or {}
    review_payload = targets_payload.get("ownership_requires_review") or {}
    fee_value = fee_payload.get("value") or {}
    green_value = green_payload.get("value") or {}
    review_value = review_payload.get("value") or {}

    fee_share = _safe_float(
        fee_value.get("share"),
        None,
    )
    green_red_share = _safe_float(
        green_value.get("share"),
        None,
    )
    review_share = _safe_float(
        review_value.get("share"),
        None,
    )

    rollback_hard_fail = bool(
        (pf_delta < -0.05)
        or (review_share is not None and review_share > 0.20)
        or (green_red_share is not None and green_red_share > 0.60)
        or (fee_share is not None and fee_share > 0.60)
        or (not readiness_ok)
    )

    if patch_id == "baseline_locked":
        action = "hold"
        reasons = ["baseline_reference"]
    elif runtime_pass and real_pf_gain:
        action = "promote"
        reasons = ["runtime_targets_pass", "real_pf_gain_confirmed"]
    elif rollback_hard_fail:
        action = "rollback"
        reasons = ["hard_fail_guard_triggered"]
    else:
        action = "hold"
        reasons = ["runtime_or_profitability_not_confirmed"]

    return {
        "patch_id": patch_id,
        "action": action,
        "reasons": reasons,
        "readiness_ok": readiness_ok,
        "runtime_targets_pass": runtime_pass,
        "real_pf_gain": real_pf_gain,
        "delta_profit_factor_vs_baseline": pf_delta,
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = []
    lines.append("# Repair Plan KPI Iteration")
    lines.append("")
    lines.append("## Matrix")
    lines.append("| Patch | PF | Net PnL | Trades | dPF vs baseline | Real PF gain |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for row in summary["patch_isolation_matrix"]["rows"]:
        lines.append(
            "| "
            f"{row['patch_id']} | "
            f"{row['profit_factor']:.6f} | "
            f"{row['net_pnl']:.6f} | "
            f"{row['trade_count']} | "
            f"{row['delta_profit_factor_vs_baseline']:.6f} | "
            f"{row['real_pf_gain']} |"
        )

    lines.append("")
    lines.append("## Runtime Targets")
    for patch_id, payload in summary["runtime_target_verification"].items():
        lines.append(f"### {patch_id}")
        lines.append(f"- runtime_target_pass: {payload['runtime_target_pass']}")
        for target_name, target in (payload.get("targets") or {}).items():
            lines.append(
                f"- {target_name}: "
                f"pass={target.get('pass')} value={target.get('value')}"
            )

    lines.append("")
    lines.append("## Rollout Gates")
    for decision in summary["rollout_gates"]["decisions"]:
        lines.append(
            f"- {decision['patch_id']}: action={decision['action']} "
            f"reasons={','.join(decision['reasons'])}"
        )

    lines.append("")
    lines.append("## Final Recommendation")
    rec = summary["rollout_gates"]["recommendation"]
    lines.append(f"- patch: {rec.get('patch_id')}")
    lines.append(f"- action: {rec.get('action')}")
    lines.append(f"- reason: {rec.get('reason')}")
    return "\n".join(lines) + "\n"


def _render_repair_plan_md(summary: dict[str, Any]) -> str:
    metadata = summary.get("metadata") or {}
    lines = ["# Repair Plan", ""]
    lines.append("## Inputs")
    lines.append(f"- generated_at: {metadata.get('generated_at')}")
    lines.append(f"- scorecard_path: {metadata.get('scorecard_path')}")
    lines.append(f"- seed_report_path: {metadata.get('seed_report_path')}")
    args = metadata.get("args") or {}
    for key in (
        "symbols",
        "market_type",
        "timeframe",
        "after_min",
        "paper_auto_close_sec",
        "equity_snapshot_sec",
    ):
        if key in args:
            lines.append(f"- {key}: {args.get(key)}")
    lines.append("")
    lines.append("## Candidate Patches")
    for run in summary.get("patch_runs") or []:
        lines.append(
            f"- {run.get('patch_id')}: "
            f"{run.get('title')} | rationale={run.get('rationale')}"
        )
    lines.append("")
    lines.append("## Hard Gate Definitions")
    gate_defs = ((summary.get("rollout_gates") or {}).get("definitions") or {})
    for key, value in gate_defs.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Expected Output Contract")
    for name in REQUIRED_ITERATION_ARTIFACTS:
        lines.append(f"- {name}")
    return "\n".join(lines) + "\n"


def _render_repair_iteration_md(summary: dict[str, Any]) -> str:
    return _render_markdown(summary)


def _render_repair_diff_md(summary: dict[str, Any]) -> str:
    matrix = (summary.get("patch_isolation_matrix") or {}).get("rows") or []
    by_patch = {str(row.get("patch_id") or ""): row for row in matrix}
    baseline = by_patch.get("baseline_locked") or {}
    rec = ((summary.get("rollout_gates") or {}).get("recommendation") or {})
    rec_patch_id = str(rec.get("patch_id") or "")
    recommended = by_patch.get(rec_patch_id) or {}

    def _fmt(value: Any) -> str:
        f = _safe_float(value, None)
        if f is None:
            return "n/a"
        return f"{f:.6f}"

    lines = ["# Repair Diff", ""]
    lines.append(f"- recommendation_patch: {rec_patch_id}")
    lines.append(f"- recommendation_action: {rec.get('action')}")
    lines.append(f"- recommendation_reason: {rec.get('reason')}")
    lines.append("")
    lines.append("## Baseline vs Recommendation")
    lines.append("| Metric | baseline_locked | recommended_patch |")
    lines.append("|---|---:|---:|")
    lines.append(
        f"| profit_factor | {_fmt(baseline.get('profit_factor'))} | "
        f"{_fmt(recommended.get('profit_factor'))} |"
    )
    lines.append(
        f"| net_pnl | {_fmt(baseline.get('net_pnl'))} | "
        f"{_fmt(recommended.get('net_pnl'))} |"
    )
    lines.append(
        f"| trade_count | {int(_safe_int(baseline.get('trade_count'), 0))} | "
        f"{int(_safe_int(recommended.get('trade_count'), 0))} |"
    )
    lines.append(
        f"| delta_profit_factor_vs_baseline | 0.000000 | "
        f"{_fmt(recommended.get('delta_profit_factor_vs_baseline'))} |"
    )
    lines.append(
        f"| delta_net_pnl_vs_baseline | 0.000000 | "
        f"{_fmt(recommended.get('delta_net_pnl_vs_baseline'))} |"
    )
    lines.append("")
    lines.append("## Rollout Decisions")
    for decision in (summary.get("rollout_gates") or {}).get("decisions") or []:
        lines.append(
            f"- {decision.get('patch_id')}: action={decision.get('action')} "
            f"reasons={','.join(decision.get('reasons') or [])}"
        )
    return "\n".join(lines) + "\n"


def _enforce_required_artifact_contract(out_dir: Path) -> None:
    missing = [
        name
        for name in REQUIRED_ITERATION_ARTIFACTS
        if not (out_dir / name).exists()
    ]
    if missing:
        raise RuntimeError(
            "Missing required repair iteration artifacts: "
            + ", ".join(sorted(missing))
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run KPI threshold iteration, patch-isolation matrix, runtime "
            "target verification, and rollout gates."
        )
    )
    parser.add_argument("--after-min", type=int, default=3)
    parser.add_argument("--symbols", default="ETHUSDTM,BTCUSDTM,SOLUSDTM")
    parser.add_argument("--market-type", default="futures")
    parser.add_argument("--timeframe", default="1")
    parser.add_argument("--paper-auto-close-sec", type=int, default=20)
    parser.add_argument("--equity-snapshot-sec", type=int, default=30)
    parser.add_argument("--scorecard-path", default="")
    parser.add_argument(
        "--patch-filter",
        default="",
        help="Optional comma-separated patch_id list for focused matrix runs",
    )
    args = parser.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = REPORTS_BASE_DIR / f"repair_iteration_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    scorecard_path = (
        Path(args.scorecard_path).resolve()
        if str(args.scorecard_path).strip()
        else _latest_file("zol0_profitability_audit_*_scorecard.json", ANALYSIS_DIR)
    )
    scorecard = _load_json(scorecard_path)

    seed_report_path = _latest_after_controlled_report()
    seed_report = _load_json(seed_report_path)
    base_overrides = _extract_base_overrides(seed_report)

    alpha_source_db_url = str(
        (seed_report.get("params") or {}).get("alpha_bootstrap_source_db_url")
        or "sqlite:///tmp/alpha_history_auto_recent.db"
    )
    alpha_source_db_glob = str(
        (seed_report.get("params") or {}).get("alpha_bootstrap_source_db_glob")
        or "tmp/alpha_history_auto_recent.db"
    )

    specs = _patch_specs_from_scorecard(scorecard, base_overrides)
    if str(args.patch_filter or "").strip():
        requested = {
            token.strip()
            for token in str(args.patch_filter).split(",")
            if token.strip()
        }
        if requested:
            specs = [spec for spec in specs if spec.patch_id in requested]
            if not specs:
                raise ValueError(
                    "patch_filter did not match any known patch IDs: "
                    f"{sorted(requested)}"
                )
            if "baseline_locked" not in {spec.patch_id for spec in specs}:
                baseline_spec = next(
                    (
                        spec
                        for spec in _patch_specs_from_scorecard(
                            scorecard, base_overrides
                        )
                        if spec.patch_id == "baseline_locked"
                    ),
                    None,
                )
                if baseline_spec is not None:
                    specs.insert(0, baseline_spec)
    runs = []
    for spec in specs:
        run_row = _run_controlled_kpi(
            patch=spec,
            base_overrides=base_overrides,
            symbols=str(args.symbols),
            market_type=str(args.market_type),
            timeframe=str(args.timeframe),
            after_min=int(args.after_min),
            paper_auto_close_sec=int(args.paper_auto_close_sec),
            equity_snapshot_sec=int(args.equity_snapshot_sec),
            alpha_source_db_url=alpha_source_db_url,
            alpha_source_db_glob=alpha_source_db_glob,
        )
        runs.append(run_row)

    matrix = _build_delta_matrix(runs)

    runtime_target_verification = {}
    matrix_by_patch = {row["patch_id"]: row for row in matrix["rows"]}
    for run_row in runs:
        patch_id = str(run_row.get("patch_id") or "")
        runtime_target_verification[patch_id] = _runtime_target_verification(
            run_row.get("after") or {}
        )
        matrix_by_patch[patch_id]["after"] = run_row.get("after") or {}

    decisions = []
    for patch_id, row in matrix_by_patch.items():
        decision = _rollout_decision(
            row=row,
            runtime_targets=runtime_target_verification.get(patch_id) or {},
        )
        decisions.append(decision)

    promote_candidates = [d for d in decisions if d.get("action") == "promote"]
    if promote_candidates:
        promote_candidates.sort(
            key=lambda d: float(d.get("delta_profit_factor_vs_baseline") or 0.0),
            reverse=True,
        )
        recommendation = {
            "patch_id": promote_candidates[0]["patch_id"],
            "action": "promote",
            "reason": "best_promote_candidate_by_pf_delta_and_runtime_targets",
        }
    else:
        hold_candidates = [
            d
            for d in decisions
            if d.get("action") == "hold"
            and d.get("patch_id") != "baseline_locked"
        ]
        if hold_candidates:
            hold_candidates.sort(
                key=lambda d: float(d.get("delta_profit_factor_vs_baseline") or 0.0),
                reverse=True,
            )
            recommendation = {
                "patch_id": hold_candidates[0]["patch_id"],
                "action": "hold",
                "reason": "no_patch_met_promote_gates",
            }
        else:
            recommendation = {
                "patch_id": "baseline_locked",
                "action": "rollback",
                "reason": "all_patch_candidates_failed_runtime_or_profitability_guards",
            }

    summary = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "method_version": "kpi_iteration_v1",
            "scorecard_path": str(scorecard_path),
            "seed_report_path": str(seed_report_path),
            "base_overrides": base_overrides,
            "args": {
                "after_min": int(args.after_min),
                "symbols": str(args.symbols),
                "market_type": str(args.market_type),
                "timeframe": str(args.timeframe),
                "paper_auto_close_sec": int(args.paper_auto_close_sec),
                "equity_snapshot_sec": int(args.equity_snapshot_sec),
                "alpha_source_db_url": alpha_source_db_url,
                "alpha_source_db_glob": alpha_source_db_glob,
            },
        },
        "patch_runs": [
            {
                "patch_id": r.get("patch_id"),
                "title": r.get("title"),
                "rationale": r.get("rationale"),
                "report_json_path": r.get("report_json_path"),
                "subprocess_returncode": r.get("subprocess_returncode"),
                "run_error": r.get("run_error"),
                "overrides": r.get("overrides"),
                "after": r.get("after"),
            }
            for r in runs
        ],
        "patch_isolation_matrix": matrix,
        "runtime_target_verification": runtime_target_verification,
        "rollout_gates": {
            "definitions": {
                "profitability_floor": (
                    f"profit_factor >= {TARGET_PROFIT_FACTOR_MIN} "
                    f"and net_pnl >= {TARGET_NET_PNL_MIN}"
                ),
                "fee_inversion": (
                    f"fee_inversion_share <= {TARGET_FEE_INVERSION_MAX_SHARE}"
                ),
                "green_to_red": (
                    f"green_to_red_share <= {TARGET_GREEN_TO_RED_MAX_SHARE}"
                ),
                "ownership_requires_review": (
                    "requires_review_share <= "
                    f"{TARGET_REQUIRES_REVIEW_MAX_SHARE}"
                ),
                "real_pf_gain": (
                    "delta_profit_factor_vs_baseline > 0.05 "
                    "with non-collapsed trade_count"
                ),
            },
            "decisions": decisions,
            "recommendation": recommendation,
        },
    }

    json_path = out_dir / "repair_iteration_summary.json"
    md_path = out_dir / "repair_iteration_summary.md"
    repair_plan_md_path = out_dir / "repair_plan.md"
    repair_iteration_md_path = out_dir / "repair_iteration.md"
    repair_diff_md_path = out_dir / "repair_diff.md"
    json_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    # Keep legacy summary markdown for backward compatibility.
    md_path.write_text(_render_markdown(summary), encoding="utf-8")
    repair_plan_md_path.write_text(_render_repair_plan_md(summary), encoding="utf-8")
    repair_iteration_md_path.write_text(
        _render_repair_iteration_md(summary), encoding="utf-8"
    )
    repair_diff_md_path.write_text(_render_repair_diff_md(summary), encoding="utf-8")
    _enforce_required_artifact_contract(out_dir)

    print(f"SUMMARY_JSON={json_path}")
    print(f"SUMMARY_MD={md_path}")
    print(f"REPAIR_PLAN_MD={repair_plan_md_path}")
    print(f"REPAIR_ITERATION_MD={repair_iteration_md_path}")
    print(f"REPAIR_DIFF_MD={repair_diff_md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
