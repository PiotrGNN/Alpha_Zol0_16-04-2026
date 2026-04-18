"""
alpha_relaxation_kpi_validation.py
====================================
PAPER-only, KuCoin-only.
Reads the most recent controlled_kpi_*.json result (or a path passed via
--kpi-report) and the alpha-bootstrap report JSON, then evaluates the
alpha-relaxation pass/fail criteria.

Validation criteria (PASS = all green):
  - trade_count_after >= 10
  - pairs_selected >= 3
  - conversion_rate >= 3%
  - profit_factor > 1.2 (only evaluated when trade_count >= 6)

Failure criteria (detected automatically):
  - still only 1 pair selected
  - trade_count < 6
  - PF high but sample too small (trade_count < 6 and PF > 2)

Outputs:
  reports/alpha_relaxation_validation_<ts>.json

Usage:
  python scripts/alpha_relaxation_kpi_validation.py
  python scripts/alpha_relaxation_kpi_validation.py \
      --kpi-report results/controlled_kpi_20260408_XXXXXX.json \
      --bootstrap-report tmp/alpha_history_auto_recent_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKDIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = WORKDIR / "results"
REPORTS_DIR = WORKDIR / "reports"
TMP_DIR = WORKDIR / "tmp"

# ── Validation thresholds ────────────────────────────────────────────────────
CRIT_TRADE_COUNT_MIN = 10
CRIT_PAIRS_SELECTED_MIN = 3
CRIT_CONVERSION_RATE_MIN = 0.03  # 3 %
CRIT_PROFIT_FACTOR_MIN = 1.2
FAIL_TRADE_COUNT_FLOOR = 6         # below this → unconditional FAIL
FAIL_SINGLETON_PAIR = 1            # still 1 pair selected → FAIL
SMALL_SAMPLE_PF_THRESHOLD = 2.0    # PF considered "artificially high" when n < 6


def _find_latest_kpi_report() -> Path | None:
    candidates = sorted(
        RESULTS_DIR.glob("controlled_kpi_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for c in candidates:
        # Skip files that are clearly too old / not JSON mappings
        try:
            with c.open(encoding="utf-8") as fh:
                obj = json.load(fh)
            if isinstance(obj, dict) and "run_id" in obj:
                return c
        except Exception:
            continue
    return None


def _find_latest_bootstrap_report() -> Path | None:
    candidates = [
        TMP_DIR / "alpha_history_auto_recent_report.json",
        TMP_DIR / "alpha_history_auto_recent.json",
    ]
    candidates += sorted(
        TMP_DIR.glob("alpha_history_*report*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for c in candidates:
        if c.exists():
            return c
    return None


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _compute_entry_conversion_rate(
    trade_count: int, decisions_count: int
) -> float | None:
    if decisions_count <= 0:
        return None
    return trade_count / decisions_count


def _evaluate(
    trade_count: int,
    pairs_selected: int,
    conversion_rate: float | None,
    profit_factor: float,
) -> dict:
    """Return per-criterion pass/fail + overall verdict."""
    results: dict[str, dict] = {}

    # 1. trade_count
    results["trade_count"] = {
        "value": trade_count,
        "threshold": f">= {CRIT_TRADE_COUNT_MIN}",
        "pass": trade_count >= CRIT_TRADE_COUNT_MIN,
    }

    # 2. pairs_selected
    results["pairs_selected"] = {
        "value": pairs_selected,
        "threshold": f">= {CRIT_PAIRS_SELECTED_MIN}",
        "pass": pairs_selected >= CRIT_PAIRS_SELECTED_MIN,
    }

    # 3. conversion_rate
    if conversion_rate is not None:
        results["conversion_rate"] = {
            "value": round(conversion_rate, 5),
            "value_pct": round(conversion_rate * 100, 3),
            "threshold": f">= {CRIT_CONVERSION_RATE_MIN * 100:.1f}%",
            "pass": conversion_rate >= CRIT_CONVERSION_RATE_MIN,
        }
    else:
        results["conversion_rate"] = {
            "value": None,
            "threshold": f">= {CRIT_CONVERSION_RATE_MIN * 100:.1f}%",
            "pass": False,
            "note": "decisions_count=0; cannot compute",
        }

    # 4. profit_factor (only evaluated when sample is large enough)
    pf_evaluated = trade_count >= FAIL_TRADE_COUNT_FLOOR
    results["profit_factor"] = {
        "value": profit_factor,
        "threshold": f"> {CRIT_PROFIT_FACTOR_MIN}",
        "pass": profit_factor > CRIT_PROFIT_FACTOR_MIN if pf_evaluated else None,
        "evaluated": pf_evaluated,
        "note": (
            None
            if pf_evaluated
            else (
                f"sample too small"
                f" (trade_count={trade_count} < {FAIL_TRADE_COUNT_FLOOR})"
            )
        ),
    }

    # Failure modes
    failure_flags: list[str] = []
    if pairs_selected <= FAIL_SINGLETON_PAIR:
        failure_flags.append("still_only_1_pair_selected")
    if trade_count < FAIL_TRADE_COUNT_FLOOR:
        failure_flags.append(f"trade_count_below_floor_{FAIL_TRADE_COUNT_FLOOR}")
    if (
        trade_count < FAIL_TRADE_COUNT_FLOOR
        and profit_factor > SMALL_SAMPLE_PF_THRESHOLD
    ):
        failure_flags.append("pf_high_but_sample_too_small")

    all_pass = all(
        v["pass"]
        for v in results.values()
        if v.get("pass") is not None
    )
    hard_fail = bool(failure_flags)

    if hard_fail:
        verdict = "FAIL"
    elif all_pass:
        verdict = "PASS"
    else:
        failing = [k for k, v in results.items() if v.get("pass") is False]
        verdict = f"PARTIAL_FAIL({','.join(failing)})"

    return {
        "criteria": results,
        "failure_flags": failure_flags,
        "verdict": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate alpha relaxation PAPER KPI validation"
    )
    parser.add_argument(
        "--kpi-report",
        type=str,
        default="",
        help="Path to controlled_kpi_*.json; defaults to most recent in results/",
    )
    parser.add_argument(
        "--bootstrap-report",
        type=str,
        default="",
        help="Path to alpha bootstrap report JSON",
    )
    parser.add_argument(
        "--force-bootstrap-report",
        action="store_true",
        default=False,
        help=(
            "When set, always use the explicit --bootstrap-report file "
            "instead of the one embedded in the KPI result JSON."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="reports",
        help="Directory to write the validation report (workspace-relative)",
    )
    args = parser.parse_args()

    # ── Locate KPI report ───────────────────────────────────────────────────
    if args.kpi_report.strip():
        kpi_path = (WORKDIR / args.kpi_report.strip()).resolve()
    else:
        kpi_path = _find_latest_kpi_report()
    if kpi_path is None or not kpi_path.exists():
        print(
            "ERROR: No controlled_kpi result JSON found. "
            "Run controlled_kpi_run.py first.",
            file=sys.stderr,
        )
        return 1

    with kpi_path.open(encoding="utf-8") as fh:
        kpi = json.load(fh)

    # ── Locate bootstrap report ─────────────────────────────────────────────
    if args.bootstrap_report.strip():
        bs_path = (WORKDIR / args.bootstrap_report.strip()).resolve()
    else:
        # Try to resolve from kpi report itself
        bs_path_from_kpi = None
        try:
            alpha_refresh = kpi.get("alpha_bootstrap_refresh") or {}
            built_path_str = (alpha_refresh.get("report") or {}).get(
                "output"
            ) or ""
            if built_path_str:
                bs_path_from_kpi = Path(built_path_str).with_suffix(
                    ""
                ).with_suffix(".json")
        except Exception:
            pass
        bs_path = bs_path_from_kpi or _find_latest_bootstrap_report()

    bootstrap_report: dict = {}
    if bs_path and bs_path.exists():
        try:
            with bs_path.open(encoding="utf-8") as fh:
                bootstrap_report = json.load(fh)
        except Exception as exc:
            print(f"WARNING: could not read bootstrap report: {exc}", file=sys.stderr)

    # ── Extract bootstrap telemetry ─────────────────────────────────────────
    # Prefer data from the kpi report's embedded bootstrap refresh block,
    # UNLESS --force-bootstrap-report was given.
    alpha_refresh = kpi.get("alpha_bootstrap_refresh") or {}
    embedded_report = alpha_refresh.get("report") or {}
    if args.force_bootstrap_report and bootstrap_report:
        refresh_report = bootstrap_report
    else:
        refresh_report = embedded_report or bootstrap_report

    pairs_total = _safe_int(refresh_report.get("pairs_total"), 0)
    pairs_selected = _safe_int(refresh_report.get("pairs_selected"), 0)
    pairs_rejected_per_rule = refresh_report.get("pairs_rejected_per_rule") or {}
    fallback_used = bool(refresh_report.get("fallback_used"))
    rows_inserted = _safe_int(refresh_report.get("rows_inserted"), 0)

    # Thresholds actually used
    thresholds_used = {
        "min_pair_trades": _safe_int(refresh_report.get("min_pair_trades"), -1),
        "min_pair_winrate": _safe_float(refresh_report.get("min_pair_winrate"), -1),
        "min_pair_expectancy": _safe_float(
            refresh_report.get("min_pair_expectancy"), -999
        ),
        "fallback_top_pairs": _safe_int(
            refresh_report.get("fallback_top_pairs"), -1
        ),
    }

    # Fall back to params block when embedded report lacks them
    if thresholds_used["min_pair_trades"] < 0:
        params = kpi.get("params") or {}
        thresholds_used.update(
            {
                "min_pair_trades": _safe_int(
                    params.get("alpha_bootstrap_build_min_pair_trades"), 5
                ),
                "min_pair_winrate": _safe_float(
                    params.get("alpha_bootstrap_build_min_pair_winrate"), 0.45
                ),
                "min_pair_expectancy": _safe_float(
                    params.get("alpha_bootstrap_build_min_pair_expectancy"), 0.0
                ),
                "fallback_top_pairs": _safe_int(
                    params.get("alpha_bootstrap_build_fallback_top_pairs"), 0
                ),
            }
        )

    # Selected pair names (for diagnostics)
    pair_stats_top = refresh_report.get("pair_stats_top") or []
    selected_pairs = [
        {
            "symbol": r.get("symbol"),
            "strategy": r.get("strategy"),
            "trade_count": r.get("trade_count"),
            "winrate": r.get("winrate"),
            "expectancy": r.get("expectancy"),
        }
        for r in pair_stats_top
        if isinstance(r, dict) and bool(r.get("selected"))
    ]

    # ── Extract variant metrics ─────────────────────────────────────────────
    # Use "after" variant if present, else "before"
    variant_data = kpi.get("after") or kpi.get("before") or {}
    variant_name = variant_data.get("variant", "unknown")
    trade_count = _safe_int(variant_data.get("trade_count"), 0)
    decisions_count = _safe_int(variant_data.get("decisions_count"), 0)
    profit_factor = _safe_float(variant_data.get("profit_factor"), 0.0)
    net_pnl = _safe_float(variant_data.get("net_pnl"), 0.0)
    winrate = _safe_float(variant_data.get("winrate"), 0.0)
    max_drawdown = _safe_float(variant_data.get("max_drawdown"), 0.0)

    # entry_conversion_rate telemetry
    conversion_rate = _compute_entry_conversion_rate(trade_count, decisions_count)

    # ── Evaluate KPIs ──────────────────────────────────────────────────────
    evaluation = _evaluate(
        trade_count=trade_count,
        pairs_selected=pairs_selected,
        conversion_rate=conversion_rate,
        profit_factor=profit_factor,
    )

    # ── Build output report ─────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "report_type": "alpha_relaxation_kpi_validation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": kpi.get("run_id", "unknown"),
        "kpi_report_path": str(kpi_path),
        "bootstrap_report_path": str(bs_path) if bs_path else None,
        "constraints": {
            "exchange": "KuCoin",
            "mode": "PAPER_ONLY",
            "strategy_mutation": False,
            "exit_logic_changed": False,
        },
        "alpha_bootstrap_telemetry": {
            "pairs_total": pairs_total,
            "pairs_selected": pairs_selected,
            "pairs_rejected_per_rule": pairs_rejected_per_rule,
            "fallback_used": fallback_used,
            "rows_inserted": rows_inserted,
            "thresholds_used": thresholds_used,
            "selected_pairs": selected_pairs,
        },
        "variant_metrics": {
            "variant": variant_name,
            "trade_count": trade_count,
            "decisions_count": decisions_count,
            "entry_conversion_rate": conversion_rate,
            "entry_conversion_rate_pct": (
                round(conversion_rate * 100, 3)
                if conversion_rate is not None
                else None
            ),
            "profit_factor": profit_factor,
            "net_pnl": net_pnl,
            "winrate": winrate,
            "max_drawdown": max_drawdown,
        },
        "evaluation": evaluation,
        "relaxation_patch": {
            "min_pair_trades": {"before": 5, "after": 3},
            "min_pair_winrate": {"before": 0.45, "after": 0.40},
            "min_pair_expectancy": {"before": 0.0, "after": -0.0005},
            "fallback_top_pairs": {"before": 0, "after": 3},
        },
    }

    # ── Write output ────────────────────────────────────────────────────────
    out_dir = (WORKDIR / str(args.out_dir or "reports").strip()).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"alpha_relaxation_validation_{ts}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=True)

    # ── Print summary ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"ALPHA RELAXATION KPI VALIDATION — {ts}")
    print(f"{'='*60}")
    print(f"  KPI source   : {kpi_path.name}")
    print(f"  Run ID       : {kpi.get('run_id', 'unknown')}")
    print(f"  Variant      : {variant_name}")
    print()
    print("[Bootstrap telemetry]")
    print(f"  pairs_total        = {pairs_total}")
    print(f"  pairs_selected     = {pairs_selected}")
    print(f"  fallback_used      = {fallback_used}")
    print(f"  rows_inserted      = {rows_inserted}")
    if pairs_rejected_per_rule:
        for rule, cnt in pairs_rejected_per_rule.items():
            print(f"  {rule:30s} = {cnt}")
    print(f"  thresholds_used    = {thresholds_used}")
    print()
    print("[Variant metrics]")
    print(f"  trade_count        = {trade_count}")
    print(f"  decisions_count    = {decisions_count}")
    cvr_str = (
        f"{conversion_rate * 100:.2f}%"
        if conversion_rate is not None
        else "n/a"
    )
    print(f"  conversion_rate    = {cvr_str}")
    print(f"  profit_factor      = {profit_factor:.4f}")
    print(f"  net_pnl            = {net_pnl:.6f}")
    print(f"  winrate            = {winrate:.4f}")
    print()
    print("[Criteria]")
    for name, crit in evaluation["criteria"].items():
        status = (
            "PASS" if crit.get("pass") is True
            else ("SKIP" if crit.get("pass") is None else "FAIL")
        )
        val = crit.get("value_pct", crit.get("value"))
        thr = crit.get("threshold", "")
        note = crit.get("note", "")
        note_str = f"  [{note}]" if note else ""
        print(f"  [{status}] {name}: {val} (threshold: {thr}){note_str}")
    if evaluation["failure_flags"]:
        print()
        print("[Failure flags]")
        for flag in evaluation["failure_flags"]:
            print(f"  ! {flag}")
    print()
    print(f"VERDICT: {evaluation['verdict']}")
    print(f"\nReport written: {out_path}")
    print(f"{'='*60}\n")

    return 0 if evaluation["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
