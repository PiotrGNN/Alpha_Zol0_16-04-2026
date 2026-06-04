from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]

CLASS_REALIZED_PROFIT_TARGET_FOUND = "REALIZED_PROFITABILITY_OPERATING_POINT_FOUND"
CLASS_REALIZED_LOSS_DOMINANT = "REALIZED_PROFITABILITY_LOSS_DOMINANT"
CLASS_NO_TRADES = "REALIZED_PROFITABILITY_BLOCKED_BY_NO_TRADES"
CLASS_CONTAMINATED = "REALIZED_PROFITABILITY_EVIDENCE_CONTAMINATED"

CONTAMINATION_KEYS = ("seed", "fallback", "mock", "force_open", "forced_cycle")


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _canonical_strategy(value: Any) -> str:
    text = str(value or "").strip().upper().replace("_", "").replace("-", "")
    if text.endswith("V2"):
        text = text[:-2]
    aliases = {
        "MEANREVERSION": "MEANREVERSION",
        "MOMENTUM": "MOMENTUM",
        "MICROBREAKOUT": "MICROBREAKOUT",
        "TRENDFOLLOWING": "TRENDFOLLOWING",
    }
    return aliases.get(text, text)


def _is_contaminated(payload: dict[str, Any]) -> bool:
    flags = payload.get("contamination_flags")
    if not isinstance(flags, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict):
            flags = meta.get("contamination_flags")
    if not isinstance(flags, dict):
        return False
    for key in CONTAMINATION_KEYS:
        value = flags.get(key, 0)
        if value is True:
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _load_position_closes(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "logs" not in tables:
            return []
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(logs)")}
        event_col = "event" if "event" in columns else "event_type" if "event_type" in columns else None
        details_col = "details" if "details" in columns else "payload" if "payload" in columns else None
        timestamp_col = "timestamp" if "timestamp" in columns else "ts" if "ts" in columns else None
        if event_col is None or details_col is None:
            return []
        selected = [event_col, details_col]
        if timestamp_col:
            selected.append(timestamp_col)
        rows = []
        for row in conn.execute(f"SELECT {', '.join(selected)} FROM logs ORDER BY rowid ASC"):
            values = dict(zip(selected, row))
            if values.get(event_col) != "position_close":
                continue
            try:
                payload = json.loads(str(values.get(details_col) or "{}"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            payload["db_path"] = str(db_path)
            if timestamp_col:
                payload["db_timestamp"] = values.get(timestamp_col)
            rows.append(payload)
        return rows
    finally:
        conn.close()


def _normalize_trade(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    sizing = meta.get("sizing_trace") if isinstance(meta.get("sizing_trace"), dict) else {}
    cost_breakdown = meta.get("cost_breakdown") if isinstance(meta.get("cost_breakdown"), dict) else {}
    symbol = str(payload.get("symbol") or "").upper()
    strategy = _canonical_strategy(payload.get("strategy"))
    side = str(payload.get("side") or "").lower()
    return {
        "candidate_key": f"{symbol}:{strategy}:{side}",
        "symbol": symbol,
        "canonical_strategy": strategy,
        "side": side,
        "realized_pnl": _safe_float(payload.get("realized_pnl")),
        "exit_reason": payload.get("exit_reason") or payload.get("close_reason"),
        "notional_usdt": _safe_float(payload.get("notional_usdt")),
        "expected_net_after_full_cost": _safe_float(
            sizing.get("expected_net_after_full_cost") or meta.get("expected_net_after_full_cost")
        ),
        "runtime_profile_source": cost_breakdown.get("runtime_profile_source"),
        "contaminated": _is_contaminated(payload),
        "db_path": payload.get("db_path"),
    }


def _bucket_summary(rows: list[dict[str, Any]], min_trades: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["canonical_strategy"] != "MEANREVERSION":
            continue
        if row["side"] != "sell":
            continue
        buckets[row["candidate_key"]].append(row)
    summaries = []
    for key, bucket in buckets.items():
        pnls = [float(row["realized_pnl"]) for row in bucket]
        wins = [value for value in pnls if value > 0]
        losses = [abs(value) for value in pnls if value <= 0]
        gross_win = sum(wins)
        gross_loss = sum(losses)
        summaries.append(
            {
                "candidate_key": key,
                "symbol": bucket[0]["symbol"],
                "canonical_strategy": bucket[0]["canonical_strategy"],
                "side": bucket[0]["side"],
                "trade_count": len(pnls),
                "win_count": len(wins),
                "loss_count": len(losses),
                "win_rate": (len(wins) / len(pnls)) if pnls else 0.0,
                "net_pnl": sum(pnls),
                "avg_win": mean(wins) if wins else 0.0,
                "avg_loss_abs": mean(losses) if losses else 0.0,
                "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0),
                "avg_expected_net_after_full_cost": mean([row["expected_net_after_full_cost"] for row in bucket]),
                "exit_reason_counts": {
                    reason: sum(1 for row in bucket if row["exit_reason"] == reason)
                    for reason in sorted({row["exit_reason"] for row in bucket})
                },
                "passes_realized_target": (
                    len(pnls) >= min_trades
                    and sum(pnls) > 0.0
                    and ((len(wins) / len(pnls)) if pnls else 0.0) >= 0.55
                    and ((gross_win / gross_loss) if gross_loss > 0 else 999.0) >= 1.20
                ),
            }
        )
    summaries.sort(
        key=lambda row: (
            bool(row["passes_realized_target"]),
            row["net_pnl"],
            row["profit_factor"],
            row["trade_count"],
        ),
        reverse=True,
    )
    return summaries


def audit_realized_operating_point(db_paths: list[Path | str], min_trades: int = 5) -> dict[str, Any]:
    dbs = [Path(path) for path in db_paths]
    rows = [_normalize_trade(payload) for db in dbs for payload in _load_position_closes(db)]
    contaminated = [row for row in rows if row["contaminated"]]
    clean = [row for row in rows if not row["contaminated"]]
    buckets = _bucket_summary(clean, min_trades=min_trades)
    passing = [row for row in buckets if row["passes_realized_target"]]
    if contaminated:
        classification = CLASS_CONTAMINATED
    elif not clean:
        classification = CLASS_NO_TRADES
    elif passing:
        classification = CLASS_REALIZED_PROFIT_TARGET_FOUND
    else:
        classification = CLASS_REALIZED_LOSS_DOMINANT
    return {
        "classification": classification,
        "inputs": {"db_paths": [str(path) for path in dbs]},
        "objective": {
            "min_trades": min_trades,
            "win_rate_min": 0.55,
            "profit_factor_min": 1.20,
            "net_pnl_min": 0.0,
            "profitability_claim": False,
        },
        "summary": {
            "trade_count": len(rows),
            "clean_trade_count": len(clean),
            "contaminated_trade_count": len(contaminated),
            "bucket_count": len(buckets),
            "passing_bucket_count": len(passing),
            "net_pnl": sum(row["realized_pnl"] for row in clean),
            "win_rate": (sum(1 for row in clean if row["realized_pnl"] > 0) / len(clean)) if clean else 0.0,
        },
        "best_realized_bucket": passing[0] if passing else (buckets[0] if buckets else None),
        "ranked_buckets": buckets,
        "profitability_claim": False,
        "decision": _decision(classification),
    }


def _decision(classification: str) -> dict[str, Any]:
    if classification == CLASS_REALIZED_PROFIT_TARGET_FOUND:
        return {
            "next_step": "repeat_longer_paper_validation_before_any_profitability_claim",
            "patch_strategy": False,
            "patch_exit": False,
            "reason": "realized clean paper bucket passed net pnl, winrate, and profit factor guards",
        }
    if classification == CLASS_REALIZED_LOSS_DOMINANT:
        return {
            "next_step": "do_not_promote_current_meanreversion_h10_sizing_exit_profile",
            "patch_strategy": False,
            "patch_exit": False,
            "reason": "natural clean paper trades exist but realized pnl/profit factor fail the operating point objective",
        }
    if classification == CLASS_CONTAMINATED:
        return {
            "next_step": "discard_evidence_and_repeat_clean_paper",
            "patch_strategy": False,
            "patch_exit": False,
            "reason": "contaminated realized trades cannot support profitability decisions",
        }
    return {
        "next_step": "collect_natural_paper_trades",
        "patch_strategy": False,
        "patch_exit": False,
        "reason": "no realized paper trades were available",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Realized Profitability Operating Point Audit",
        "",
        f"- classification: `{report['classification']}`",
        f"- trade_count: `{report['summary']['trade_count']}`",
        f"- clean_trade_count: `{report['summary']['clean_trade_count']}`",
        f"- contaminated_trade_count: `{report['summary']['contaminated_trade_count']}`",
        f"- bucket_count: `{report['summary']['bucket_count']}`",
        f"- passing_bucket_count: `{report['summary']['passing_bucket_count']}`",
        f"- net_pnl: `{report['summary']['net_pnl']}`",
        f"- win_rate: `{report['summary']['win_rate']}`",
        f"- profitability_claim: `{report['profitability_claim']}`",
        f"- next_step: `{report['decision']['next_step']}`",
        "",
        "## Best Realized Bucket",
    ]
    best = report.get("best_realized_bucket")
    if best:
        lines.append(
            "- `{candidate}` trades=`{trades}` net=`{net}` win_rate=`{win}` pf=`{pf}` pass=`{passes}`".format(
                candidate=best["candidate_key"],
                trades=best["trade_count"],
                net=best["net_pnl"],
                win=best["win_rate"],
                pf=best["profit_factor"],
                passes=best["passes_realized_target"],
            )
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Ranked Buckets"])
    for row in report["ranked_buckets"][:20]:
        lines.append(
            "- `{candidate}` trades=`{trades}` net=`{net}` win_rate=`{win}` pf=`{pf}` exits=`{exits}`".format(
                candidate=row["candidate_key"],
                trades=row["trade_count"],
                net=row["net_pnl"],
                win=row["win_rate"],
                pf=row["profit_factor"],
                exits=row["exit_reason_counts"],
            )
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="append", default=[])
    parser.add_argument("--db-glob", default="")
    parser.add_argument("--min-trades", type=int, default=5)
    parser.add_argument("--output-json", default="analysis/realized_profitability_operating_point_current.json")
    parser.add_argument("--output-md", default="analysis/realized_profitability_operating_point_current.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_paths = [Path(path) for path in args.db]
    if args.db_glob:
        db_paths.extend(sorted(WORKDIR.glob(args.db_glob)))
    report = audit_realized_operating_point(db_paths, min_trades=args.min_trades)
    output_json = WORKDIR / args.output_json
    output_md = WORKDIR / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
