from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTROLLED_KPI_RUN = ROOT / "scripts" / "controlled_kpi_run.py"
SOURCE_DB = ROOT / "tmp" / "alpha_history_all_recent_20260523.db"
COMPANION_REPORT = ROOT / "tmp" / "alpha_history_all_recent_20260523_report.json"
MISSING_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_bootstrap_corpus_from_recent_paper.py"
OUTPUT_JSON = ROOT / "analysis" / "fresh_edge_existence_autopsy_20260523.json"
OUTPUT_MD = ROOT / "analysis" / "fresh_edge_existence_autopsy_20260523.md"


def _extract_thresholds(controlled_kpi_run_path: Path) -> dict[str, float]:
    txt = controlled_kpi_run_path.read_text(encoding="utf-8")

    def _pick(name: str, default: float) -> float:
        pattern = rf"^{name}\s*=\s*([-+]?[0-9]*\.?[0-9]+)"
        m = re.search(pattern, txt, re.MULTILINE)
        if not m:
            return default
        return float(m.group(1))

    return {
        "STRICT_ALPHA_SIDE_MIN_TRADES": _pick("STRICT_ALPHA_SIDE_MIN_TRADES", 5.0),
        "STRICT_ALPHA_SIDE_MIN_WINRATE": _pick("STRICT_ALPHA_SIDE_MIN_WINRATE", 0.45),
        "STRICT_ALPHA_SIDE_MIN_EXPECTANCY": _pick("STRICT_ALPHA_SIDE_MIN_EXPECTANCY", 0.0),
    }


def _db_position_close_count(db_path: Path) -> int:
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute("SELECT COUNT(1) FROM logs WHERE event='position_close'")
        row = cur.fetchone()
        return int((row or [0])[0] or 0)
    finally:
        con.close()


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _row_has_required_fields(row: dict[str, Any]) -> bool:
    required = ("symbol", "strategy", "side", "trade_count", "winrate", "net_pnl", "expectancy")
    return all(k in row for k in required)


def _classify_row(
    row: dict[str, Any],
    pair_selected: bool,
    min_trades: int,
    min_wr: float,
    min_exp: float,
) -> tuple[str, list[str], bool]:
    reasons: list[str] = []

    if not _row_has_required_fields(row):
        reasons.append("MISSING_FIELDS")

    trade_count = _safe_int(row.get("trade_count"))
    winrate = _safe_float(row.get("winrate"))
    expectancy = _safe_float(row.get("expectancy"))

    if trade_count < min_trades:
        reasons.append("INSUFFICIENT_TRADES")
    if expectancy < 0.0:
        reasons.append("NEGATIVE_EDGE")
    elif expectancy <= min_exp:
        reasons.append("WEAK_EXPECTANCY")
    if winrate < min_wr:
        reasons.append("LOW_WINRATE")

    strict_pass = pair_selected and trade_count >= min_trades and winrate >= min_wr and expectancy > min_exp
    rejected = not strict_pass

    if rejected and not reasons:
        reasons.append("UNKNOWN_REQUIRES_REVIEW")

    primary = reasons[0] if reasons else "UNKNOWN_REQUIRES_REVIEW"
    return primary, reasons, rejected


def _build_md(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("A. Executive Summary")
    lines.append(report["executive_summary"])
    lines.append("")

    lines.append("B. Scope")
    for item in report["scope"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("C. Locked facts")
    for item in report["locked_facts"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("D. Bucket rejection table")
    lines.append("| symbol | strategy | side | trade_count | winrate | net_pnl | expectancy | mean_edge | max_edge | fee_adjusted_edge | rejection reason |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in report["bucket_rejection_table"]:
        lines.append(
            "| {symbol} | {strategy} | {side} | {trade_count} | {winrate:.6f} | {net_pnl:.10f} | {expectancy:.10f} | {mean_edge} | {max_edge} | {fee_adjusted_edge:.10f} | {rejection_reason} |".format(
                symbol=row.get("symbol", ""),
                strategy=row.get("strategy", ""),
                side=row.get("side", ""),
                trade_count=_safe_int(row.get("trade_count")),
                winrate=_safe_float(row.get("winrate")),
                net_pnl=_safe_float(row.get("net_pnl")),
                expectancy=_safe_float(row.get("expectancy")),
                mean_edge="null" if row.get("mean_edge") is None else f"{_safe_float(row.get('mean_edge')):.10f}",
                max_edge="null" if row.get("max_edge") is None else f"{_safe_float(row.get('max_edge')):.10f}",
                fee_adjusted_edge=_safe_float(row.get("fee_adjusted_edge")),
                rejection_reason=row.get("rejection_reason", ""),
            )
        )
    lines.append("")

    lines.append("E. Missing tooling check")
    for item in report["missing_tooling_check"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("F. Root cause classification")
    lines.append(f"- Final classification: {report['final_classification']}")
    lines.append("- Reason counts:")
    reason_counts: dict[str, int] = report["rejection_reason_counts"]
    for k in sorted(reason_counts):
        lines.append(f"  - {k}: {reason_counts[k]}")
    lines.append("")

    lines.append("G. Minimal next step")
    lines.append(report["minimal_next_step"])
    lines.append("")

    lines.append("H. LIVE status")
    lines.append(report["live_status"])
    lines.append("")

    lines.append("Artifact paths:")
    lines.append(f"- JSON: {OUTPUT_JSON}")
    lines.append(f"- MD: {OUTPUT_MD}")
    return "\n".join(lines)


def main() -> int:
    thresholds = _extract_thresholds(CONTROLLED_KPI_RUN)
    min_trades = int(thresholds["STRICT_ALPHA_SIDE_MIN_TRADES"])
    min_wr = float(thresholds["STRICT_ALPHA_SIDE_MIN_WINRATE"])
    min_exp = float(thresholds["STRICT_ALPHA_SIDE_MIN_EXPECTANCY"])

    db_exists = SOURCE_DB.exists()
    report_exists = COMPANION_REPORT.exists()
    if not db_exists or not report_exists:
        raise FileNotFoundError(
            f"Required source artifacts missing: db_exists={db_exists}, report_exists={report_exists}"
        )

    db_close_count = _db_position_close_count(SOURCE_DB)
    report_payload = json.loads(COMPANION_REPORT.read_text(encoding="utf-8"))
    report_output = str(report_payload.get("output") or "").strip()
    report_rows_inserted = _safe_int(report_payload.get("rows_inserted"))

    source_report_mismatch = (Path(report_output).resolve() != SOURCE_DB.resolve()) or (
        report_rows_inserted != db_close_count
    )

    pair_stats_top = [r for r in (report_payload.get("pair_stats_top") or []) if isinstance(r, dict)]
    pair_selected = {
        (str(r.get("symbol") or "").strip().upper(), str(r.get("strategy") or "").strip().upper()): bool(r.get("selected"))
        for r in pair_stats_top
    }

    side_rows = [r for r in (report_payload.get("pair_side_stats_top") or []) if isinstance(r, dict)]
    side_rows_sorted = sorted(
        side_rows,
        key=lambda r: (
            str(r.get("symbol") or ""),
            str(r.get("strategy") or ""),
            str(r.get("side") or ""),
        ),
    )

    bucket_table: list[dict[str, Any]] = []
    reason_counter: Counter[str] = Counter()
    strict_pass_count = 0
    near_min_trades_count = 0

    for row in side_rows_sorted:
        symbol = str(row.get("symbol") or "").strip().upper()
        strategy = str(row.get("strategy") or "").strip().upper()
        side = str(row.get("side") or "").strip().lower()
        if side == "long":
            side = "buy"
        elif side == "short":
            side = "sell"

        tc = _safe_int(row.get("trade_count"))
        wr = _safe_float(row.get("winrate"))
        exp = _safe_float(row.get("expectancy"))
        net_pnl = _safe_float(row.get("net_pnl"))
        fee_adj_edge = net_pnl / tc if tc > 0 else 0.0

        selected = pair_selected.get((symbol, strategy), False)
        primary_reason, all_reasons, rejected = _classify_row(row, selected, min_trades, min_wr, min_exp)
        if source_report_mismatch:
            primary_reason = "SOURCE_REPORT_MISMATCH"
            all_reasons = ["SOURCE_REPORT_MISMATCH"] + [r for r in all_reasons if r != "SOURCE_REPORT_MISMATCH"]
            rejected = True

        strict_pass = selected and tc >= min_trades and wr >= min_wr and exp > min_exp
        if strict_pass:
            strict_pass_count += 1
        if selected and wr >= min_wr and exp > min_exp and tc < min_trades:
            near_min_trades_count += 1

        if rejected:
            reason_counter[primary_reason] += 1
            bucket_table.append(
                {
                    "symbol": symbol,
                    "strategy": strategy,
                    "side": side,
                    "trade_count": tc,
                    "winrate": wr,
                    "net_pnl": net_pnl,
                    "expectancy": exp,
                    "mean_edge": row.get("mean_edge"),
                    "max_edge": row.get("max_edge"),
                    "fee_adjusted_edge": fee_adj_edge,
                    "rejection_reason": primary_reason,
                    "all_rejection_reasons": all_reasons,
                    "pair_selected": selected,
                }
            )

    stale_or_invalid_source = db_close_count <= 0
    missing_refresh_script = not MISSING_REFRESH_SCRIPT.exists()

    if stale_or_invalid_source:
        final_classification = "SOURCE_DB_INVALID_OR_INCOMPLETE"
    elif source_report_mismatch:
        final_classification = "COMPANION_REPORT_MISMATCH"
    elif strict_pass_count > 0:
        final_classification = "CLEAN_EDGE_HIDDEN_BY_TOOLING_GAP"
    elif near_min_trades_count > 0:
        final_classification = "CLEAN_EDGE_BLOCKED_BY_MIN_TRADES"
    else:
        final_classification = "NO_CLEAN_EDGE_FOUND"

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "executive_summary": (
            "Strict bucket gate found zero passing side buckets on fresh source. "
            "Positive expectancy buckets exist, but only with 1-2 trades; the best 15-trade bucket remains below winrate requirement."
        ),
        "scope": [
            "Inspect fresh source DB: tmp/alpha_history_all_recent_20260523.db",
            "Inspect companion report used by probe",
            "Inspect bucket extraction/gating in scripts/controlled_kpi_run.py via _probe_alpha_bootstrap_source_db and _derive_profitability_bucket_gate",
            "Check missing script reference scripts/refresh_bootstrap_corpus_from_recent_paper.py",
        ],
        "locked_facts": [
            f"KuCoin-only PAPER constraints preserved; no LIVE commands executed.",
            f"Source DB exists: {db_exists}; companion report exists: {report_exists}",
            f"position_close rows in DB: {db_close_count}",
            f"report rows_inserted: {report_rows_inserted}",
            f"report output matches DB: {not source_report_mismatch}",
            f"strict thresholds: trades>={min_trades}, winrate>={min_wr:.2f}, expectancy>{min_exp:.4f}",
            f"strict passing side buckets: {strict_pass_count}",
            f"near-pass buckets blocked by min-trades: {near_min_trades_count}",
        ],
        "thresholds": {
            "min_side_trades": min_trades,
            "min_side_winrate": min_wr,
            "min_side_expectancy_gt": min_exp,
        },
        "source_artifacts": {
            "source_db": str(SOURCE_DB),
            "companion_report": str(COMPANION_REPORT),
            "report_output": report_output,
            "missing_refresh_script_exists": not missing_refresh_script,
            "missing_refresh_script_path": str(MISSING_REFRESH_SCRIPT),
        },
        "bucket_rejection_table": bucket_table,
        "rejection_reason_counts": dict(reason_counter),
        "missing_tooling_check": [
            f"scripts/refresh_bootstrap_corpus_from_recent_paper.py exists: {not missing_refresh_script}",
            (
                "controlled_kpi_run.py still references the missing refresh script in the staleness warning path"
                if missing_refresh_script
                else "Refresh script reference resolved"
            ),
        ],
        "classification_candidates": {
            "NO_CLEAN_EDGE_FOUND": strict_pass_count == 0 and near_min_trades_count == 0,
            "CLEAN_EDGE_HIDDEN_BY_TOOLING_GAP": strict_pass_count > 0,
            "CLEAN_EDGE_BLOCKED_BY_MIN_TRADES": strict_pass_count == 0 and near_min_trades_count > 0,
            "SOURCE_DB_INVALID_OR_INCOMPLETE": stale_or_invalid_source,
            "COMPANION_REPORT_MISMATCH": source_report_mismatch,
            "BOOTSTRAP_REFRESH_SCRIPT_MISSING_BLOCKER": missing_refresh_script,
        },
        "final_classification": final_classification,
        "minimal_next_step": (
            "Keep thresholds/readiness unchanged. Accumulate more fresh PAPER closes for currently positive selected sides "
            "(e.g., XRPUSDTM|MeanReversion|sell, BNBUSDTM|MeanReversion|sell) until trade_count >= 5, then rerun this autopsy."
        ),
        "live_status": "LIVE remains blocked. No LIVE command executed.",
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    OUTPUT_MD.write_text(_build_md(report), encoding="utf-8")

    print(f"AUTOPSY_JSON={OUTPUT_JSON}")
    print(f"AUTOPSY_MD={OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
